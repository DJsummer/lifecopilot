from __future__ import annotations
"""FastAPI 依赖注入：从请求头提取并校验 JWT，返回当前登录成员"""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import decode_access_token
from src.models.member import Member, MemberRole

bearer_scheme = HTTPBearer()

_AUTH_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "UNAUTHORIZED", "message": "认证失败，请重新登录"},
    headers={"WWW-Authenticate": "Bearer"},
)

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={"code": "FORBIDDEN", "message": "权限不足"},
)


async def get_current_member(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Member:
    """从 Bearer token 中解析并返回当前成员，任何路由均可注入"""
    try:
        payload = decode_access_token(credentials.credentials)
        member_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise _AUTH_ERROR

    member = await db.get(Member, member_id)
    if member is None:
        raise _AUTH_ERROR
    return member


async def get_current_admin(
    current: Member = Depends(get_current_member),
) -> Member:
    """要求当前成员角色为 admin"""
    if current.role != MemberRole.ADMIN:
        raise _FORBIDDEN
    return current


def require_same_family(member_id: uuid.UUID, current: Member) -> None:
    """校验目标成员与当前成员属于同一家庭，防止越权访问"""
    if member_id == current.id:
        return  # 访问自己，直接放行
    if current.role == MemberRole.ADMIN:
        return  # 家庭管理员可访问家庭内所有成员
    raise _FORBIDDEN
