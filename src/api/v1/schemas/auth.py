from __future__ import annotations
from typing import Optional
"""Pydantic 请求/响应 Schema：认证相关"""
import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator

from src.models.member import Gender, MemberRole


# ── 家庭注册 ─────────────────────────────────────────────────────────
class FamilyRegisterRequest(BaseModel):
    family_name: str = Field(..., min_length=1, max_length=100)
    nickname: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    gender: Optional[Gender] = None
    birth_date: Optional[date] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含至少一个数字")
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含至少一个字母")
        return v


# ── 登录 ──────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    member_id: uuid.UUID
    family_id: uuid.UUID
    role: MemberRole


# ── token 刷新 ────────────────────────────────────────────────────────
class RefreshRequest(BaseModel):
    refresh_token: str


# ── 成员 ──────────────────────────────────────────────────────────────
class MemberCreateRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=50)
    role: MemberRole = MemberRole.ADULT
    gender: Optional[Gender] = None
    birth_date: Optional[date] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=100)


class MemberUpdateRequest(BaseModel):
    nickname: Optional[str] = Field(default=None, min_length=1, max_length=50)
    gender: Optional[Gender] = None
    birth_date: Optional[date] = None
    avatar_url: Optional[str] = None
    notes: Optional[str] = None


class MemberResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    family_id: uuid.UUID
    nickname: str
    role: MemberRole
    gender: Optional[Gender]
    birth_date: Optional[date]
    avatar_url: Optional[str]
    email: Optional[str]


class FamilyResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    invite_code: str
    members: list[MemberResponse] = []
