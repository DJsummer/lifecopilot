"""营养规划模型（T014）"""
import uuid
from typing import Optional
from datetime import date
from enum import Enum

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


# ── 饮食偏好 ────────────────────────────────────────────────────────────

class DietType(str, Enum):
    NORMAL = "normal"              # 普通（无特殊限制）
    VEGETARIAN = "vegetarian"      # 素食
    VEGAN = "vegan"                # 纯素
    LOW_CARB = "low_carb"          # 低碳水
    LOW_SODIUM = "low_sodium"      # 低盐（高血压/肾病）
    LOW_SUGAR = "low_sugar"        # 低糖（糖尿病）
    LOW_FAT = "low_fat"            # 低脂（高血脂）
    HIGH_PROTEIN = "high_protein"  # 高蛋白（运动/增肌）
    GLUTEN_FREE = "gluten_free"    # 无麸质


class MealType(str, Enum):
    BREAKFAST = "breakfast"   # 早餐
    LUNCH = "lunch"           # 午餐
    DINNER = "dinner"         # 晚餐
    SNACK = "snack"           # 加餐/零食


# ── 食物营养素数据 ──────────────────────────────────────────────────────

class FoodItem(BaseModel):
    """食物营养素数据库（内置 + 用户自定义）"""
    __tablename__ = "food_items"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    name_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)   # 谷物/蔬菜/水果/肉类/乳制品/豆类/坚果/调料
    # 每 100g 营养素
    calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # 千卡
    protein: Mapped[Optional[float]] = mapped_column(Float, nullable=True)        # g
    fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)            # g
    carbohydrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # g
    fiber: Mapped[Optional[float]] = mapped_column(Float, nullable=True)          # g
    sodium: Mapped[Optional[float]] = mapped_column(Float, nullable=True)         # mg
    sugar: Mapped[Optional[float]] = mapped_column(Float, nullable=True)          # g
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="builtin")  # builtin / usda / custom
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ── 营养目标 ────────────────────────────────────────────────────────────

class NutritionGoal(BaseModel):
    """成员个性化营养目标"""
    __tablename__ = "nutrition_goals"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    diet_type: Mapped[DietType] = mapped_column(String(30), nullable=False, default=DietType.NORMAL)
    # 过敏原 JSON 数组（如 ["花生", "海鲜", "乳糖"]）
    allergies: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 饮食禁忌 JSON 数组（宗教/个人原因，如 ["猪肉"]）
    dietary_restrictions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 每日营养目标（LLM 生成 + 可手动覆盖）
    daily_calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_protein: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_carbohydrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_fiber: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_sodium: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # LLM 生成的营养建议说明
    llm_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="nutrition_goal")
    meal_plans: Mapped[list["MealPlan"]] = relationship(back_populates="nutrition_goal", cascade="all, delete-orphan")


# ── 每周食谱 ────────────────────────────────────────────────────────────

class MealPlan(BaseModel):
    """LLM 生成的每周食谱"""
    __tablename__ = "meal_plans"

    nutrition_goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nutrition_goals.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    # LLM 生成的 7 天食谱 JSON
    # [{day: "周一", meals: [{type: breakfast, dishes: [...], calories: ..., tips: ...}, ...]}]
    plan_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM 整体营养说明
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    nutrition_goal: Mapped["NutritionGoal"] = relationship(back_populates="meal_plans")
    member: Mapped["Member"] = relationship(back_populates="meal_plans")


# ── 饮食记录日志 ────────────────────────────────────────────────────────

class DietLog(BaseModel):
    """用户饮食记录（用于反馈实际摄入）"""
    __tablename__ = "diet_logs"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal_type: Mapped[MealType] = mapped_column(String(20), nullable=False)
    # 自由文本描述（LLM 辅助估算营养素）
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # LLM 估算的营养素（可能为空，失败时降级）
    estimated_calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_protein: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_carbohydrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # LLM 饮食反馈（健康提示、改善建议）
    llm_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="diet_logs")


from src.models.member import Member  # noqa: E402
