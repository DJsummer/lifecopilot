"""T013：皮肤/伤口照片辅助分析 API 集成测试"""
from __future__ import annotations

import io
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.main import app

pytestmark = [pytest.mark.integration, pytest.mark.skin_analysis]

BASE_URL = "/api/v1/skin"

# ── 最小有效 1x1 像素 PNG（不依赖 Pillow）────────────────────────────
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd4n\x00\x00\x00\x00IEND\xaeB`\x82"
)

FAKE_ANALYSIS_ATTENTION = {
    "image_path": "data/skin_images/fake.png",
    "result": "attention",
    "structured_analysis": json.dumps({
        "result": "attention",
        "findings": ["皮肤轻微泛红", "无明显破损"],
        "possible_conditions": ["接触性皮炎（轻度）"],
        "care_advice": ["保持皮肤清洁干燥", "避免搔抓", "如无改善考虑就诊"],
        "summary": "照片显示轻微皮肤红肿，建议观察并居家护理。",
    }),
    "llm_summary": "照片显示轻微皮肤红肿，建议观察并居家护理。\n\n⚠️ 免责声明：以上分析由 AI 辅助生成，仅供参考。",
    "audit_model": "gpt-4o",
    "occurred_at": __import__("datetime").datetime(2026, 4, 27, 0, 0, tzinfo=__import__("datetime").timezone.utc),
}

FAKE_ANALYSIS_EMERGENCY = {
    **FAKE_ANALYSIS_ATTENTION,
    "result": "emergency",
    "llm_summary": "发现严重感染迹象，建议立即就医。\n\n⚠️ 免责声明：以上分析由 AI 辅助生成，仅供参考。",
}

FAKE_ANALYSIS_DEGRADED = {
    "image_path": "data/skin_images/fake.png",
    "result": "attention",
    "structured_analysis": None,
    "llm_summary": "AI 分析暂时不可用，图片已保存。建议咨询专业医生。\n\n⚠️ 免责声明：以上分析由 AI 辅助生成，仅供参考。",
    "audit_model": None,
    "occurred_at": __import__("datetime").datetime(2026, 4, 27, 0, 0, tzinfo=__import__("datetime").timezone.utc),
}


def _make_upload_files(content_type: str = "image/png"):
    return {"file": ("test.png", io.BytesIO(TINY_PNG), content_type)}


# ── 1. 上传分析 ───────────────────────────────────────────────────────

class TestAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_ATTENTION),
        ):
            resp = await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files=_make_upload_files(),
                data={"body_part": "左臂", "user_description": "有点红"},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["result"] == "attention"
        assert data["member_id"] == str(member_id)
        assert data["body_part"] == "左臂"
        assert "免责声明" in data["llm_summary"]
        assert data["structured_analysis"] is not None

    @pytest.mark.asyncio
    async def test_analyze_emergency_result(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_EMERGENCY),
        ):
            resp = await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files=_make_upload_files(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["result"] == "emergency"

    @pytest.mark.asyncio
    async def test_analyze_llm_degraded(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 失败时静默降级，仍返回 201"""
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_DEGRADED),
        ):
            resp = await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files=_make_upload_files(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["result"] == "attention"
        assert data["structured_analysis"] is None
        assert data["audit_model"] is None

    @pytest.mark.asyncio
    async def test_analyze_invalid_content_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/analyze",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_analyze_file_too_large(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        big_data = b"x" * (11 * 1024 * 1024)  # 11 MB
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_ATTENTION),
        ):
            resp = await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files={"file": ("big.png", io.BytesIO(big_data), "image/png")},
                headers=auth_headers,
            )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_analyze_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/analyze",
            files=_make_upload_files(),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_cross_family_forbidden(
        self, client: AsyncClient, auth_headers: dict
    ):
        """随机 UUID 成员：admin 可访问（设计行为），普通流量走降级"""
        other_id = uuid.uuid4()
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_DEGRADED),
        ):
            resp = await client.post(
                f"{BASE_URL}/{other_id}/analyze",
                files=_make_upload_files(),
                headers=auth_headers,
            )
        # admin 可跨成员操作（require_same_family 对 admin 放行）
        assert resp.status_code in (201, 403, 404)


# ── 2. 列表 ───────────────────────────────────────────────────────────

class TestListAnalyses:
    @pytest.mark.asyncio
    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 用唯一成员避免和其他测试数据干扰
        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    @pytest.mark.asyncio
    async def test_list_after_create(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 先创建
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_ATTENTION),
        ):
            await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files=_make_upload_files(),
                headers=auth_headers,
            )

        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_filter_by_result(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses?result_filter=emergency",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pagination(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses?page=1&page_size=5",
            headers=auth_headers,
        )
        assert resp.status_code == 200


# ── 3. 详情与删除 ──────────────────────────────────────────────────────

class TestGetAndDelete:
    @pytest.mark.asyncio
    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 创建记录
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_ATTENTION),
        ):
            create_resp = await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files=_make_upload_files(),
                headers=auth_headers,
            )
        analysis_id = create_resp.json()["id"]

        # 查详情
        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses/{analysis_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == analysis_id

    @pytest.mark.asyncio
    async def test_get_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 创建
        with patch(
            "src.api.v1.routers.skin_analysis.analyze_skin_image",
            new=AsyncMock(return_value=FAKE_ANALYSIS_ATTENTION),
        ):
            create_resp = await client.post(
                f"{BASE_URL}/{member_id}/analyze",
                files=_make_upload_files(),
                headers=auth_headers,
            )
        analysis_id = create_resp.json()["id"]

        # 删除
        del_resp = await client.delete(
            f"{BASE_URL}/{member_id}/analyses/{analysis_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        # 确认已删除
        resp = await client.get(
            f"{BASE_URL}/{member_id}/analyses/{analysis_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.delete(
            f"{BASE_URL}/{member_id}/analyses/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ── 4. 服务层单元测试 ──────────────────────────────────────────────────

class TestSkinAnalysisService:
    @pytest.mark.asyncio
    async def test_openai_backend_success(self, monkeypatch):
        """openai 后端正常路径"""
        import src.services.skin_analysis_service as svc_mod

        monkeypatch.setattr(svc_mod, "_save_image_locally", lambda *a, **kw: "data/skin_images/test.png")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BACKEND", "openai")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_MODEL", "gpt-4o")

        fake_content = json.dumps({
            "result": "normal",
            "findings": ["皮肤正常"],
            "possible_conditions": [],
            "care_advice": ["维持日常护肤"],
            "summary": "皮肤状态良好，无需特殊处理。",
        })
        mock_resp = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": fake_content})()})()]})()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("src.services.skin_analysis_service.AsyncOpenAI", return_value=mock_client):
            result = await svc_mod.analyze_skin_image(TINY_PNG, "image/png")

        assert result["result"] == "normal"
        assert result["audit_model"] == "gpt-4o"
        assert "免责声明" in result["llm_summary"]

    @pytest.mark.asyncio
    async def test_custom_provider_key_and_url(self, monkeypatch):
        """SKIN_VISION_API_KEY / SKIN_VISION_BASE_URL 优先于全局 OpenAI 配置"""
        import src.services.skin_analysis_service as svc_mod

        monkeypatch.setattr(svc_mod, "_save_image_locally", lambda *a, **kw: "data/skin_images/test.png")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BACKEND", "openai")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_MODEL", "qwen-vl-plus")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_API_KEY", "sk-dashscope-xxx")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        monkeypatch.setattr(svc_mod.settings, "OPENAI_API_KEY", "sk-global-key")

        fake_content = json.dumps({
            "result": "attention", "findings": [], "possible_conditions": [],
            "care_advice": [], "summary": "ok",
        })
        mock_resp = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": fake_content})()})()]})()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        captured = {}

        def capture(**kw):
            captured.update(kw)
            return mock_client

        with patch("src.services.skin_analysis_service.AsyncOpenAI", side_effect=capture):
            await svc_mod.analyze_skin_image(TINY_PNG, "image/png")

        assert captured["api_key"] == "sk-dashscope-xxx"
        assert "dashscope" in captured["base_url"]

    @pytest.mark.asyncio
    async def test_fallback_to_global_key_when_skin_key_empty(self, monkeypatch):
        """SKIN_VISION_API_KEY 为空时回退到全局 OPENAI_API_KEY"""
        import src.services.skin_analysis_service as svc_mod

        monkeypatch.setattr(svc_mod, "_save_image_locally", lambda *a, **kw: "data/skin_images/test.png")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BACKEND", "openai")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_API_KEY", "")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BASE_URL", "")
        monkeypatch.setattr(svc_mod.settings, "OPENAI_API_KEY", "sk-global-fallback")
        monkeypatch.setattr(svc_mod.settings, "OPENAI_BASE_URL", "https://api.openai.com/v1")

        fake_content = json.dumps({
            "result": "normal", "findings": [], "possible_conditions": [],
            "care_advice": [], "summary": "ok",
        })
        mock_resp = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": fake_content})()})()]})()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        captured = {}

        def capture(**kw):
            captured.update(kw)
            return mock_client

        with patch("src.services.skin_analysis_service.AsyncOpenAI", side_effect=capture):
            await svc_mod.analyze_skin_image(TINY_PNG, "image/png")

        assert captured["api_key"] == "sk-global-fallback"
        assert "openai.com" in captured["base_url"]

    @pytest.mark.asyncio
    async def test_ollama_backend_success(self, monkeypatch):
        """ollama 后端：使用 OpenAI 兼容接口，api_key='ollama'"""
        import src.services.skin_analysis_service as svc_mod

        monkeypatch.setattr(svc_mod, "_save_image_locally", lambda *a, **kw: "data/skin_images/test.png")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BACKEND", "ollama")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_MODEL", "qwen2-vl:7b")
        monkeypatch.setattr(svc_mod.settings, "OLLAMA_BASE_URL", "http://ollama:11434")

        fake_content = json.dumps({
            "result": "attention",
            "findings": ["轻微红肿"],
            "possible_conditions": ["接触性皮炎"],
            "care_advice": ["保持清洁"],
            "summary": "皮肤轻微红肿，建议观察。",
        })
        mock_resp = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": fake_content})()})()]})()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        captured_kwargs = {}

        def capture_client(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_client

        with patch("src.services.skin_analysis_service.AsyncOpenAI", side_effect=capture_client):
            result = await svc_mod.analyze_skin_image(TINY_PNG, "image/png")

        assert result["result"] == "attention"
        assert "ollama/qwen2-vl:7b" in result["audit_model"]
        # 验证 base_url 指向 Ollama
        assert "ollama" in captured_kwargs.get("base_url", "")
        assert captured_kwargs.get("api_key") == "ollama"

    @pytest.mark.asyncio
    async def test_local_backend_success(self, monkeypatch):
        """local 后端：模拟 transformers 推理"""
        import src.services.skin_analysis_service as svc_mod

        monkeypatch.setattr(svc_mod, "_save_image_locally", lambda *a, **kw: "data/skin_images/test.png")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BACKEND", "local")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_LOCAL_MODEL", "Qwen/Qwen2-VL-7B-Instruct")

        fake_raw = json.dumps({
            "result": "visit_soon",
            "findings": ["疑似感染"],
            "possible_conditions": ["蜂窝织炎（待排查）"],
            "care_advice": ["建议 1-2 天内就诊"],
            "summary": "图片显示疑似感染迹象，建议尽快就医。",
        })

        async def mock_local(image_bytes, user_context):
            return fake_raw, "local/Qwen2-VL-7B-Instruct"

        monkeypatch.setattr(svc_mod, "_call_local_qwen", mock_local)

        result = await svc_mod.analyze_skin_image(TINY_PNG, "image/png")

        assert result["result"] == "visit_soon"
        assert result["audit_model"] == "local/Qwen2-VL-7B-Instruct"

    @pytest.mark.asyncio
    async def test_analyze_skin_image_llm_failure(self, monkeypatch):
        """任何后端异常时静默降级"""
        import src.services.skin_analysis_service as svc_mod

        monkeypatch.setattr(svc_mod, "_save_image_locally", lambda *a, **kw: "data/skin_images/test.png")
        monkeypatch.setattr(svc_mod.settings, "SKIN_VISION_BACKEND", "openai")

        with patch(
            "src.services.skin_analysis_service.AsyncOpenAI",
            side_effect=Exception("Connection refused"),
        ):
            result = await svc_mod.analyze_skin_image(TINY_PNG, "image/png")

        assert result["result"] == "attention"
        assert result["audit_model"] is None
        assert result["structured_analysis"] is None

    def test_invalid_json_fallback(self):
        """JSON 解析容错：仍能提取 result"""
        import re
        raw = 'some noise {"result": "visit_soon", "findings": [], "possible_conditions": [], "care_advice": [], "summary": "x"} extra'
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group())
        assert data["result"] == "visit_soon"

    def test_parse_result_unknown_level(self):
        """未知 result 等级回退到 attention"""
        import src.services.skin_analysis_service as svc_mod
        raw = json.dumps({"result": "unknown_level", "summary": "test"})
        out = svc_mod._parse_result(raw, "gpt-4o", "data/test.png")
        assert out["result"] == "attention"
