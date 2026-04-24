"""
LabReportService — 检验单 AI 解读服务（T012）
============================================
流程：
  1. 接收上传文件（图片/PDF）
  2. OCR 提取文字（优先 pytesseract，可选 PaddleOCR）
  3. LLM 解读：结构化提取 + 异常标注 + 通俗说明
  4. 保存到 LabReport 模型（ocr_raw_text / structured_data /
     llm_interpretation / abnormal_items / has_abnormal）

OCR 策略（按可用性自动降级）：
  - pytesseract + Pillow（轻量，支持中英文 chi_sim+eng）
  - PaddleOCR（精度更高，但依赖较重，可选安装）
  - 纯文本模式（文件已是 .txt，直接读取）

测试时通过 mock 绕过 OCR 和 OpenAI 调用。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# ── 支持的文件类型 ────────────────────────────────────────────────────
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp",
    "application/pdf",
    "text/plain",
}
MAX_FILE_SIZE_MB = 20


# ── OCR 实现 ─────────────────────────────────────────────────────────

def _ocr_with_tesseract(image_bytes: bytes) -> str:
    """使用 pytesseract 识别图片文字（中英文）"""
    import pytesseract
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img, lang="chi_sim+eng")


def _ocr_with_paddle(image_bytes: bytes) -> str:
    """使用 PaddleOCR 识别（需安装 paddleocr）"""
    from paddleocr import PaddleOCR
    import numpy as np
    from PIL import Image
    import io
    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result = ocr.ocr(np.array(img), cls=True)
    lines = []
    for line_group in (result or []):
        for item in (line_group or []):
            if item and len(item) >= 2:
                text_info = item[1]
                if text_info and len(text_info) >= 1:
                    lines.append(text_info[0])
    return "\n".join(lines)


def _ocr_pdf(pdf_bytes: bytes) -> str:
    """从 PDF 提取文字（先尝试 pdfplumber，再图像 OCR）"""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            texts = [p.extract_text() or "" for p in pdf.pages]
        text = "\n".join(texts).strip()
        if len(text) > 50:   # 文字型 PDF 直接返回
            return text
    except Exception as e:
        log.warning("pdfplumber failed: %s", e)

    # 图像型 PDF：用 pdf2image 转图片再 OCR
    try:
        import pdf2image
        images = pdf2image.convert_from_bytes(pdf_bytes, dpi=200)
        parts = []
        for img in images:
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            parts.append(_ocr_image(buf.getvalue()))
        return "\n".join(parts)
    except Exception as e:
        log.warning("pdf2image OCR failed: %s", e)
        return ""


def _ocr_image(image_bytes: bytes) -> str:
    """图片 OCR：优先 PaddleOCR，降级 tesseract"""
    try:
        return _ocr_with_paddle(image_bytes)
    except Exception:
        pass
    try:
        return _ocr_with_tesseract(image_bytes)
    except Exception as e:
        log.warning("tesseract OCR failed: %s", e)
        return ""


def extract_text(file_bytes: bytes, content_type: str) -> str:
    """
    根据文件类型提取文字。
    返回 OCR/提取的原始文本，失败时返回空字符串。
    """
    ct = content_type.lower()
    if ct == "text/plain":
        return file_bytes.decode("utf-8", errors="replace")
    if ct == "application/pdf":
        return _ocr_pdf(file_bytes)
    # 图片类
    return _ocr_image(file_bytes)


# ── LLM 解读 ─────────────────────────────────────────────────────────

_INTERPRET_SYSTEM = """你是一位资深临床检验科医师，擅长用通俗语言向患者解释医学报告。
你的任务是分析检验报告的 OCR 文字，完成以下工作：
1. 识别报告类型（血常规/生化/尿常规/甲状腺/血脂等）
2. 提取所有检验项目（名称、数值、单位、参考范围、是否异常）
3. 用通俗易懂的中文解释整体报告含义
4. 重点说明异常项及其临床意义

输出要求（严格 JSON 格式）：
{
  "report_type": "blood_routine",
  "structured_items": [
    {
      "name": "白细胞计数",
      "abbr": "WBC",
      "value": "12.5",
      "unit": "10^9/L",
      "reference_range": "4.0-10.0",
      "is_abnormal": true,
      "direction": "high",
      "clinical_hint": "偏高，提示可能存在感染或炎症"
    }
  ],
  "has_abnormal": true,
  "abnormal_summary": "共发现3项异常：WBC偏高（提示感染可能）、...",
  "interpretation": "整体解读，用通俗语言...",
  "advice": "建议就医咨询，请勿自行用药",
  "disclaimer": "本解读仅供参考，不构成医疗诊断，请结合临床症状咨询专业医师"
}"""

_INTERPRET_USER_TMPL = """以下是检验报告的 OCR 识别文字，请按要求分析：

{ocr_text}

请输出严格的 JSON，不要有任何多余文字。"""


class LabReportService:
    """检验单 AI 解读服务"""

    def __init__(self, openai_client: Optional[AsyncOpenAI] = None):
        self._openai = openai_client or AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

    async def interpret(self, ocr_text: str) -> dict:
        """
        调用 LLM 解读 OCR 文字，返回结构化结果字典。
        结果字段：report_type / structured_items / has_abnormal /
                  abnormal_summary / interpretation / advice / disclaimer
        """
        if not ocr_text.strip():
            return {
                "report_type": "other",
                "structured_items": [],
                "has_abnormal": False,
                "abnormal_summary": "",
                "interpretation": "OCR 未能提取到有效文字，请确认图片清晰度。",
                "advice": "请尝试重新上传更清晰的图片。",
                "disclaimer": "本解读仅供参考，不构成医疗诊断，请咨询专业医师。",
            }

        resp = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _INTERPRET_SYSTEM},
                {"role": "user", "content": _INTERPRET_USER_TMPL.format(ocr_text=ocr_text[:6000])},
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        raw = resp.choices[0].message.content or "{}"
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("LLM returned invalid JSON, raw=%s", raw[:200])
            result = {
                "report_type": "other",
                "structured_items": [],
                "has_abnormal": False,
                "abnormal_summary": "",
                "interpretation": raw,
                "advice": "请咨询专业医师",
                "disclaimer": "本解读仅供参考，不构成医疗诊断，请咨询专业医师。",
            }

        # 确保 disclaimer 始终存在
        result.setdefault(
            "disclaimer", "本解读仅供参考，不构成医疗诊断，请结合临床症状咨询专业医师。"
        )
        log.info(
            "lab report interpreted",
            has_abnormal=result.get("has_abnormal"),
            items=len(result.get("structured_items", [])),
        )
        return result

    async def process_upload(
        self, file_bytes: bytes, content_type: str
    ) -> tuple[str, dict]:
        """
        完整处理流程：OCR → LLM 解读
        返回 (ocr_raw_text, interpretation_dict)
        """
        ocr_text = extract_text(file_bytes, content_type)
        interpretation = await self.interpret(ocr_text)
        return ocr_text, interpretation
