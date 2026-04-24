"""检验单 AI 解读路由 — /api/v1/lab-reports (T012)"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.lab_report import (
    AbnormalItem,
    LabReportCompareItem,
    LabReportDetail,
    LabReportSummary,
    LabReportUploadResponse,
    StructuredItem,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.member import Member
from src.models.report import LabReport, ReportType
from src.services.lab_report_service import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE_MB,
    LabReportService,
)

log = structlog.get_logger()
router = APIRouter()

# -----------------------------------------------------------------------
_SERVICE: Optional[LabReportService] = None


def _get_service() -> LabReportService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = LabReportService()
    return _SERVICE


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


def _build_upload_response(report: LabReport, llm_result: dict) -> LabReportUploadResponse:
    """从 ORM 对象 + LLM 结果构造响应 schema"""
    raw_items = llm_result.get("structured_items") or []
    structured_items = [StructuredItem(**i) for i in raw_items if isinstance(i, dict)]

    return LabReportUploadResponse(
        report_id=report.id,
        member_id=report.member_id,
        report_type=report.report_type,
        report_date=report.report_date,
        hospital=report.hospital,
        has_abnormal=report.has_abnormal,
        abnormal_summary=llm_result.get("abnormal_summary"),
        structured_items=structured_items,
        interpretation=llm_result.get("interpretation", ""),
        advice=llm_result.get("advice"),
        disclaimer=llm_result.get("disclaimer", "本解读仅供参考，不构成医疗诊断，请咨询专业医师。"),
        ocr_raw_text=report.ocr_raw_text,
    )


# ── POST /{member_id}/upload ─────────────────────────────────────────
@router.post(
    "/{member_id}/upload",
    response_model=LabReportUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传并 AI 解读检验单",
    description=(
        "支持 JPG/PNG/PDF/TXT 格式（≤20 MB）。"
        "系统自动 OCR 识别文字，再由 AI 医师进行专业解读，"
        "返回结构化检验项目与通俗说明。"
    ),
)
async def upload_report(
    member_id: uuid.UUID = Depends(_member_id_param),
    file: UploadFile = File(..., description="检验单图片或 PDF"),
    report_date: date = Form(..., description="报告日期（YYYY-MM-DD）"),
    report_type: ReportType = Form(ReportType.OTHER, description="报告类型"),
    hospital: Optional[str] = Form(None, description="医院名称（可选）"),
    db: AsyncSession = Depends(get_db),
    svc: LabReportService = Depends(_get_service),
):
    # ── 文件类型与大小校验 ─────────────────────────────────────────────
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "UNSUPPORTED_FILE_TYPE",
                "message": f"不支持的文件类型：{content_type}，请上传图片（JPG/PNG）或 PDF",
            },
        )

    file_bytes = await file.read()
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"文件大小超过限制 {MAX_FILE_SIZE_MB} MB",
            },
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMPTY_FILE", "message": "文件内容为空"},
        )

    # ── OCR + LLM 解读 ────────────────────────────────────────────────
    ocr_text, llm_result = await svc.process_upload(file_bytes, content_type)

    # ── 解析 LLM 返回的字段 ───────────────────────────────────────────
    has_abnormal = bool(llm_result.get("has_abnormal", False))
    structured_data_str = json.dumps(
        llm_result.get("structured_items", []), ensure_ascii=False
    )
    abnormal_items_str = json.dumps(
        [
            item
            for item in (llm_result.get("structured_items") or [])
            if isinstance(item, dict) and item.get("is_abnormal")
        ],
        ensure_ascii=False,
    )
    interpretation_text = (
        llm_result.get("interpretation", "")
        + ("\n\n建议：" + llm_result["advice"] if llm_result.get("advice") else "")
        + "\n\n"
        + llm_result.get("disclaimer", "")
    )

    # 如果 LLM 返回了 report_type，尝试覆盖用户传入的值
    llm_report_type = llm_result.get("report_type")
    if llm_report_type and llm_report_type in [e.value for e in ReportType]:
        report_type = ReportType(llm_report_type)

    # ── 保存数据库 ────────────────────────────────────────────────────
    report = LabReport(
        member_id=member_id,
        report_type=report_type,
        report_date=report_date,
        hospital=hospital,
        file_path=None,                         # 本 task 不做文件存储，留空
        ocr_raw_text=ocr_text or None,
        structured_data=structured_data_str,
        llm_interpretation=interpretation_text,
        abnormal_items=abnormal_items_str,
        has_abnormal=has_abnormal,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    log.info(
        "lab report uploaded",
        member_id=str(member_id),
        report_type=report_type,
        has_abnormal=has_abnormal,
    )
    return _build_upload_response(report, llm_result)


# ── GET /{member_id}/compare — 异常趋势对比（需在 {report_id} 路由前注册）──
@router.get(
    "/{member_id}/compare",
    response_model=List[LabReportCompareItem],
    summary="检验异常项趋势对比",
    description="返回最近 N 份同类报告的异常项列表，便于纵向追踪变化趋势。",
)
async def compare_reports(
    member_id: uuid.UUID = Depends(_member_id_param),
    report_type: ReportType = Query(..., description="报告类型（必填）"),
    limit: int = Query(5, ge=2, le=10, description="最近 N 份报告"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LabReport)
        .where(
            LabReport.member_id == member_id,
            LabReport.report_type == report_type,
        )
        .order_by(LabReport.report_date.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    reports = result.scalars().all()

    items = []
    for r in reports:
        abnormal_items: List[AbnormalItem] = []
        if r.abnormal_items:
            try:
                raw = json.loads(r.abnormal_items)
                abnormal_items = [
                    AbnormalItem(
                        name=i.get("name", ""),
                        value=i.get("value"),
                        unit=i.get("unit"),
                        direction=i.get("direction"),
                    )
                    for i in raw
                    if isinstance(i, dict)
                ]
            except Exception:
                pass
        items.append(
            LabReportCompareItem(
                report_id=r.id,
                report_date=r.report_date,
                abnormal_items=abnormal_items,
            )
        )
    return items


# ── GET /{member_id} — 报告列表 ──────────────────────────────────────
@router.get(
    "/{member_id}",
    response_model=List[LabReportSummary],
    summary="获取成员检验报告列表",
)
async def list_reports(
    member_id: uuid.UUID = Depends(_member_id_param),
    report_type: Optional[ReportType] = Query(None, description="按报告类型过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LabReport)
        .where(LabReport.member_id == member_id)
        .order_by(LabReport.report_date.desc())
        .limit(limit)
        .offset(offset)
    )
    if report_type:
        stmt = stmt.where(LabReport.report_type == report_type)

    result = await db.execute(stmt)
    reports = result.scalars().all()

    items = []
    for r in reports:
        abnormal_summary = None
        if r.structured_data:
            try:
                structured = json.loads(r.structured_data)
                abnormal_names = [
                    i.get("name", "") for i in structured if isinstance(i, dict) and i.get("is_abnormal")
                ]
                if abnormal_names:
                    abnormal_summary = "异常项：" + "、".join(abnormal_names[:5])
            except Exception:
                pass

        items.append(
            LabReportSummary(
                report_id=r.id,
                member_id=r.member_id,
                report_type=r.report_type,
                report_date=r.report_date,
                hospital=r.hospital,
                has_abnormal=r.has_abnormal,
                abnormal_summary=abnormal_summary,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
        )
    return items


# ── GET /{member_id}/{report_id} — 报告详情 ─────────────────────────
@router.get(
    "/{member_id}/{report_id}",
    response_model=LabReportDetail,
    summary="获取单份检验报告详情",
)
async def get_report(
    report_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(LabReport, report_id)
    if report is None or report.member_id != member_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_NOT_FOUND", "message": "报告不存在"},
        )

    # 从 structured_data 解析 LLM 结果还原详情
    structured_items: List[StructuredItem] = []
    llm_result: dict = {}
    if report.structured_data:
        try:
            raw_items = json.loads(report.structured_data)
            structured_items = [StructuredItem(**i) for i in raw_items if isinstance(i, dict)]
        except Exception:
            pass

    # 解析 abnormal_summary（从 llm_interpretation 提取或从异常项列表推导）
    abnormal_summary = None
    if report.abnormal_items:
        try:
            abnormal = json.loads(report.abnormal_items)
            names = [i.get("name", "") for i in abnormal if isinstance(i, dict)]
            if names:
                abnormal_summary = "异常项：" + "、".join(names[:5])
        except Exception:
            pass

    return LabReportDetail(
        report_id=report.id,
        member_id=report.member_id,
        report_type=report.report_type,
        report_date=report.report_date,
        hospital=report.hospital,
        has_abnormal=report.has_abnormal,
        abnormal_summary=abnormal_summary,
        structured_items=structured_items,
        interpretation=report.llm_interpretation or "",
        advice=None,
        disclaimer="本解读仅供参考，不构成医疗诊断，请结合临床症状咨询专业医师。",
        ocr_raw_text=report.ocr_raw_text,
        created_at=report.created_at.isoformat() if report.created_at else None,
    )


# ── DELETE /{member_id}/{report_id} — 删除报告 ──────────────────────
@router.delete(
    "/{member_id}/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除检验报告",
)
async def delete_report(
    report_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(LabReport, report_id)
    if report is None or report.member_id != member_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_NOT_FOUND", "message": "报告不存在"},
        )
    await db.delete(report)
    await db.commit()
    log.info("lab report deleted", report_id=str(report_id))

