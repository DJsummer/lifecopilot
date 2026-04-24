"""检验单与报告模型"""
import uuid
from datetime import date
from enum import Enum

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class ReportType(str, Enum):
    BLOOD_ROUTINE = "blood_routine"         # 血常规
    BIOCHEMISTRY = "biochemistry"           # 生化
    URINE_ROUTINE = "urine_routine"         # 尿常规
    THYROID = "thyroid"                     # 甲状腺功能
    LIPID_PANEL = "lipid_panel"             # 血脂
    GLYCATED_HB = "glycated_hb"            # 糖化血红蛋白
    IMAGING = "imaging"                     # 影像（CT/B超等）
    OTHER = "other"


class LabReport(BaseModel):
    """医学检验/检查报告"""
    __tablename__ = "lab_reports"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[ReportType] = mapped_column(String(50), nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hospital: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # OSS/本地路径
    ocr_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)      # OCR 原始文本
    structured_data: Mapped[str | None] = mapped_column(Text, nullable=True)   # LLM 结构化 JSON
    llm_interpretation: Mapped[str | None] = mapped_column(Text, nullable=True) # LLM 通俗解读
    abnormal_items: Mapped[str | None] = mapped_column(Text, nullable=True)    # 异常项 JSON 数组
    has_abnormal: Mapped[bool] = mapped_column(default=False)

    member: Mapped["Member"] = relationship(back_populates="lab_reports")


from src.models.member import Member  # noqa: E402
