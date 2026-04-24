"""用药记录与提醒模型"""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class MedicationStatus(str, Enum):
    ACTIVE = "active"       # 正在服用
    PAUSED = "paused"       # 暂停
    COMPLETED = "completed" # 疗程结束


class AdherenceStatus(str, Enum):
    TAKEN = "taken"         # 已服
    MISSED = "missed"       # 漏服
    DELAYED = "delayed"     # 延迟服用
    SKIPPED = "skipped"     # 主动跳过


class Medication(BaseModel):
    """用药方案"""
    __tablename__ = "medications"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    generic_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dosage: Mapped[str] = mapped_column(String(100), nullable=False)   # eg. "5mg"
    frequency: Mapped[str] = mapped_column(String(100), nullable=False) # eg. "每日两次"
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[MedicationStatus] = mapped_column(
        String(20), nullable=False, default=MedicationStatus.ACTIVE
    )
    llm_description: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM 生成的通俗说明

    member: Mapped["Member"] = relationship(back_populates="medications")
    reminders: Mapped[list["MedicationReminder"]] = relationship(
        back_populates="medication", cascade="all, delete-orphan"
    )
    adherence_logs: Mapped[list["AdherenceLog"]] = relationship(
        back_populates="medication", cascade="all, delete-orphan"
    )


class MedicationReminder(BaseModel):
    """服药提醒设置"""
    __tablename__ = "medication_reminders"

    medication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medications.id", ondelete="CASCADE"), nullable=False
    )
    remind_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "08:00"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    medication: Mapped["Medication"] = relationship(back_populates="reminders")


class AdherenceLog(BaseModel):
    """服药依从性记录"""
    __tablename__ = "adherence_logs"

    medication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medications.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AdherenceStatus] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    medication: Mapped["Medication"] = relationship(back_populates="adherence_logs")


from src.models.member import Member  # noqa: E402
