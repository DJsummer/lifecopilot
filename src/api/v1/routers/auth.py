"""认证与家庭账户路由"""
import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.v1.schemas.auth import (
    FamilyRegisterRequest,
    FamilyResponse,
    LoginRequest,
    MemberCreateRequest,
    MemberResponse,
    MemberUpdateRequest,
    RefreshRequest,
    TokenResponse,
)
from src.core.database import get_db
from src.core.deps import get_current_admin, get_current_member, require_same_family
from src.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from src.models.member import Family, Member, MemberRole
from src.core.config import settings

log = structlog.get_logger()
router = APIRouter()


# ───────────────────────────────────────────────
# 注册家庭账户（同时创建第一个 admin 成员）
# ───────────────────────────────────────────────
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: FamilyRegisterRequest, db: AsyncSession = Depends(get_db)):
    # 邮箱唯一性检查
    existing = await db.scalar(select(Member).where(Member.email == body.email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "EMAIL_EXISTS", "message": "该邮箱已注册"})

    family = Family(name=body.family_name, invite_code=secrets.token_urlsafe(10)[:16])
    db.add(family)
    await db.flush()  # 获取 family.id

    member = Member(
        family_id=family.id,
        nickname=body.nickname,
        role=MemberRole.ADMIN,
        email=body.email,
        hashed_password=hash_password(body.password),
        gender=body.gender,
        birth_date=body.birth_date,
    )
    db.add(member)
    await db.flush()

    log.info("family registered", family_id=str(family.id), member_id=str(member.id))
    return TokenResponse(
        access_token=create_access_token(str(member.id), str(family.id), member.role),
        refresh_token=create_refresh_token(str(member.id)),
        member_id=member.id,
        family_id=family.id,
        role=member.role,
    )


# ───────────────────────────────────────────────
# 登录
# ───────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    member = await db.scalar(select(Member).where(Member.email == body.email))
    if not member or not member.hashed_password or not verify_password(body.password, member.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "邮箱或密码错误"},
        )
    log.info("member login", member_id=str(member.id))
    return TokenResponse(
        access_token=create_access_token(str(member.id), str(member.family_id), member.role),
        refresh_token=create_refresh_token(str(member.id)),
        member_id=member.id,
        family_id=member.family_id,
        role=member.role,
    )


# ───────────────────────────────────────────────
# 刷新 token
# ───────────────────────────────────────────────
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    _invalid = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_REFRESH_TOKEN", "message": "刷新令牌无效或已过期"},
    )
    try:
        payload = jwt.decode(body.refresh_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise _invalid
        member_id = uuid.UUID(payload["sub"])
    except (JWTError, ValueError):
        raise _invalid

    member = await db.get(Member, member_id)
    if not member:
        raise _invalid

    return TokenResponse(
        access_token=create_access_token(str(member.id), str(member.family_id), member.role),
        refresh_token=create_refresh_token(str(member.id)),
        member_id=member.id,
        family_id=member.family_id,
        role=member.role,
    )


# ───────────────────────────────────────────────
# 当前用户信息
# ───────────────────────────────────────────────
@router.get("/me", response_model=MemberResponse)
async def me(current: Member = Depends(get_current_member)):
    return current


# ───────────────────────────────────────────────
# 家庭信息（含成员列表，仅 admin）
# ───────────────────────────────────────────────
@router.get("/family", response_model=FamilyResponse)
async def get_family(current: Member = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Family).options(selectinload(Family.members)).where(Family.id == current.family_id)
    )
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "FAMILY_NOT_FOUND", "message": "家庭不存在"})
    return family


# ───────────────────────────────────────────────
# 添加家庭成员（仅 admin）
# ───────────────────────────────────────────────
@router.post("/family/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    body: MemberCreateRequest,
    current: Member = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.email:
        existing = await db.scalar(select(Member).where(Member.email == body.email))
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "EMAIL_EXISTS", "message": "该邮箱已注册"})

    member = Member(
        family_id=current.family_id,
        nickname=body.nickname,
        role=body.role,
        gender=body.gender,
        birth_date=body.birth_date,
        email=body.email,
        hashed_password=hash_password(body.password) if body.password else None,
    )
    db.add(member)
    await db.flush()
    log.info("member added", member_id=str(member.id), by=str(current.id))
    return member


# ───────────────────────────────────────────────
# 更新成员信息（自己或 admin）
# ───────────────────────────────────────────────
@router.patch("/family/members/{member_id}", response_model=MemberResponse)
async def update_member(
    member_id: uuid.UUID,
    body: MemberUpdateRequest,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    require_same_family(member_id, current)
    target = await db.get(Member, member_id)
    if not target or target.family_id != current.family_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "MEMBER_NOT_FOUND", "message": "成员不存在"})

    for field, val in body.model_dump(exclude_none=True).items():
        setattr(target, field, val)
    return target


# ───────────────────────────────────────────────
# 删除成员（仅 admin，不能删除自己）
# ───────────────────────────────────────────────
@router.delete("/family/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if member_id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "CANNOT_DELETE_SELF", "message": "不能删除自己"})
    target = await db.get(Member, member_id)
    if not target or target.family_id != current.family_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "MEMBER_NOT_FOUND", "message": "成员不存在"})
    await db.delete(target)
    log.info("member deleted", member_id=str(member_id), by=str(current.id))
