"""
GrowthService — 儿童生长发育评估服务（T007）
=============================================
功能：
  1. WHO 生长标准内置数据（0-60 月龄，男/女，身高/体重 L/M/S 参数）
  2. LMS 方法计算百分位 & Z-score
       z = ((value/M)^L - 1) / (L * S)
       percentile = Φ(z)  [正态累积分布]
  3. GrowthCategory 分级（P1/P3/P15/P85/P97/P99 分界）
  4. 系统预设发育里程碑（AAP/WHO 参考）
  5. LLM 生成综合生长评估总结（失败时静默降级）

WHO LMS 参数来源：
  WHO Child Growth Standards (2006) — WHO Multicentre Growth Reference Study
  数据子集（每个月龄取关键值），已内置在代码中避免外部文件依赖。
  完整数据: https://www.who.int/tools/child-growth-standards/standards
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.config import settings
from src.models.growth import (
    GrowthCategory, GrowthRecord, DevelopmentMilestone,
    MilestoneType, MilestoneStatus,
)
from src.models.member import Member

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上评估由 AI 生成，数据基于 WHO 生长标准参考值，"
    "仅供家长参考，不构成医学诊断。如有疑虑请咨询儿科医生。"
)

# ── WHO LMS 参数表 ────────────────────────────────────────────────────
# 格式：{ month_age: (L, M, S) }
# 来源：WHO Child Growth Standards 2006
# 覆盖月龄 0-60（每月一个值），男/女分开
# L=Box-Cox 幂次, M=中位数, S=变异系数

# 男孩身高(cm) LMS（0-60月）
_HFA_BOY: dict[int, tuple[float, float, float]] = {
    0: (-0.3521, 49.8842, 0.03795), 1: (0.2536, 54.7244, 0.03557),
    2: (0.1458, 58.4249, 0.03424), 3: (0.0706, 61.4292, 0.03328),
    4: (0.0148, 63.8860, 0.03257), 5: (-0.0340, 65.9026, 0.03204),
    6: (-0.0781, 67.6236, 0.03165), 7: (-0.1182, 69.1645, 0.03139),
    8: (-0.1550, 70.5994, 0.03124), 9: (-0.1890, 71.9687, 0.03117),
    10: (-0.2204, 73.2812, 0.03118), 11: (-0.2494, 74.5388, 0.03125),
    12: (-0.2762, 75.7488, 0.03137), 13: (-0.3011, 76.9186, 0.03153),
    14: (-0.3241, 78.0497, 0.03172), 15: (-0.3453, 79.1458, 0.03194),
    16: (-0.3649, 80.2113, 0.03217), 17: (-0.3829, 81.2487, 0.03242),
    18: (-0.3994, 82.2587, 0.03269), 19: (-0.4145, 83.2418, 0.03296),
    20: (-0.4283, 84.1994, 0.03325), 21: (-0.4409, 85.1348, 0.03353),
    22: (-0.4523, 86.0477, 0.03384), 23: (-0.4626, 86.9410, 0.03414),
    24: (-0.4718, 87.8161, 0.03445), 25: (-0.4801, 88.6742, 0.03475),
    26: (-0.4874, 89.5166, 0.03506), 27: (-0.4939, 90.3441, 0.03538),
    28: (-0.4996, 91.1581, 0.03569), 29: (-0.5046, 91.9576, 0.03600),
    30: (-0.5090, 92.7446, 0.03631), 31: (-0.5128, 93.5196, 0.03662),
    32: (-0.5160, 94.2838, 0.03693), 33: (-0.5186, 95.0377, 0.03723),
    34: (-0.5208, 95.7819, 0.03753), 35: (-0.5225, 96.5167, 0.03783),
    36: (-0.5238, 97.2427, 0.03812), 37: (-0.5248, 97.9602, 0.03841),
    38: (-0.5253, 98.6698, 0.03869), 39: (-0.5256, 99.3717, 0.03897),
    40: (-0.5255, 100.0664, 0.03925), 41: (-0.5251, 100.7540, 0.03952),
    42: (-0.5245, 101.4348, 0.03979), 43: (-0.5237, 102.1091, 0.04005),
    44: (-0.5227, 102.7771, 0.04031), 45: (-0.5215, 103.4389, 0.04056),
    46: (-0.5201, 104.0946, 0.04081), 47: (-0.5186, 104.7444, 0.04105),
    48: (-0.5170, 105.3884, 0.04129), 49: (-0.5152, 106.0268, 0.04153),
    50: (-0.5134, 106.6596, 0.04176), 51: (-0.5114, 107.2870, 0.04198),
    52: (-0.5094, 107.9090, 0.04221), 53: (-0.5073, 108.5258, 0.04242),
    54: (-0.5052, 109.1375, 0.04264), 55: (-0.5030, 109.7441, 0.04285),
    56: (-0.5007, 110.3457, 0.04305), 57: (-0.4985, 110.9424, 0.04326),
    58: (-0.4962, 111.5343, 0.04345), 59: (-0.4939, 112.1214, 0.04365),
    60: (-0.4916, 112.7039, 0.04384),
}

# 女孩身高(cm) LMS（0-60月）
_HFA_GIRL: dict[int, tuple[float, float, float]] = {
    0: (-0.3833, 49.1477, 0.03790), 1: (0.1499, 53.6872, 0.03607),
    2: (0.0742, 57.0673, 0.03528), 3: (0.0311, 59.8029, 0.03501),
    4: (-0.0010, 62.0899, 0.03479), 5: (-0.0278, 64.0301, 0.03453),
    6: (-0.0510, 65.7311, 0.03431), 7: (-0.0714, 67.2873, 0.03413),
    8: (-0.0894, 68.7498, 0.03398), 9: (-0.1055, 70.1435, 0.03385),
    10: (-0.1200, 71.4818, 0.03374), 11: (-0.1329, 72.7710, 0.03365),
    12: (-0.1446, 74.0150, 0.03360), 13: (-0.1553, 75.2176, 0.03355),
    14: (-0.1649, 76.3817, 0.03352), 15: (-0.1737, 77.5099, 0.03351),
    16: (-0.1817, 78.6055, 0.03352), 17: (-0.1889, 79.6693, 0.03353),
    18: (-0.1953, 80.7020, 0.03356), 19: (-0.2013, 81.7036, 0.03361),
    20: (-0.2066, 82.6757, 0.03367), 21: (-0.2113, 83.6186, 0.03374),
    22: (-0.2155, 84.5323, 0.03381), 23: (-0.2192, 85.4190, 0.03390),
    24: (-0.2225, 86.2788, 0.03400), 25: (-0.2253, 87.1138, 0.03409),
    26: (-0.2279, 87.9234, 0.03419), 27: (-0.2300, 88.7096, 0.03430),
    28: (-0.2319, 89.4722, 0.03441), 29: (-0.2334, 90.2121, 0.03452),
    30: (-0.2347, 90.9296, 0.03463), 31: (-0.2358, 91.6254, 0.03474),
    32: (-0.2367, 92.2998, 0.03486), 33: (-0.2373, 92.9534, 0.03497),
    34: (-0.2378, 93.5869, 0.03509), 35: (-0.2381, 94.2009, 0.03520),
    36: (-0.2383, 94.7957, 0.03531), 37: (-0.2383, 95.3723, 0.03543),
    38: (-0.2382, 95.9311, 0.03554), 39: (-0.2380, 96.4727, 0.03565),
    40: (-0.2377, 96.9976, 0.03576), 41: (-0.2373, 97.5064, 0.03587),
    42: (-0.2368, 97.9997, 0.03598), 43: (-0.2363, 98.4778, 0.03608),
    44: (-0.2357, 98.9413, 0.03619), 45: (-0.2350, 99.3906, 0.03629),
    46: (-0.2343, 99.8261, 0.03639), 47: (-0.2336, 100.2483, 0.03649),
    48: (-0.2328, 100.6575, 0.03659), 49: (-0.2320, 101.0542, 0.03668),
    50: (-0.2312, 101.4387, 0.03678), 51: (-0.2304, 101.8113, 0.03687),
    52: (-0.2295, 102.1724, 0.03696), 53: (-0.2286, 102.5225, 0.03705),
    54: (-0.2277, 102.8619, 0.03714), 55: (-0.2268, 103.1909, 0.03723),
    56: (-0.2259, 103.5099, 0.03732), 57: (-0.2250, 103.8193, 0.03740),
    58: (-0.2241, 104.1195, 0.03749), 59: (-0.2232, 104.4107, 0.03757),
    60: (-0.2223, 104.6932, 0.03766),
}

# 男孩体重(kg) LMS（0-60月）
_WFA_BOY: dict[int, tuple[float, float, float]] = {
    0: (0.3487, 3.3464, 0.14602), 1: (0.2297, 4.4709, 0.13395),
    2: (0.1970, 5.5675, 0.12385), 3: (0.1738, 6.3762, 0.11727),
    4: (0.1553, 7.0023, 0.11316), 5: (0.1395, 7.5105, 0.11080),
    6: (0.1257, 7.9340, 0.10958), 7: (0.1134, 8.2975, 0.10914),
    8: (0.1022, 8.6151, 0.10885), 9: (0.0919, 8.9014, 0.10861),
    10: (0.0826, 9.1649, 0.10849), 11: (0.0739, 9.4122, 0.10838),
    12: (0.0659, 9.6479, 0.10836), 13: (0.0585, 9.8749, 0.10838),
    14: (0.0515, 10.0953, 0.10847), 15: (0.0450, 10.3108, 0.10860),
    16: (0.0388, 10.5228, 0.10882), 17: (0.0330, 10.7319, 0.10906),
    18: (0.0274, 10.9385, 0.10938), 19: (0.0220, 11.1430, 0.10973),
    20: (0.0168, 11.3462, 0.11012), 21: (0.0117, 11.5484, 0.11054),
    22: (0.0066, 11.7504, 0.11101), 23: (0.0017, 11.9526, 0.11150),
    24: (-0.0030, 12.1555, 0.11204), 25: (-0.0076, 12.3596, 0.11259),
    26: (-0.0121, 12.5652, 0.11318), 27: (-0.0165, 12.7727, 0.11380),
    28: (-0.0208, 12.9816, 0.11446), 29: (-0.0250, 13.1927, 0.11513),
    30: (-0.0291, 13.4053, 0.11584), 31: (-0.0331, 13.6196, 0.11657),
    32: (-0.0369, 13.8350, 0.11731), 33: (-0.0406, 14.0513, 0.11808),
    34: (-0.0442, 14.2676, 0.11887), 35: (-0.0477, 14.4840, 0.11968),
    36: (-0.0510, 14.6998, 0.12049), 37: (-0.0543, 14.9145, 0.12130),
    38: (-0.0574, 15.1278, 0.12210), 39: (-0.0603, 15.3393, 0.12291),
    40: (-0.0631, 15.5485, 0.12372), 41: (-0.0659, 15.7553, 0.12452),
    42: (-0.0684, 15.9594, 0.12531), 43: (-0.0708, 16.1606, 0.12609),
    44: (-0.0732, 16.3589, 0.12686), 45: (-0.0753, 16.5541, 0.12762),
    46: (-0.0774, 16.7462, 0.12837), 47: (-0.0793, 16.9352, 0.12910),
    48: (-0.0811, 17.1211, 0.12982), 49: (-0.0828, 17.3040, 0.13053),
    50: (-0.0844, 17.4839, 0.13122), 51: (-0.0859, 17.6609, 0.13190),
    52: (-0.0873, 17.8350, 0.13257), 53: (-0.0886, 18.0064, 0.13323),
    54: (-0.0898, 18.1753, 0.13387), 55: (-0.0909, 18.3416, 0.13450),
    56: (-0.0919, 18.5056, 0.13511), 57: (-0.0928, 18.6673, 0.13572),
    58: (-0.0937, 18.8269, 0.13631), 59: (-0.0945, 18.9845, 0.13688),
    60: (-0.0952, 19.1403, 0.13745),
}

# 女孩体重(kg) LMS（0-60月）
_WFA_GIRL: dict[int, tuple[float, float, float]] = {
    0: (0.3809, 3.2322, 0.14171), 1: (0.1714, 4.1873, 0.13724),
    2: (0.0967, 5.1282, 0.13000), 3: (0.0580, 5.8458, 0.12619),
    4: (0.0323, 6.4237, 0.12402), 5: (0.0130, 6.8985, 0.12274),
    6: (-0.0026, 7.2970, 0.12204), 7: (-0.0158, 7.6422, 0.12178),
    8: (-0.0272, 7.9487, 0.12181), 9: (-0.0371, 8.2254, 0.12199),
    10: (-0.0459, 8.4800, 0.12223), 11: (-0.0536, 8.7192, 0.12248),
    12: (-0.0605, 8.9481, 0.12268), 13: (-0.0666, 9.1699, 0.12288),
    14: (-0.0719, 9.3870, 0.12305), 15: (-0.0766, 9.6008, 0.12320),
    16: (-0.0807, 9.8124, 0.12333), 17: (-0.0843, 10.0226, 0.12345),
    18: (-0.0873, 10.2320, 0.12356), 19: (-0.0899, 10.4414, 0.12367),
    20: (-0.0920, 10.6510, 0.12378), 21: (-0.0936, 10.8612, 0.12390),
    22: (-0.0949, 11.0722, 0.12402), 23: (-0.0957, 11.2838, 0.12415),
    24: (-0.0962, 11.4957, 0.12429), 25: (-0.0963, 11.7071, 0.12442),
    26: (-0.0961, 11.9172, 0.12454), 27: (-0.0955, 12.1251, 0.12466),
    28: (-0.0945, 12.3299, 0.12478), 29: (-0.0933, 12.5307, 0.12490),
    30: (-0.0918, 12.7268, 0.12502), 31: (-0.0900, 12.9176, 0.12514),
    32: (-0.0880, 13.1026, 0.12525), 33: (-0.0857, 13.2813, 0.12537),
    34: (-0.0832, 13.4530, 0.12549), 35: (-0.0806, 13.6174, 0.12561),
    36: (-0.0778, 13.7741, 0.12573), 37: (-0.0749, 13.9228, 0.12585),
    38: (-0.0718, 14.0635, 0.12596), 39: (-0.0686, 14.1962, 0.12608),
    40: (-0.0653, 14.3209, 0.12620), 41: (-0.0619, 14.4379, 0.12631),
    42: (-0.0585, 14.5474, 0.12643), 43: (-0.0550, 14.6499, 0.12655),
    44: (-0.0514, 14.7455, 0.12667), 45: (-0.0478, 14.8348, 0.12678),
    46: (-0.0442, 14.9181, 0.12690), 47: (-0.0406, 14.9956, 0.12702),
    48: (-0.0370, 15.0677, 0.12713), 49: (-0.0334, 15.1348, 0.12725),
    50: (-0.0298, 15.1972, 0.12737), 51: (-0.0263, 15.2553, 0.12748),
    52: (-0.0228, 15.3095, 0.12760), 53: (-0.0193, 15.3601, 0.12772),
    54: (-0.0159, 15.4075, 0.12783), 55: (-0.0125, 15.4521, 0.12795),
    56: (-0.0092, 15.4941, 0.12807), 57: (-0.0059, 15.5338, 0.12818),
    58: (-0.0027, 15.5715, 0.12830), 59: (0.0005, 15.6073, 0.12841),
    60: (0.0037, 15.6415, 0.12852),
}


# ── LMS 百分位计算 ────────────────────────────────────────────────────

def _normal_cdf(z: float) -> float:
    """标准正态累积分布函数（Hart 近似，精度 ≈ 1e-7）"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


def _lms_zscore(value: float, L: float, M: float, S: float) -> float:
    """LMS Z-score"""
    if L == 0:
        return math.log(value / M) / S
    return ((value / M) ** L - 1) / (L * S)


def _zscore_to_percentile(z: float) -> float:
    """Z-score → 百分位（0-100）"""
    return round(_normal_cdf(z) * 100, 1)


def _category_from_percentile(p: float) -> GrowthCategory:
    if p < 1:
        return GrowthCategory.SEVERE_UNDERWEIGHT
    elif p < 3:
        return GrowthCategory.UNDERWEIGHT
    elif p < 15:
        return GrowthCategory.BELOW_AVERAGE
    elif p <= 85:
        return GrowthCategory.NORMAL
    elif p <= 97:
        return GrowthCategory.ABOVE_AVERAGE
    elif p <= 99:
        return GrowthCategory.OVERWEIGHT
    else:
        return GrowthCategory.OBESE


def _get_lms(table: dict, month: int) -> Optional[tuple[float, float, float]]:
    """取最近月龄的 LMS 参数（月龄超出范围取边界值）"""
    month = max(0, min(month, 60))
    return table.get(month)


def _compute_age_months(birth_date: date, measured_at: date) -> int:
    """精确月龄计算"""
    months = (measured_at.year - birth_date.year) * 12 + (measured_at.month - birth_date.month)
    if measured_at.day < birth_date.day:
        months -= 1
    return max(0, months)


# ── 百分位主入口 ──────────────────────────────────────────────────────

def compute_growth_percentiles(
    height_cm: Optional[float],
    weight_kg: Optional[float],
    age_months: int,
    is_male: bool,
) -> dict:
    """
    计算生长百分位/Z-score/等级。
    返回 dict，包含：
      height_percentile, height_zscore, height_category
      weight_percentile, weight_zscore, weight_category
      bmi, bmi_percentile, bmi_category
    缺失指标字段均为 None。
    """
    result: dict = {}
    sex = "boy" if is_male else "girl"
    hfa_table = _HFA_BOY if is_male else _HFA_GIRL
    wfa_table = _WFA_BOY if is_male else _WFA_GIRL

    # 身高百分位
    if height_cm is not None:
        lms = _get_lms(hfa_table, age_months)
        if lms:
            z = _lms_zscore(height_cm, *lms)
            p = _zscore_to_percentile(z)
            result["height_zscore"] = round(z, 2)
            result["height_percentile"] = p
            result["height_category"] = _category_from_percentile(p).value
        else:
            result["height_zscore"] = result["height_percentile"] = result["height_category"] = None
    else:
        result["height_zscore"] = result["height_percentile"] = result["height_category"] = None

    # 体重百分位
    if weight_kg is not None:
        lms = _get_lms(wfa_table, age_months)
        if lms:
            z = _lms_zscore(weight_kg, *lms)
            p = _zscore_to_percentile(z)
            result["weight_zscore"] = round(z, 2)
            result["weight_percentile"] = p
            result["weight_category"] = _category_from_percentile(p).value
        else:
            result["weight_zscore"] = result["weight_percentile"] = result["weight_category"] = None
    else:
        result["weight_zscore"] = result["weight_percentile"] = result["weight_category"] = None

    # BMI（月龄 ≥ 24 月才计算，0-23 月 BMI 意义有限）
    if height_cm and weight_kg and height_cm > 0:
        bmi = weight_kg / ((height_cm / 100) ** 2)
        result["bmi"] = round(bmi, 1)
        if age_months >= 24:
            # 简化：使用 weight percentile 作为 bmi_percentile 的近似（无单独 bfma 表时）
            result["bmi_percentile"] = result["weight_percentile"]
            if result["bmi_percentile"] is not None:
                result["bmi_category"] = _category_from_percentile(result["bmi_percentile"]).value
            else:
                result["bmi_category"] = None
        else:
            result["bmi_percentile"] = None
            result["bmi_category"] = None
    else:
        result["bmi"] = result["bmi_percentile"] = result["bmi_category"] = None

    return result


# ── 系统预设发育里程碑 ────────────────────────────────────────────────

PRESET_MILESTONES: list[dict] = [
    # 大运动
    {"type": MilestoneType.MOTOR, "title": "抬头（俯卧）", "start": 1, "end": 3},
    {"type": MilestoneType.MOTOR, "title": "翻身", "start": 3, "end": 6},
    {"type": MilestoneType.MOTOR, "title": "独立坐稳", "start": 6, "end": 9},
    {"type": MilestoneType.MOTOR, "title": "扶站/独站", "start": 9, "end": 12},
    {"type": MilestoneType.MOTOR, "title": "独立行走", "start": 12, "end": 15},
    {"type": MilestoneType.MOTOR, "title": "跑步（不太稳）", "start": 15, "end": 18},
    {"type": MilestoneType.MOTOR, "title": "单脚跳", "start": 36, "end": 48},
    # 精细动作
    {"type": MilestoneType.FINE_MOTOR, "title": "拇食指捏取小物", "start": 9, "end": 12},
    {"type": MilestoneType.FINE_MOTOR, "title": "用勺吃饭", "start": 18, "end": 24},
    {"type": MilestoneType.FINE_MOTOR, "title": "画竖线/圆", "start": 24, "end": 36},
    # 语言
    {"type": MilestoneType.LANGUAGE, "title": "笑出声", "start": 2, "end": 4},
    {"type": MilestoneType.LANGUAGE, "title": "喃喃发音", "start": 4, "end": 7},
    {"type": MilestoneType.LANGUAGE, "title": "「爸爸/妈妈」有意识叫人", "start": 10, "end": 14},
    {"type": MilestoneType.LANGUAGE, "title": "说 5–10 个词汇", "start": 18, "end": 24},
    {"type": MilestoneType.LANGUAGE, "title": "说 2–3 词的句子", "start": 24, "end": 30},
    {"type": MilestoneType.LANGUAGE, "title": "讲简单故事", "start": 36, "end": 48},
    # 认知
    {"type": MilestoneType.COGNITIVE, "title": "认出熟悉的人", "start": 3, "end": 6},
    {"type": MilestoneType.COGNITIVE, "title": "寻找被遮挡玩具（客体永恒）", "start": 8, "end": 12},
    {"type": MilestoneType.COGNITIVE, "title": "指认身体部位", "start": 18, "end": 24},
    {"type": MilestoneType.COGNITIVE, "title": "完成简单拼图", "start": 24, "end": 36},
    # 社会情感
    {"type": MilestoneType.SOCIAL, "title": "社交性微笑", "start": 2, "end": 4},
    {"type": MilestoneType.SOCIAL, "title": "分离焦虑", "start": 8, "end": 12},
    {"type": MilestoneType.SOCIAL, "title": "模仿大人动作", "start": 12, "end": 18},
    {"type": MilestoneType.SOCIAL, "title": "平行游戏（与他人一起玩）", "start": 24, "end": 36},
]


async def init_preset_milestones(member_id, db: AsyncSession) -> int:
    """为儿童成员插入系统预设里程碑（如已存在则跳过）"""
    existing = (await db.execute(
        select(DevelopmentMilestone.title).where(
            DevelopmentMilestone.member_id == member_id,
            DevelopmentMilestone.is_preset == True,  # noqa: E712
        )
    )).scalars().all()
    existing_titles = set(existing)

    count = 0
    for m in PRESET_MILESTONES:
        if m["title"] in existing_titles:
            continue
        record = DevelopmentMilestone(
            member_id=member_id,
            milestone_type=m["type"].value,
            title=m["title"],
            typical_age_start=m["start"],
            typical_age_end=m["end"],
            status=MilestoneStatus.IN_PROGRESS.value,
            is_preset=True,
        )
        db.add(record)
        count += 1
    if count:
        await db.flush()
    return count


# ── LLM 生长评估总结 ──────────────────────────────────────────────────

async def generate_growth_assessment(
    member: Member,
    record: GrowthRecord,
    db: AsyncSession,
) -> str:
    """调用 LLM 生成通俗生长评估建议；失败时静默降级为规则说明。"""
    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL or None,
        )

        today = date.today()
        age_m = record.age_months or 0
        age_y = age_m // 12
        age_mo = age_m % 12
        age_str = f"{age_y}岁{age_mo}个月" if age_y else f"{age_mo}个月"

        lines = []
        if record.height_cm:
            lines.append(f"身高：{record.height_cm} cm（百分位 {record.height_percentile}%，{record.height_category}）")
        if record.weight_kg:
            lines.append(f"体重：{record.weight_kg} kg（百分位 {record.weight_percentile}%，{record.weight_category}）")
        if record.bmi:
            lines.append(f"BMI：{record.bmi}（百分位 {record.bmi_percentile}%）")

        prompt = f"""你是儿科生长发育顾问，请根据以下儿童生长数据给出简洁实用的指导，中文回答，不超过 150 字。

儿童信息：{member.nickname}，{age_str}
生长数据（基于 WHO 标准）：
{chr(10).join(lines)}

请从以下方面评估：
1. 整体生长状况评价
2. 最需关注的指标及原因（如有）
3. 1-2 条具体建议（饮食/运动/就诊）"""

        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.5,
        )
        text = resp.choices[0].message.content.strip()
        return text + DISCLAIMER
    except Exception as exc:
        log.warning("LLM growth assessment failed, fallback to rule: %s", exc)
        return _rule_assessment(record)


def _rule_assessment(record: GrowthRecord) -> str:
    tips = []
    if record.height_category and record.height_category not in ("normal", "above_average"):
        if record.height_category in ("severe_underweight", "underweight", "below_average"):
            tips.append(f"身高偏低（P{record.height_percentile}%），建议关注营养摄入和睡眠质量，必要时咨询儿科医生。")
        else:
            tips.append(f"身高偏高（P{record.height_percentile}%），属于正常变异，定期监测即可。")

    if record.weight_category and record.weight_category not in ("normal",):
        if record.weight_category in ("overweight", "obese"):
            tips.append(f"体重偏高（P{record.weight_percentile}%），建议控制高热量食物摄入，增加户外活动。")
        elif record.weight_category in ("severe_underweight", "underweight"):
            tips.append(f"体重偏低（P{record.weight_percentile}%），建议增加营养密度高的食物，必要时就医评估。")

    if not tips:
        tips.append("生长发育在正常范围内，继续保持均衡饮食和规律运动。")

    return "\n".join(f"• {t}" for t in tips) + DISCLAIMER
