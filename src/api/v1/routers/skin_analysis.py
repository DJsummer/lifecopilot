"""皮肤/伤口照片辅助分析路由 — /api/v1/skin (T013)"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.skin_analysis import SkinAnalysisList, SkinAnalysisOut
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.member import Member
from src.models.skin_analysis import SkinAnalysis
from src.services.skin_analysis_service import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE_MB,
    analyze_skin_image,
)

log = structlog.get_logger()
router = APIRouter()


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


# ── POST /{member_id}/analyze ─────────────────────────────────────────
@router.post(
    "/{member_id}/analyze",
    response_model=SkinAnalysisOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传皮肤/伤口照片并 AI 辅助分析",
    description=(
        "支持 JPEG/PNG/WEBP/BMP 格式（≤10 MB）。"
        "系统将照片传给多模态 AI 模型（GPT-4o Vision）进行初步分析，"
        "返回可能情况、护理建议及风险等级。"
        "所有分析结果仅供参考，不构成医学诊断。"
    ),
)
async def analyze(
    member_id: uuid.UUID = Depends(_member_id_param),
    file: UploadFile = File(..., description="皮肤或伤口照片（JPEG/PNG/WEBP，≤10 MB）"),
    body_part: Optional[str] = Form(None, description="拍摄部位，如：左臂、背部（可选）"),
    user_description: Optional[str] = Form(None, description="症状补充描述（可选）"),
    db: AsyncSession = Depends(get_db),
):
    # ── 文件类型校验 ──────────────────────────────────────────────────
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支持的文件类型：{content_type}，请上传 JPEG/PNG/WEBP/BMP 图片",
        )

    image_bytes = await file.read()

    # ── 文件大小校验 ──────────────────────────────────────────────────
    if len(image_bytes) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过 {MAX_IMAGE_SIZE_MB} MB 限制",
        )

    # ── 调用分析服务 ──────────────────────────────────────────────────
    analysis = await analyze_skin_image(
        image_bytes=image_bytes,
        content_type=content_type,
        body_part=body_part,
        user_description=user_description,
    )

    # ── 写入数据库 ────────────────────────────────────────────────────
    record = SkinAnalysis(
        member_id=member_id,
        body_part=body_part,
        user_description=user_description,
        image_path=analysis["image_path"],
        result=analysis["result"],
        structured_analysis=analysis["structured_analysis"],
        llm_summary=analysis["llm_summary"],
        audit_model=analysis["audit_model"],
        occurred_at=analysis["occurred_at"],
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    log.info(
        "皮肤分析完成",
        member_id=str(member_id),
        result=record.result,
        model=record.audit_model,
    )
    return record


# ── GET /{member_id}/analyses ─────────────────────────────────────────
@router.get(
    "/{member_id}/analyses",
    response_model=SkinAnalysisList,
    summary="获取皮肤分析历史列表",
)
async def list_analyses(
    member_id: uuid.UUID = Depends(_member_id_param),
    result_filter: Optional[str] = Query(None, description="按结果等级过滤（normal/attention/visit_soon/emergency）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SkinAnalysis).where(SkinAnalysis.member_id == member_id)
    if result_filter:
        stmt = stmt.where(SkinAnalysis.result == result_filter)
    stmt = stmt.order_by(SkinAnalysis.occurred_at.desc())

    total_result = await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = total_result.scalar() or 0

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = await db.execute(stmt)
    items = rows.scalars().all()

    return SkinAnalysisList(total=total, items=list(items))


# ── GET /{member_id}/analyses/{analysis_id} ───────────────────────────
@router.get(
    "/{member_id}/analyses/{analysis_id}",
    response_model=SkinAnalysisOut,
    summary="获取皮肤分析详情",
)
async def get_analysis(
    analysis_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SkinAnalysis).where(
            SkinAnalysis.id == analysis_id,
            SkinAnalysis.member_id == member_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    return record


# ── DELETE /{member_id}/analyses/{analysis_id} ────────────────────────
@router.delete(
    "/{member_id}/analyses/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除皮肤分析记录",
)
async def delete_analysis(
    analysis_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SkinAnalysis).where(
            SkinAnalysis.id == analysis_id,
            SkinAnalysis.member_id == member_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    await db.delete(record)
    await db.commit()
