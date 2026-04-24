"""心理健康筛查 — Pydantic Schemas（T016）"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator


# ── PHQ-9 / GAD-7 题目 ──────────────────────────────────────────────────

class QuestionnaireQuestion(BaseModel):
    index: int          # 0-based index
    text: str           # 题目文本


PHQ9_QUESTIONS: List[QuestionnaireQuestion] = [
    QuestionnaireQuestion(index=0, text="做事时提不起劲或没有兴趣"),
    QuestionnaireQuestion(index=1, text="感到心情低落、沮丧或绝望"),
    QuestionnaireQuestion(index=2, text="入睡困难、睡不安稳或睡眠过多"),
    QuestionnaireQuestion(index=3, text="感觉疲倦或没有活力"),
    QuestionnaireQuestion(index=4, text="食欲不振或吃太多"),
    QuestionnaireQuestion(index=5, text="觉得自己很糟，或觉得自己是个失败者，或让自己或家人失望"),
    QuestionnaireQuestion(index=6, text="对事物专注有困难，例如看报纸或看电视时"),
    QuestionnaireQuestion(index=7, text="动作或说话速度缓慢到别人已经察觉，或正好相反——烦躁或坐立不安、动来动去的情况更胜于平常"),
    QuestionnaireQuestion(index=8, text="有不如死掉或用某种方式伤害自己的念头"),
]

GAD7_QUESTIONS: List[QuestionnaireQuestion] = [
    QuestionnaireQuestion(index=0, text="感觉紧张、焦虑或烦躁"),
    QuestionnaireQuestion(index=1, text="无法停止或控制担忧"),
    QuestionnaireQuestion(index=2, text="对各种各样的事情担忧过多"),
    QuestionnaireQuestion(index=3, text="很难放松下来"),
    QuestionnaireQuestion(index=4, text="由于不安而无法静坐"),
    QuestionnaireQuestion(index=5, text="变得容易烦恼或急躁"),
    QuestionnaireQuestion(index=6, text="感到似乎将有可怕的事情发生而害怕"),
]


class PHQ9QuestionsResponse(BaseModel):
    questions: List[QuestionnaireQuestion]
    instructions: str = "请根据过去两周的感受，为每道题选择：0=完全没有，1=有几天，2=超过一半时间，3=几乎每天"


class GAD7QuestionsResponse(BaseModel):
    questions: List[QuestionnaireQuestion]
    instructions: str = "请根据过去两周的感受，为每道题选择：0=完全没有，1=有几天，2=超过一半时间，3=几乎每天"


# ── 情绪日记 ─────────────────────────────────────────────────────────────

class EmotionDiaryCreate(BaseModel):
    emotion_text: str
    emotion_tags: Optional[List[str]] = None
    occurred_at: Optional[datetime] = None

    @field_validator("emotion_text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("情绪日记内容不能为空")
        return v.strip()


# ── 量表评估 ─────────────────────────────────────────────────────────────

class AssessmentCreate(BaseModel):
    """提交量表答案（PHQ-9 / GAD-7 可单独或同时提交），可附带情绪日记"""
    phq9_answers: Optional[List[int]] = None    # 长度 9，每项 0-3
    gad7_answers: Optional[List[int]] = None    # 长度 7，每项 0-3
    emotion_text: Optional[str] = None          # 可选的附加日记
    emotion_tags: Optional[List[str]] = None
    occurred_at: Optional[datetime] = None

    @field_validator("phq9_answers")
    @classmethod
    def validate_phq9(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if len(v) != 9:
            raise ValueError("PHQ-9 需要恰好 9 道题的答案")
        if any(a not in (0, 1, 2, 3) for a in v):
            raise ValueError("PHQ-9 每道题答案须为 0、1、2 或 3")
        return v

    @field_validator("gad7_answers")
    @classmethod
    def validate_gad7(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if len(v) != 7:
            raise ValueError("GAD-7 需要恰好 7 道题的答案")
        if any(a not in (0, 1, 2, 3) for a in v):
            raise ValueError("GAD-7 每道题答案须为 0、1、2 或 3")
        return v


# ── 响应 Schema ──────────────────────────────────────────────────────────

class MentalHealthLogListItem(BaseModel):
    id: uuid.UUID
    entry_type: str
    risk_level: str
    mood_score: Optional[int]
    phq9_score: Optional[int]
    gad7_score: Optional[int]
    emotion_tags: Optional[List[str]]
    occurred_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class MentalHealthLogResponse(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    entry_type: str
    emotion_text: Optional[str]
    emotion_tags: Optional[List[str]]
    mood_score: Optional[int]
    nlp_analysis: Optional[str]
    phq9_answers: Optional[List[int]]
    phq9_score: Optional[int]
    gad7_answers: Optional[List[int]]
    gad7_score: Optional[int]
    risk_level: str
    resources: Optional[List[str]]
    occurred_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
