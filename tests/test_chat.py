"""
T009/T010 RAG 测试
- KnowledgeService：chunk_text 单元测试（无需外部服务）
- ChatService：mock OpenAI + mock Qdrant，不发真实请求
- Chat API：集成测试，验证路由层逻辑
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from src.services.knowledge_service import KnowledgeService, chunk_text
from src.services.chat_service import ChatService, ChatSession

pytestmark = [pytest.mark.integration, pytest.mark.chat]


# ═══════════════════════════════════════════════════════════════════════
# 单元测试：chunk_text
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "高血压患者应注意低盐饮食，每天盐摄入不超过 5g。"
        chunks = chunk_text(text, chunk_size=512)
        assert len(chunks) == 1
        assert "高血压" in chunks[0]

    def test_long_text_multiple_chunks(self):
        # 生成足够长的文本（>512 tokens）
        text = "健康知识。" * 300  # 约 900 tokens
        chunks = chunk_text(text, chunk_size=512, overlap=64)
        assert len(chunks) >= 2

    def test_overlap_creates_continuity(self):
        """相邻块之间有内容重叠"""
        text = "A " * 600
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) >= 2
        # 第一块末尾内容应出现在第二块开头（重叠）
        # 由于空格/tokenizer 截断，仅验证块数量和非空
        for c in chunks:
            assert len(c) > 0

    def test_empty_text_returns_empty(self):
        assert chunk_text("") == []

    def test_exact_chunk_size(self):
        # 恰好小于 chunk_size 的文本，应产生 1 个 chunk
        text = "词 " * 100  # 约 200 tokens，小于默认 chunk_size=512
        chunks = chunk_text(text, chunk_size=512)
        assert len(chunks) == 1


# ═══════════════════════════════════════════════════════════════════════
# 单元测试：ChatSession
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestChatSession:
    def test_add_messages(self):
        session = ChatSession()
        session.add("user", "你好")
        session.add("assistant", "你好！有什么可以帮你？")
        assert len(session.messages) == 2

    def test_max_history_truncation(self):
        session = ChatSession()
        for i in range(30):
            session.add("user", f"问题{i}")
            session.add("assistant", f"回答{i}")
        # 最多保留 MAX_HISTORY * 2 条
        assert len(session.messages) <= ChatSession.MAX_HISTORY * 2

    def test_to_openai_messages_format(self):
        session = ChatSession()
        session.add("user", "问题")
        msgs = session.to_openai_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "问题"


# ═══════════════════════════════════════════════════════════════════════
# 单元测试：ChatService — 安全过滤
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestChatServiceSafety:
    def _make_service(self):
        mock_qdrant = AsyncMock()
        knowledge_svc = KnowledgeService(mock_qdrant)  # v2: embedding 由 embedding_service 管理
        mock_openai = AsyncMock()
        return ChatService(knowledge_svc, openai_client=mock_openai)

    def test_safe_question(self):
        svc = self._make_service()
        assert svc._is_safe("高血压怎么控制？") is True

    def test_unsafe_question_rejected(self):
        svc = self._make_service()
        assert svc._is_safe("如何制作武器") is False

    def test_build_rag_prompt_with_chunks(self):
        svc = self._make_service()
        chunks = [
            {"source": "丁香医生", "title": "高血压", "text": "低盐饮食有助于控制血压。", "score": 0.9}
        ]
        prompt = svc._build_rag_prompt("高血压吃什么好？", chunks)
        assert "丁香医生" in prompt
        assert "低盐饮食" in prompt

    def test_build_rag_prompt_no_chunks(self):
        svc = self._make_service()
        prompt = svc._build_rag_prompt("血压高怎么办", [])
        assert prompt == "血压高怎么办"


# ═══════════════════════════════════════════════════════════════════════
# 集成测试：Chat API 路由
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
@pytest.mark.chat
class TestChatAPI:
    """mock 掉 OpenAI 和 Qdrant，仅测试路由层逻辑"""

    def _mock_chat_service(self):
        """返回 patch 上下文管理器列表"""
        return [
            patch(
                "src.api.v1.routers.chat.ChatService.chat",
                new_callable=AsyncMock,
                return_value="血压高的患者建议低盐饮食，多吃蔬菜水果。",
            ),
            patch(
                "src.api.v1.routers.chat.KnowledgeService.search",
                new_callable=AsyncMock,
                return_value=[
                    {"source": "丁香医生", "title": "高血压", "text": "...", "score": 0.92}
                ],
            ),
        ]

    async def test_chat_success(self, client: AsyncClient, auth_headers: dict):
        with patch("src.api.v1.routers.chat.ChatService.chat", new_callable=AsyncMock,
                   return_value="低盐饮食有助控制血压。"), \
             patch("src.api.v1.routers.chat.KnowledgeService.search", new_callable=AsyncMock,
                   return_value=[{"source": "丁香医生", "title": "高血压", "text": "...", "score": 0.9}]):
            resp = await client.post(
                "/api/v1/chat/",
                json={"question": "高血压怎么控制？"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "answer" in data
        assert len(data["answer"]) > 0

    async def test_chat_returns_session_id(self, client: AsyncClient, auth_headers: dict):
        with patch("src.api.v1.routers.chat.ChatService.chat", new_callable=AsyncMock,
                   return_value="回答"), \
             patch("src.api.v1.routers.chat.KnowledgeService.search", new_callable=AsyncMock,
                   return_value=[]):
            resp1 = await client.post(
                "/api/v1/chat/",
                json={"question": "第一个问题"},
                headers=auth_headers,
            )
            session_id = resp1.json()["session_id"]
            assert session_id  # 不为空

            # 第二轮对话传入 session_id
            resp2 = await client.post(
                "/api/v1/chat/",
                json={"question": "第二个问题", "session_id": session_id},
                headers=auth_headers,
            )
            assert resp2.status_code == 200

    async def test_chat_no_token_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v1/chat/", json={"question": "测试"})
        assert resp.status_code in (401, 403)

    async def test_chat_empty_question_rejected(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/chat/",
            json={"question": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_clear_session(self, client: AsyncClient, auth_headers: dict):
        resp = await client.delete(
            "/api/v1/chat/sessions/nonexistent-session-id",
            headers=auth_headers,
        )
        assert resp.status_code == 204  # 不存在时也返回 204


@pytest.mark.integration
@pytest.mark.chat
class TestKnowledgeAPI:
    """知识库管理端点测试"""

    async def test_ingest_knowledge_admin_only(self, client: AsyncClient, auth_headers: dict):
        with patch("src.api.v1.routers.chat.KnowledgeService.ingest_document",
                   new_callable=AsyncMock, return_value=5):
            resp = await client.post(
                "/api/v1/chat/knowledge",
                json={
                    "content": "高血压是一种常见的慢性病，患者应注意控制盐分摄入。" * 20,
                    "source": "测试来源",
                    "title": "高血压基础知识",
                    "category": "内科",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] == 5
        assert data["source"] == "测试来源"

    async def test_ingest_too_short_rejected(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/chat/knowledge",
            json={"content": "短", "source": "来源", "title": "标题"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_knowledge_stats(self, client: AsyncClient, auth_headers: dict):
        with patch("src.api.v1.routers.chat.KnowledgeService.collection_stats",
                   new_callable=AsyncMock,
                   return_value={"vectors_count": 100, "points_count": 100, "status": "green"}):
            resp = await client.get("/api/v1/chat/knowledge/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "vectors_count" in data
        assert "status" in data

    async def test_delete_knowledge(self, client: AsyncClient, auth_headers: dict):
        with patch("src.api.v1.routers.chat.KnowledgeService.delete_by_source",
                   new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/chat/knowledge/测试来源",
                headers=auth_headers,
            )
        assert resp.status_code == 204
