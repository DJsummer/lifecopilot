"""
ChatService — 家庭健康 RAG 问答服务（v3）
==========================================
核心升级：规则路由 → 真正的 LLM Tool Calling
（参考 FamilyHealthyAgent 架构）

工作流（两轮 LLM 调用）：
  Round 1 — 问题 + 三工具定义 → LLM 自主决定调用哪些工具（可并行多个）
  Execute  — 并行执行工具调用（Qdrant 向量检索）
  Round 2  — 问题 + 工具结果 → LLM 生成最终回答（可流式）

三工具（OpenAI Function Calling 格式）：
  check_red_flag  : 搜索危险症状库（50种紧急症状），判断是否需要立即就医
  get_triage      : 分诊导诊检索，帮助确定挂哪个科室
  search_disease  : 通用疾病/药物/健康知识检索（默认兜底）

其他能力：
  多成员记忆隔离  : _member_sessions[member_id] 每人独立对话历史
  个体化约束      : member_context（档案、用药、近期指标）注入 system prompt
  可追溯引用      : 回答附带 sources（source / title / category）

向后兼容：
  - ChatSession.add() / to_openai_messages() / MAX_HISTORY 不变
  - ChatService.chat(question, session, member_context, top_k) 签名不变
  - ChatService._is_safe() / _build_rag_prompt() 方法不变（供测试）
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import AsyncIterator, Optional

import structlog
from openai import AsyncOpenAI

from src.core.config import settings
from src.services.knowledge_service import KnowledgeService

log = structlog.get_logger()

# ── 安全过滤词 ────────────────────────────────────────────────────────
_SAFETY_KEYWORDS = [
    "习近平", "政治", "军事", "武器", "黑客", "诈骗", "赌博",
    "色情", "暴力", "毒品", "自杀", "炸弹",
]

# ── OpenAI Tool Calling 工具定义 ──────────────────────────────────────
# LLM 通过这三个 schema 自主决定调用哪些工具，不再依赖 if-else 关键词匹配
HEALTH_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "check_red_flag",
            "description": (
                "搜索危险症状库，检测用户描述的症状是否属于医疗紧急情况，"
                "例如胸痛、大出血、意识丧失、呼吸困难、脑卒中等危重症状。"
                "当用户描述急性或严重症状时优先调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户描述的症状或紧急情况，原话传入效果最好",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_triage",
            "description": (
                "分诊导诊检索，帮助用户确定应该挂哪个科室就诊。"
                "当用户询问'挂什么科'、'看哪个科'、'去哪个科室'、"
                "'应该看什么医生'、'要去哪个医院'等导诊类问题时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户的症状描述或就诊问题",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_disease",
            "description": (
                "搜索疾病科普、药物、健康知识库，回答一般性健康问题，"
                "包括疾病原因/预防/治疗、用药说明、检验报告解读、"
                "慢病管理、营养饮食、母婴健康等日常健康咨询。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户的健康问题，关键词尽量明确",
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "可选，限定知识分类提升检索精度。"
                            "可选值：disease（疾病科普）、drug（药物）、"
                            "triage（导诊）、general（通用）"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# ── 系统提示词 ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """你是 LifePilot 家庭健康助手，一个专业、温暖的AI健康顾问。

【核心职责】
- 基于提供的权威健康知识回答用户关于家庭健康的问题
- 帮助用户理解健康数据、症状、用药、检验报告等
- 提供科学、通俗易懂的健康建议

【重要限制】
- 仅回答与健康、医疗、养生相关的问题
- 不做出确定性诊断，建议严重情况及时就医
- 所有建议仅供参考，不替代执业医师诊断

【回答风格】
- 使用通俗易懂的中文
- 适当引用知识来源增加可信度
- 对老人/孩子相关问题使用更简单的语言
- 回答结构清晰，必要时使用列表

【免责声明】
如遇紧急医疗情况，请立即拨打120或前往最近急诊。本助手的所有建议仅供参考，不构成医疗诊断。
"""

_TOOL_RESULT_PROMPT = """你已经调用了健康知识工具，以下是检索到的参考资料：

{tool_results}

请基于以上资料回答用户的问题。如果资料中包含危险症状警告，必须在回答开头清晰提示用户立即就医或拨打120。
如果知识库中没有直接答案，可结合通用医学常识，但需注明"根据通用医学知识"。
所有建议仅供参考，不构成医疗诊断，末尾加免责声明。"""


# ── 对话消息 & 会话 ───────────────────────────────────────────────────

class ChatMessage:
    def __init__(self, role: str, content: str, timestamp: Optional[datetime] = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.utcnow()

    def to_openai_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class ChatSession:
    """单成员对话会话（多轮历史管理）"""
    MAX_HISTORY = 10

    def __init__(self):
        self.messages: list[ChatMessage] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append(ChatMessage(role, content))
        if len(self.messages) > self.MAX_HISTORY * 2:
            self.messages = self.messages[-self.MAX_HISTORY * 2:]

    def to_openai_messages(self) -> list[dict]:
        return [m.to_openai_dict() for m in self.messages]


# ── 多成员会话注册表 ──────────────────────────────────────────────────
# key: member_id (str），value: ChatSession
# 每个成员独立的持久化会话，互不干扰
_member_sessions: dict[str, ChatSession] = {}
_MAX_MEMBER_SESSIONS = 50_000


def get_or_create_member_session(member_id: str) -> ChatSession:
    """获取或新建成员专属会话（记忆隔离核心）"""
    if member_id not in _member_sessions:
        if len(_member_sessions) >= _MAX_MEMBER_SESSIONS:
            # 简单 LRU：删除最旧的 10%
            remove_keys = list(_member_sessions.keys())[:_MAX_MEMBER_SESSIONS // 10]
            for k in remove_keys:
                del _member_sessions[k]
        _member_sessions[member_id] = ChatSession()
    return _member_sessions[member_id]


def clear_member_session(member_id: str) -> None:
    """清除成员对话历史"""
    _member_sessions.pop(member_id, None)


# ── ChatService ───────────────────────────────────────────────────────

class ChatService:
    """RAG 问答服务（Agentic 三工具 + 多成员隔离）"""

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

    # ── 安全过滤 ──────────────────────────────────────────────────────

    def _is_safe(self, question: str) -> bool:
        q_lower = question.lower()
        return not any(kw in q_lower for kw in _SAFETY_KEYWORDS)

    # ── 工具执行 ──────────────────────────────────────────────────────

    async def _execute_tool(
        self, tool_name: str, tool_args: dict, top_k: int
    ) -> list[dict]:
        """
        执行单个工具调用，返回检索到的 chunks 列表。

        check_red_flag → 搜索 category=red_flag
        get_triage     → 搜索 category=triage
        search_disease → 搜索 category=disease（或 args 中指定的 category）
        """
        query = tool_args.get("query", "")
        if not query:
            return []

        if tool_name == "check_red_flag":
            return await self._knowledge.search(query, top_k=top_k, category="red_flag")

        if tool_name == "get_triage":
            return await self._knowledge.search(query, top_k=top_k, category="triage")

        if tool_name == "search_disease":
            category = tool_args.get("category") or "disease"
            chunks = await self._knowledge.search(query, top_k=top_k, category=category)
            if not chunks:
                # fallback：不限分类
                chunks = await self._knowledge.search(query, top_k=top_k)
            return chunks

        return []

    async def _run_tool_calling(
        self, question: str, base_messages: list[dict], top_k: int
    ) -> tuple[list[dict], list[dict]]:
        """
        Round 1：把问题 + 工具定义发给 LLM，LLM 自主决定调用哪些工具（可多个）。
        Execute：并行执行所有工具调用。
        返回 (tool_messages, all_chunks)

        tool_messages 格式（追加到 messages 后用于 Round 2）：
          [assistant_tool_call_msg, tool_result_msg, ...]
        """
        # Round 1：LLM 决定工具调用
        r1 = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=base_messages,
            tools=HEALTH_TOOLS,
            tool_choice="auto",  # LLM 自主选择
            temperature=0.1,     # 工具选择阶段用低温度
            max_tokens=256,      # 工具调用不需要长 token
        )
        assistant_msg = r1.choices[0].message

        # 如果 LLM 选择不调用工具（直接回答），返回空列表
        if not assistant_msg.tool_calls:
            log.info("tool_calling: LLM chose no tools, falling back to direct answer")
            return [], []

        log.info(
            "tool_calling: LLM selected tools",
            tools=[tc.function.name for tc in assistant_msg.tool_calls],
        )

        # Execute：并行调用所有工具
        tasks = [
            self._execute_tool(
                tc.function.name,
                json.loads(tc.function.arguments),
                top_k,
            )
            for tc in assistant_msg.tool_calls
        ]
        results_per_tool = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总 chunks 并构建 tool_messages（OpenAI 格式）
        all_chunks: list[dict] = []
        tool_messages: list[dict] = [assistant_msg.model_dump()]  # assistant 发起工具调用的消息

        for tc, chunks in zip(assistant_msg.tool_calls, results_per_tool):
            if isinstance(chunks, Exception):
                tool_content = f"工具调用失败：{chunks}"
                chunks = []
            else:
                all_chunks.extend(chunks)
                if chunks:
                    tool_content = "\n\n".join(
                        f"【{c.get('source', '')} — {c.get('title', '')}】\n{c.get('text', '')}"
                        for c in chunks
                    )
                else:
                    tool_content = "知识库中暂无相关内容。"

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": tool_content,
            })

        return tool_messages, all_chunks

    # ── Prompt 构建（向后兼容，供单元测试） ───────────────────────────

    def _build_rag_prompt(self, question: str, context_chunks: list[dict]) -> str:
        """将检索到的知识片段注入 prompt（供单元测试使用）"""
        if not context_chunks:
            return question
        context_text = "\n\n".join(
            f"【来源：{c['source']} — {c['title']}】\n{c['text']}"
            for c in context_chunks
        )
        return (
            f"请基于以下健康知识回答用户问题。如知识库中没有直接答案，"
            f"可结合通用医学常识，但需说明。\n\n"
            f"=== 相关知识 ===\n{context_text}\n\n"
            f"=== 用户问题 ===\n{question}"
        )

    def _build_member_system_prompt(self, member_context: Optional[dict]) -> Optional[str]:
        """根据成员档案生成个体化 system 提示"""
        if not member_context:
            return None
        parts: list[str] = []
        nickname = member_context.get("nickname")
        if nickname:
            parts.append(f"当前用户：{nickname}")
        age = member_context.get("age")
        role = member_context.get("role", "")
        if age:
            parts.append(f"年龄：{age}岁")
            if role == "elder" or (isinstance(age, int) and age >= 65):
                parts.append("（请使用更简单易懂的语言，注意老年人常见疾病风险）")
            elif role == "child" or (isinstance(age, int) and age < 18):
                parts.append("（儿科相关，请注意儿童用药剂量和发育特点）")
        if member_context.get("gender"):
            parts.append(f"性别：{member_context['gender']}")

        metrics = []
        for key in ["blood_pressure_sys", "blood_pressure_dia", "blood_glucose", "weight", "heart_rate"]:
            val = member_context.get(key)
            if val:
                metrics.append(f"{key}={val}")
        if metrics:
            parts.append(f"近期健康指标：{', '.join(metrics)}")

        meds = member_context.get("medications")
        if meds:
            parts.append(f"正在服用药物：{meds}")

        if not parts:
            return None
        return "【成员个人健康档案（仅供参考）】\n" + "\n".join(parts)

    def _build_base_messages(
        self,
        question: str,
        session: ChatSession,
        member_context: Optional[dict],
    ) -> list[dict]:
        """构建 Round 1 基础消息列表（system + 历史 + 当前问题）"""
        messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        member_sys = self._build_member_system_prompt(member_context)
        if member_sys:
            messages.append({"role": "system", "content": member_sys})
        messages.extend(session.to_openai_messages())
        messages.append({"role": "user", "content": question})
        return messages

    # ── 主接口：同步问答 ──────────────────────────────────────────────

    async def chat(
        self,
        question: str,
        session: ChatSession,
        member_context: Optional[dict] = None,
        top_k: int = 4,
    ) -> str:
        """
        两轮 Tool Calling 问答（完整回答一次性返回）：
          Round 1  — LLM 自主决定调用哪些工具
          Execute  — 并行执行工具（向量检索）
          Round 2  — LLM 生成最终回答
        """
        if not self._is_safe(question):
            return "抱歉，我只能回答与健康相关的问题。请问有什么健康方面需要了解的？"

        base_messages = self._build_base_messages(question, session, member_context)
        tool_messages, chunks = await self._run_tool_calling(base_messages=base_messages,
                                                              question=question,
                                                              top_k=top_k)

        # Round 2：生成最终回答
        if tool_messages:
            # 正常 Tool Calling 流程：base + tool_messages → 最终回答
            final_messages = base_messages + tool_messages
        else:
            # LLM 未调用工具（问题与健康无关或知识库为空）：直接生成
            final_messages = base_messages

        resp = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=final_messages,
            temperature=0.3,
            max_tokens=1500,
        )
        answer = resp.choices[0].message.content or ""

        # 更新对话历史（保存原始问题，不含工具调用细节）
        session.add("user", question)
        session.add("assistant", answer)

        log.info(
            "chat completed",
            tools_called=len(tool_messages) // 2 if tool_messages else 0,
            chunks=len(chunks),
        )
        return answer

    # ── 流式问答（SSE）────────────────────────────────────────────────

    async def stream_chat(
        self,
        question: str,
        session: ChatSession,
        member_context: Optional[dict] = None,
        top_k: int = 4,
    ) -> AsyncIterator[str]:
        """
        两轮 Tool Calling 流式问答：
          Round 1  — 非流式，LLM 决定工具（工具调用不需要流式）
          Execute  — 并行执行工具查询
          Round 2  — 流式，逐 token yield 最终回答
        """
        if not self._is_safe(question):
            yield "抱歉，我只能回答与健康相关的问题。"
            return

        base_messages = self._build_base_messages(question, session, member_context)
        tool_messages, chunks = await self._run_tool_calling(base_messages=base_messages,
                                                              question=question,
                                                              top_k=top_k)

        final_messages = base_messages + tool_messages if tool_messages else base_messages

        full_answer = ""
        async with await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=final_messages,
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
        log.info(
            "stream_chat completed",
            tools_called=len(tool_messages) // 2 if tool_messages else 0,
            chunks=len(chunks),
        )

