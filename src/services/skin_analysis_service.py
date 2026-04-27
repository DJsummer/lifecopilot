"""
SkinAnalysisService — 皮肤/伤口照片辅助分析服务（T013）
=======================================================
支持三种视觉分析后端（通过 SKIN_VISION_BACKEND 环境变量切换）：

  openai  — GPT-4o Vision（默认）
              SKIN_VISION_MODEL=gpt-4o
              OPENAI_API_KEY=sk-...

  ollama  — 本地 Ollama 服务，使用 OpenAI 兼容接口
              SKIN_VISION_MODEL=qwen2-vl:7b   # 或 llava:13b 等
              OLLAMA_BASE_URL=http://ollama:11434
              （需提前 `ollama pull qwen2-vl:7b`）

  local   — 纯本地 transformers 推理（Qwen2-VL-Instruct）
              SKIN_VISION_LOCAL_MODEL=Qwen/Qwen2-VL-7B-Instruct
              HF_CACHE_DIR=/app/models
              （需安装 transformers>=4.45 + torch>=2.1，建议 GPU）

流程：
  1. 接收上传图片（JPEG/PNG/WEBP/BMP），最大 10 MB
  2. 保存到本地 data/skin_images/ （生产可替换 OSS）
  3. 按后端调用视觉模型，返回 JSON 结构化分析
  4. 判断结果等级：normal / attention / visit_soon / emergency
  5. LLM 失败时静默降级：attention + 空结构化数据
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# ── 支持的图片类型 ────────────────────────────────────────────────────
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/gif": "gif",
}
MAX_IMAGE_SIZE_MB = 10

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上分析由 AI 辅助生成，仅供参考，不构成医学诊断。"
    "皮肤状况复杂多样，AI 无法替代专业皮肤科医生的面对面检查。"
    "如症状持续或加重，请及时就医。"
)

SYSTEM_PROMPT = """\
你是一位经验丰富的家庭健康 AI 助手，专门协助分析皮肤和伤口照片。

请根据用户上传的照片，严格按以下 JSON 格式输出分析结果（不要输出其他内容）：
{
  "result": "<normal|attention|visit_soon|emergency>",
  "findings": ["<观察到的特征1>", "<特征2>"],
  "possible_conditions": ["<可能的情况或名称>"],
  "care_advice": ["<护理或处置建议1>", "<建议2>"],
  "summary": "<用通俗中文写的 2-3 句话总结，包含结果级别解释>"
}

result 判断标准：
- normal: 皮肤状态正常，无异常迹象
- attention: 有轻微异常（如小擦伤、轻微红疹），建议观察，居家护理
- visit_soon: 有明显异常（如较深伤口、感染迹象、皮疹扩散），建议 1-3 天内就医
- emergency: 紧急情况（如严重烧伤、出血不止、蜂窝织炎迹象、坏死组织），建议立即就医

注意：
1. 严格只输出 JSON，不输出任何额外说明
2. findings 和 possible_conditions 最多各 5 条
3. care_advice 最多 5 条
4. 若图片模糊或无法判断，result 设为 attention，findings 中说明图片质量问题
"""


def _save_image_locally(image_bytes: bytes, content_type: str) -> str:
    """将图片保存到本地，返回相对路径"""
    ext = ALLOWED_IMAGE_TYPES.get(content_type, "jpg")
    filename = f"{uuid.uuid4().hex}.{ext}"
    save_dir = os.path.join("data", "skin_images")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, filename)
    with open(file_path, "wb") as f:
        f.write(image_bytes)
    return file_path


async def analyze_skin_image(
    image_bytes: bytes,
    content_type: str,
    body_part: Optional[str] = None,
    user_description: Optional[str] = None,
) -> dict:
    """
    主分析函数，按 SKIN_VISION_BACKEND 路由到对应后端。
    返回 dict：
    {
        image_path, result, structured_analysis (JSON str),
        llm_summary, audit_model, occurred_at
    }
    """
    image_path = _save_image_locally(image_bytes, content_type)

    user_context = ""
    if body_part:
        user_context += f"部位：{body_part}。"
    if user_description:
        user_context += f"用户描述：{user_description}"
    user_context = user_context or "请分析这张皮肤/伤口照片。"

    backend = settings.SKIN_VISION_BACKEND.lower()
    try:
        if backend == "ollama":
            raw, model_name = await _call_via_ollama(image_bytes, content_type, user_context)
        elif backend == "local":
            raw, model_name = await _call_local_qwen(image_bytes, user_context)
        else:
            raw, model_name = await _call_openai_vision(image_bytes, content_type, user_context)

        return _parse_result(raw, model_name, image_path)

    except Exception as e:
        log.warning("皮肤分析 LLM 调用失败，静默降级: %s", e)
        return _degraded_result(image_path)


# ── OpenAI 后端 ───────────────────────────────────────────────────────

async def _call_openai_vision(
    image_bytes: bytes,
    content_type: str,
    user_context: str,
) -> tuple[str, str]:
    """
    OpenAI 兼容接口（支持任何供应商）。
    优先使用 SKIN_VISION_API_KEY / SKIN_VISION_BASE_URL，
    未配置时回退到全局 OPENAI_API_KEY / OPENAI_BASE_URL。
    """
    b64 = base64.b64encode(image_bytes).decode()
    mime = content_type if content_type in ALLOWED_IMAGE_TYPES else "image/jpeg"
    model = settings.SKIN_VISION_MODEL

    client = AsyncOpenAI(
        api_key=settings._skin_api_key,
        base_url=settings._skin_base_url,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                },
                {"type": "text", "text": user_context},
            ],
        },
    ]
    resp = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=800, temperature=0.2
    )
    return resp.choices[0].message.content or "", model


# ── Ollama 后端 ───────────────────────────────────────────────────────

async def _call_via_ollama(
    image_bytes: bytes,
    content_type: str,
    user_context: str,
) -> tuple[str, str]:
    """
    通过 Ollama 的 OpenAI 兼容接口调用多模态模型（Qwen2-VL / LLaVA 等）。
    需提前 `ollama pull <model>`，Ollama >= 0.3.0 支持 vision。
    """
    b64 = base64.b64encode(image_bytes).decode()
    mime = content_type if content_type in ALLOWED_IMAGE_TYPES else "image/jpeg"
    model = settings.SKIN_VISION_MODEL  # 如 qwen2-vl:7b / llava:13b

    client = AsyncOpenAI(
        api_key="ollama",                              # Ollama 不校验 key
        base_url=f"{settings.OLLAMA_BASE_URL.rstrip('/')}/v1",
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
                {"type": "text", "text": user_context},
            ],
        },
    ]
    resp = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=800, temperature=0.2
    )
    return resp.choices[0].message.content or "", f"ollama/{model}"


# ── 本地 transformers 后端（Qwen2-VL）────────────────────────────────

async def _call_local_qwen(
    image_bytes: bytes,
    user_context: str,
) -> tuple[str, str]:
    """
    使用 HuggingFace transformers 本地推理 Qwen2-VL-Instruct。
    在 asyncio 线程池中执行，避免阻塞事件循环。
    """
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(
        None, _run_local_qwen_sync, image_bytes, user_context
    )
    return result


def _run_local_qwen_sync(image_bytes: bytes, user_context: str) -> tuple[str, str]:
    """同步推理函数，在线程池执行"""
    import io

    from PIL import Image

    try:
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
        import torch
    except ImportError as e:
        raise RuntimeError(
            "本地推理需要安装 transformers>=4.45 和 torch>=2.1：pip install transformers torch pillow"
        ) from e

    model_name = settings.SKIN_VISION_LOCAL_MODEL
    cache_dir = settings.HF_CACHE_DIR

    # 延迟加载（进程内缓存，避免每次推理重复加载）
    if not hasattr(_run_local_qwen_sync, "_model"):
        log.info("加载本地视觉模型: %s", model_name)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _run_local_qwen_sync._processor = AutoProcessor.from_pretrained(
            model_name, cache_dir=cache_dir, trust_remote_code=True
        )
        _run_local_qwen_sync._model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto",
            trust_remote_code=True,
        )
        _run_local_qwen_sync._device = device
        log.info("本地视觉模型加载完成，使用设备: %s", device)

    processor = _run_local_qwen_sync._processor
    model = _run_local_qwen_sync._model

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Qwen2-VL 的 chat template 格式
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": SYSTEM_PROMPT + "\n\n" + user_context},
            ],
        }
    ]

    text_input = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = processor.process_vision_info(messages)
    inputs = processor(
        text=[text_input],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to(model.device)

    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=800, temperature=0.2, do_sample=True)

    # 去掉输入 token
    generated_ids = [
        out[len(inp):]
        for inp, out in zip(inputs.input_ids, output_ids)
    ]
    raw = processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
    return raw, f"local/{model_name.split('/')[-1]}"


# ── 公共解析 ──────────────────────────────────────────────────────────

def _parse_result(raw: str, model_name: str, image_path: str) -> dict:
    import re

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}

    result_level = data.get("result", "attention")
    if result_level not in ("normal", "attention", "visit_soon", "emergency"):
        result_level = "attention"

    summary = data.get("summary", "AI 已完成初步分析，请参考建议。")
    return {
        "image_path": image_path,
        "result": result_level,
        "structured_analysis": json.dumps(data, ensure_ascii=False),
        "llm_summary": summary + DISCLAIMER,
        "audit_model": model_name,
        "occurred_at": datetime.now(timezone.utc),
    }


def _degraded_result(image_path: str) -> dict:
    return {
        "image_path": image_path,
        "result": "attention",
        "structured_analysis": None,
        "llm_summary": "AI 分析暂时不可用，图片已保存。建议咨询专业医生。" + DISCLAIMER,
        "audit_model": None,
        "occurred_at": datetime.now(timezone.utc),
    }
