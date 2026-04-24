"""
ChatService — 家庭健康 RAG 问答服务
职责：
  1. 检索相关知识片段（KnowledgeService）
  2. 构造含健康背景 + 对话历史的 prompt
  3. 调用 LLM 生成回答（streaming / 非 streaming 两种模式）
  4. 安全过滤：拒绝非健康类问题
"""
from __future__ import annotations

from typing import AsyncIterator, Optional
from datetime import datetime

import structlog
from openai import AsyncOpenAI

from src.core.config import settings
from src.services.knowledge_service import KnowledgeService

log = structlog.get_logger()

# ── 系统提示词 ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """你是 LifePilot 家庭健康助手，一个专业、温暖的AI健康顾问。

【核心职责】
- 基于提供的权威健康知识回答用户关于家庭健康的问题
- 帮助用户理解健康数据、症状、用药、检验报告等
- 提供科学、通俗易懂的健康建议

【重要限制】
- 仅回答与健康、医疗、养生相关的问题
- 对于非健康类问题，礼貌拒绝并引导回到健康话题
- 不做出确定性诊断，建议严重情况及时就医
- 所有建议仅供参考，不替代医生诊断

【回答风格】
- 使用通俗易懂的中文
- 适当引用知识来源增加可信度
- 对老人/孩子相关问题使用更简单的语言
- 回答结构清晰，必要时使用列表

【免责声明】
如遇紧急医疗情况，请立即拨打120或前往最近急诊。
"""

_SAFETY_KEYWORDS = [
    "习近平", "政治", "军事", "武器", "黑客", "诈骗", "赌博",
    "色情", "暴力", "毒品", "自杀", "炸弹",
]

_HEALTH_CHECK_PROMPT = """判断以下问题是否与健康、医疗、养生、家庭护理相关。
只回答 yes 或 no。

问题：{question}"""


class ChatMessage:
    """对话消息"""
    def __init__(self, role: str, content: str, timestamp: Optional[datetime] = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.utcnow()

    def to_openai_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class ChatSession:
    """对话会话（多轮历史管理）"""
    MAX_HISTORY = 10  # 保留最近 N 轮对话

    def __init__(self):
        self.messages: list[ChatMessage] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append(ChatMessage(role, content))
        # 保留最近 MAX_HISTORY 轮（system 消息不计入）
        if len(self.messages) > self.MAX_HISTORY * 2:
            self.messages = self.messages[-self.MAX_HISTORY * 2:]

    def to_openai_messages(self) -> list[dict]:
        return [m.to_openai_dict() for m in self.messages]


class ChatService:
    """RAG 问答服务"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        openai_client: Optional[AsyncOpenAI] = None,
    ):
        self._knowledge = knowledge_service
        self._openai = openai_client or AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

    def _is_safe(self, question: str) -> bool:
        """基础安全过滤：拒绝敏感词"""
        q_lower = question.lower()
        return not any(kw in q_lower for kw in _SAFETY_KEYWORDS)

    def _build_rag_prompt(self, question: str, context_chunks: list[dict]) -> str:
        """将检索到的知识片段注入 prompt"""
        if not context_chunks:
            return question

        context_text = "\n\n".join(
            f"【来源：{c['source']} — {c['title']}】\n{c['text']}"
            for c in context_chunks
        )
        return (
            f"请基于以下健康知识回答用户问题。如果知识库中没有直接答案，"
            f"可以结合通用医学常识回答，但需说明。\n\n"
            f"=== 相关知识 ===\n{context_text}\n\n"
            f"=== 用户问题 ===\n{question}"
        )

    async def chat(
        self,
        question: str,
        session: ChatSession,
        member_context: Optional[dict] = None,
        top_k: int = 4,
    ) -> str:
        """
        非流式问答（完整回答一次性返回）。

        Args:
            question:       用户问题
            session:        当前对话会话（多轮历史）
            member_context: 可选的成员健康背景（如年龄、慢病情况）
            top_k:          RAG 检索 Top-K 片段数

        Returns:
            LLM 生成的回答文本
        """
        if not self._is_safe(question):
            return "抱歉，我只能回答与健康相关的问题。请问有什么健康方面需要了解的？"

        # RAG 检索
        context_chunks = await self._knowledge.search(question, top_k=top_k)

        # 构造用户消息（含知识片段）
        user_message = self._build_rag_prompt(question, context_chunks)

        # 构建消息列表
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # 注入成员健康背景
        if member_context:
            context_str = "、".join(f"{k}：{v}" for k, v in member_context.items() if v)
            if context_str:
                messages.append({
                    "role": "system",
                    "content": f"当前用户背景信息（仅供参考）：{context_str}"
                })

        messages.extend(session.to_openai_messages())
        messages.append({"role": "user", "content": user_message})

        resp = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )
        answer = resp.choices[0].message.content or ""

        # 更新对话历史（保存原始问题，不含 RAG 注入的 prompt）
        session.add("user", question)
        session.add("assistant", answer)

        sources = list({c["source"] for c in context_chunks if c["source"]})
        if sources:
            log.info("rag chat", sources=sources, top_k=len(context_chunks))

        return answer

    async def stream_chat(
        self,
        question: str,
        session: ChatSession,
        member_context: Optional[dict] = None,
        top_k: int = 4,
    ) -> AsyncIterator[str]:
        """
        流式问答（SSE / Server-Sent Events 模式）。
        每个 yield 是一小段增量文本。
        """
        if not self._is_safe(question):
            yield "抱歉，我只能回答与健康相关的问题。"
            return

        context_chunks = await self._knowledge.search(question, top_k=top_k)
        user_message = self._build_rag_prompt(question, context_chunks)

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        if member_context:
            context_str = "、".join(f"{k}：{v}" for k, v in member_context.items() if v)
            if context_str:
                messages.append({
                    "role": "system",
                    "content": f"当前用户背景信息：{context_str}"
                })
        messages.extend(session.to_openai_messages())
        messages.append({"role": "user", "content": user_message})

        full_answer = ""
        async with await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
            stream=True,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_answer += delta
                    yield delta

        session.add("user", question)
        session.add("assistant", full_answer)
