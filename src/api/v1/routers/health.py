"""健康数据录入路由 — /api/v1/health"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.health import (
    HealthRecordBatchCreate,
    HealthRecordBatchResponse,
    HealthRecordCreate,
    HealthRecordListResponse,
    HealthRecordResponse,
    HealthSummaryResponse,
    MetricStats,
    _METRIC_UNITS,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.health import HealthRecord, MetricType
from src.models.member import Member
from src.services.alert_service import check_and_create_alert

log = structlog.get_logger()
router = APIRouter()


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
) -> uuid.UUID:
    """校验请求者有权操作目标成员（同家庭）"""
    require_same_family(member_id, current)
    return member_id


# ── 录入单条健康数据 ─────────────────────────────────────────────────
@router.post(
    "/{member_id}/records",
    response_model=HealthRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="录入单条健康数据",
)
async def create_record(
    body: HealthRecordCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    unit = _METRIC_UNITS.get(body.metric_type, "")
    record = HealthRecord(
        member_id=member_id,
        metric_type=body.metric_type,
        value=body.value,
        unit=unit,
        measured_at=body.measured_at,
        source=body.source,
        notes=body.notes,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 自动检测阈值告警（静默降级，不阻塞录入）
    try:
        await check_and_create_alert(
            member_id=member_id,
            metric_type=body.metric_type.value,
            value=body.value,
            triggered_at=record.measured_at,
            db=db,
        )
        await db.commit()
    except Exception as exc:
        log.warning("告警检测失败（静默忽略）: %s", exc)

    log.info("health record created", member_id=str(member_id), metric=body.metric_type)
    return record


# ── 批量录入（JSON 列表） ─────────────────────────────────────────────
@router.post(
    "/{member_id}/records/batch",
    response_model=HealthRecordBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="批量录入健康数据（JSON）",
)
async def batch_create_records(
    body: HealthRecordBatchCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    created = 0
    errors: list[str] = []
    for i, item in enumerate(body.records):
        try:
            unit = _METRIC_UNITS.get(item.metric_type, "")
            record = HealthRecord(
                member_id=member_id,
                metric_type=item.metric_type,
                value=item.value,
                unit=unit,
                measured_at=item.measured_at,
                source=item.source,
                notes=item.notes,
            )
            db.add(record)
            created += 1
        except Exception as e:
            errors.append(f"[{i}] {e}")
    await db.commit()
    return HealthRecordBatchResponse(created=created, failed=len(errors), errors=errors)


# ── CSV 批量导入 ──────────────────────────────────────────────────────
@router.post(
    "/{member_id}/records/import-csv",
    response_model=HealthRecordBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="CSV 批量导入历史健康数据",
    description="""CSV 格式（UTF-8，含表头）：
`metric_type,value,measured_at,source,notes`

- `metric_type`：枚举值（blood_pressure_sys / blood_pressure_dia / heart_rate / blood_glucose / weight / height / body_temperature / spo2 / steps / sleep_hours）
- `measured_at`：ISO 8601 格式，例如 `2026-01-01T08:00:00+08:00`
- `source`：manual / wearable / import（默认 import）
- `notes`：可选备注
""",
)
async def import_csv(
    file: UploadFile,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_FILE", "message": "仅支持 .csv 文件"})
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail={"code": "FILE_TOO_LARGE", "message": "文件不能超过 5MB"})

    content = await file.read()
    text = content.decode("utf-8-sig")  # 兼容 Excel 导出的 BOM
    reader = csv.DictReader(io.StringIO(text))

    created = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):  # 从第 2 行开始（第 1 行是表头）
        try:
            metric_type = MetricType(row["metric_type"].strip())
            value = float(row["value"].strip())
            measured_at = datetime.fromisoformat(row["measured_at"].strip())
            source = row.get("source", "import").strip() or "import"
            notes = row.get("notes", "").strip() or None

            # 值域校验（复用 schema 逻辑）
            body = HealthRecordCreate(
                metric_type=metric_type,
                value=value,
                measured_at=measured_at,
                source=source,
                notes=notes,
            )
            unit = _METRIC_UNITS.get(body.metric_type, "")
            record = HealthRecord(
                member_id=member_id,
                metric_type=body.metric_type,
                value=body.value,
                unit=unit,
                measured_at=body.measured_at,
                source=body.source,
                notes=body.notes,
            )
            db.add(record)
            created += 1
        except Exception as e:
            errors.append(f"第 {i} 行：{e}")

    await db.commit()
    log.info("csv import done", member_id=str(member_id), created=created, failed=len(errors))
    return HealthRecordBatchResponse(created=created, failed=len(errors), errors=errors)


# ── 查询健康记录列表 ──────────────────────────────────────────────────
@router.get(
    "/{member_id}/records",
    response_model=HealthRecordListResponse,
    summary="查询健康记录列表",
)
async def list_records(
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    metric_type: Optional[MetricType] = Query(default=None, description="按指标类型过滤"),
    start_time: Optional[datetime] = Query(default=None, description="起始时间（含）"),
    end_time: Optional[datetime] = Query(default=None, description="结束时间（含）"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(HealthRecord).where(HealthRecord.member_id == member_id)
    if metric_type:
        stmt = stmt.where(HealthRecord.metric_type == metric_type)
    if start_time:
        stmt = stmt.where(HealthRecord.measured_at >= start_time)
    if end_time:
        stmt = stmt.where(HealthRecord.measured_at <= end_time)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.scalar(total_stmt)) or 0

    stmt = stmt.order_by(HealthRecord.measured_at.desc()).limit(limit).offset(offset)
    items = list((await db.scalars(stmt)).all())
    return HealthRecordListResponse(total=total, items=items)


# ── 删除单条记录 ──────────────────────────────────────────────────────
@router.delete(
    "/{member_id}/records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除一条健康记录",
)
async def delete_record(
    record_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(HealthRecord, record_id)
    if not record or record.member_id != member_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "记录不存在"})
    await db.delete(record)
    await db.commit()


# ── 健康数据统计摘要 ──────────────────────────────────────────────────
@router.get(
    "/{member_id}/summary",
    response_model=HealthSummaryResponse,
    summary="各指标统计摘要（最新值 / 最大最小 / 均值）",
)
async def health_summary(
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365, description="统计最近 N 天"),
):
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats: list[MetricStats] = []
    for metric in MetricType:
        stmt = (
            select(HealthRecord)
            .where(
                HealthRecord.member_id == member_id,
                HealthRecord.metric_type == metric,
                HealthRecord.measured_at >= since,
            )
            .order_by(HealthRecord.measured_at.desc())
        )
        records = list((await db.scalars(stmt)).all())
        if not records:
            continue
        values = [r.value for r in records]
        stats.append(
            MetricStats(
                metric_type=metric,
                unit=_METRIC_UNITS.get(metric, ""),
                count=len(values),
                latest_value=records[0].value,
                latest_at=records[0].measured_at,
                min_value=min(values),
                max_value=max(values),
                avg_value=round(sum(values) / len(values), 2),
            )
        )
    return HealthSummaryResponse(member_id=member_id, stats=stats)
