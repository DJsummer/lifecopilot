"""T012：检验单 AI 解读 API 集成测试"""
from __future__ import annotations

import json
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from src.main import app
from src.api.v1.routers.lab_report import _get_service

pytestmark = [pytest.mark.integration, pytest.mark.lab_report]

# ── 测试用 mock 数据 ──────────────────────────────────────────────────────────

FAKE_LLM_RESULT = {
    "report_type": "blood_routine",
    "structured_items": [
        {
            "name": "白细胞计数",
            "abbr": "WBC",
            "value": "12.5",
            "unit": "10^9/L",
            "reference_range": "4.0-10.0",
            "is_abnormal": True,
            "direction": "high",
            "clinical_hint": "偏高，提示可能存在感染或炎症",
        },
        {
            "name": "血红蛋白",
            "abbr": "HGB",
            "value": "138",
            "unit": "g/L",
            "reference_range": "120-160",
            "is_abnormal": False,
            "direction": None,
            "clinical_hint": "正常范围内",
        },
    ],
    "has_abnormal": True,
    "abnormal_summary": "共发现 1 项异常：WBC 偏高（提示感染可能）",
    "interpretation": "您的血常规显示白细胞计数偏高，可能提示存在感染或炎症，建议就诊。",
    "advice": "建议尽快就医，完善感染指标检查。",
    "disclaimer": "本解读仅供参考，不构成医疗诊断，请结合临床症状咨询专业医师。",
}

FAKE_OCR_TEXT = "白细胞计数 12.5 10^9/L ↑ 参考范围 4.0-10.0"


def _fake_png() -> bytes:
    """最小 1x1 PNG（OCR 会被 mock，无需真实图像）"""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ── mock 工具 ─────────────────────────────────────────────────────────────────

def _mock_svc():
    svc = MagicMock()
    svc.process_upload = AsyncMock(return_value=(FAKE_OCR_TEXT, FAKE_LLM_RESULT))
    return svc


def _override_svc():
    """通过 FastAPI dependency_overrides 注入 mock 服务（需 try/finally 清理）"""
    mock = _mock_svc()
    app.dependency_overrides[_get_service] = lambda: mock


def _restore_svc():
    app.dependency_overrides.pop(_get_service, None)


# ─────────────────────────────────────────────────────────────────────────────

class TestUploadReport:
    """POST /{member_id}/upload"""

    async def test_upload_png_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常 PNG 上传，返回 201 及 AI 解读"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("report.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-15", "report_type": "blood_routine", "hospital": "协和医院"},
            )
        finally:
            _restore_svc()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["has_abnormal"] is True
        assert data["report_type"] == "blood_routine"
        assert data["hospital"] == "协和医院"
        assert len(data["structured_items"]) == 2
        assert data["structured_items"][0]["name"] == "白细胞计数"
        assert "disclaimer" in data

    async def test_upload_returns_ocr_text(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """响应中返回 OCR 原始文字供用户核查"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("report.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-15"},
            )
        finally:
            _restore_svc()

        assert resp.status_code == 201
        assert resp.json()["ocr_raw_text"] == FAKE_OCR_TEXT

    async def test_upload_pdf(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """PDF 文件应被接受"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("report.pdf", BytesIO(b"%PDF-1.4 mock"), "application/pdf")},
                data={"report_date": "2026-01-15"},
            )
        finally:
            _restore_svc()
        assert resp.status_code == 201

    async def test_upload_txt(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """纯文本文件上传"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("report.txt", BytesIO(b"WBC 12.5"), "text/plain")},
                data={"report_date": "2026-01-15"},
            )
        finally:
            _restore_svc()
        assert resp.status_code == 201

    async def test_upload_unsupported_file_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """不支持的格式返回 415"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/lab-reports/{member_id}/upload",
            headers=auth_headers,
            files={"file": ("report.xlsx", BytesIO(b"fake excel"), "application/vnd.ms-excel")},
            data={"report_date": "2026-01-15"},
        )
        assert resp.status_code == 415

    async def test_upload_empty_file(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """空文件返回 400"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("empty.png", BytesIO(b""), "image/png")},
                data={"report_date": "2026-01-15"},
            )
        finally:
            _restore_svc()
        assert resp.status_code == 400

    async def test_upload_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        """未携带 token 时，HTTPBearer 拒绝请求（401/403）"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/lab-reports/{member_id}/upload",
            files={"file": ("report.png", BytesIO(_fake_png()), "image/png")},
            data={"report_date": "2026-01-15"},
        )
        assert resp.status_code in (401, 403)

    async def test_upload_self_always_allowed(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """用户可以为自己上传报告（member_id == current.id）"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("report.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-15"},
            )
        finally:
            _restore_svc()
        assert resp.status_code == 201


class TestListReports:
    """GET /{member_id}"""

    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """新用户没有报告，返回空列表"""
        member_id = registered_family["member_id"]
        resp = await client.get(f"/api/v1/lab-reports/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_shows_uploaded_report(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """上传后列表应包含该报告"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("r.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-10"},
            )
        finally:
            _restore_svc()

        resp = await client.get(f"/api/v1/lab-reports/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert items[0]["has_abnormal"] is True

    async def test_list_filter_by_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """按 report_type 过滤"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("r.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-10"},
            )
        finally:
            _restore_svc()

        resp = await client.get(
            f"/api/v1/lab-reports/{member_id}?report_type=blood_routine",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["report_type"] == "blood_routine"


class TestGetReportDetail:
    """GET /{member_id}/{report_id}"""

    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """能获取单份报告详情"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            up_resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("r.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-10"},
            )
        finally:
            _restore_svc()
        report_id = up_resp.json()["report_id"]

        resp = await client.get(
            f"/api/v1/lab-reports/{member_id}/{report_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_id"] == report_id
        assert "structured_items" in data
        assert "disclaimer" in data

    async def test_get_nonexistent_returns_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """不存在的 report_id 返回 404"""
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"/api/v1/lab-reports/{member_id}/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404


class TestDeleteReport:
    """DELETE /{member_id}/{report_id}"""

    async def test_delete_report(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """删除后再查询应返回 404"""
        member_id = registered_family["member_id"]
        _override_svc()
        try:
            up_resp = await client.post(
                f"/api/v1/lab-reports/{member_id}/upload",
                headers=auth_headers,
                files={"file": ("r.png", BytesIO(_fake_png()), "image/png")},
                data={"report_date": "2026-01-12"},
            )
        finally:
            _restore_svc()
        report_id = up_resp.json()["report_id"]

        del_resp = await client.delete(
            f"/api/v1/lab-reports/{member_id}/{report_id}", headers=auth_headers
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(
            f"/api/v1/lab-reports/{member_id}/{report_id}", headers=auth_headers
        )
        assert get_resp.status_code == 404


class TestCompareReports:
    """GET /{member_id}/compare"""

    async def test_compare_requires_report_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """不传 report_type 查询参数应返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"/api/v1/lab-reports/{member_id}/compare", headers=auth_headers
        )
        assert resp.status_code == 422

    async def test_compare_returns_trend(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """上传 2 份同类报告后，compare 返回相应条目"""
        member_id = registered_family["member_id"]
        for date_str in ("2026-01-05", "2026-01-10"):
            _override_svc()
            try:
                await client.post(
                    f"/api/v1/lab-reports/{member_id}/upload",
                    headers=auth_headers,
                    files={"file": ("r.png", BytesIO(_fake_png()), "image/png")},
                    data={"report_date": date_str, "report_type": "blood_routine"},
                )
            finally:
                _restore_svc()

        resp = await client.get(
            f"/api/v1/lab-reports/{member_id}/compare?report_type=blood_routine",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 2
        for item in items:
            assert "report_date" in item
            assert "abnormal_items" in item


class TestLabReportService:
    """LabReportService 单元测试（不依赖 HTTP 层）"""

    async def test_interpret_empty_ocr(self):
        """OCR 为空时，interpret 应返回提示而非报错"""
        from src.services.lab_report_service import LabReportService

        svc = LabReportService.__new__(LabReportService)
        result = await svc.interpret("")
        assert result["has_abnormal"] is False
        assert "OCR" in result["interpretation"]

    async def test_extract_text_txt(self):
        """text/plain 文件直接解码"""
        from src.services.lab_report_service import extract_text

        text = extract_text(b"WBC 12.5", "text/plain")
        assert "WBC" in text

    async def test_interpret_invalid_json_fallback(self):
        """LLM 返回非 JSON 时应优雅降级"""
        from src.services.lab_report_service import LabReportService

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "这不是JSON文本"
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        svc = LabReportService(openai_client=mock_client)
        result = await svc.interpret("WBC 12.5 偏高")
        assert isinstance(result, dict)
        assert "disclaimer" in result

    async def test_interpret_valid_json(self):
        """LLM 返回合法 JSON 时正确解析"""
        from src.services.lab_report_service import LabReportService

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps(FAKE_LLM_RESULT)
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        svc = LabReportService(openai_client=mock_client)
        result = await svc.interpret("WBC 12.5 偏高")
        assert result["has_abnormal"] is True
        assert len(result["structured_items"]) == 2
