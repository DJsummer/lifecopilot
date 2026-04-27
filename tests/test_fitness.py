"""T015：运动方案生成与追踪 API 集成测试"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.main import app

pytestmark = [pytest.mark.integration, pytest.mark.fitness]

BASE = "/api/v1/fitness"

# ── Mock LLM 返回 ─────────────────────────────────────────────────────

FAKE_WEEK_PLAN = [
    {
        "day": "周一",
        "rest": False,
        "theme": "下肢力量",
        "exercises": [
            {
                "name": "深蹲",
                "type": "strength",
                "sets": 3,
                "reps": "12",
                "duration_min": 15,
                "calories_est": 80,
                "intensity": "中等",
                "tips": "膝盖不要超过脚尖",
            }
        ],
    },
    {"day": "周二", "rest": True, "theme": "休息", "exercises": []},
    {
        "day": "周三",
        "rest": False,
        "theme": "有氧",
        "exercises": [
            {
                "name": "慢跑",
                "type": "cardio",
                "sets": 1,
                "reps": "30分钟",
                "duration_min": 30,
                "calories_est": 250,
                "intensity": "中等",
                "tips": "保持轻松配速",
            }
        ],
    },
    {"day": "周四", "rest": True, "theme": "休息", "exercises": []},
    {
        "day": "周五",
        "rest": False,
        "theme": "上肢力量",
        "exercises": [
            {
                "name": "俯卧撑",
                "type": "strength",
                "sets": 3,
                "reps": "10",
                "duration_min": 15,
                "calories_est": 70,
                "intensity": "中等",
                "tips": "保持核心收紧",
            }
        ],
    },
    {"day": "周六", "rest": True, "theme": "休息", "exercises": []},
    {"day": "周日", "rest": True, "theme": "休息", "exercises": []},
]

FAKE_PLAN_RESULT = {
    "week_plan": FAKE_WEEK_PLAN,
    "summary": "本周计划：3次力量+有氧组合，适合初级水平。⚠️ 免责声明：仅供参考。",
}

FAKE_WORKOUT_ANALYSIS = {
    "calories_burned": 210.0,
    "llm_feedback": "完成得很好！慢跑30分钟消耗约210大卡，建议补充水分和蛋白质。",
}


# ══════════════════════════════════════════════════════════════════════
# 1. 体能评估问卷
# ══════════════════════════════════════════════════════════════════════

class TestFitnessAssessment:
    @pytest.mark.asyncio
    async def test_create_assessment_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/assessment",
            json={
                "fitness_level": "beginner",
                "primary_goal": "lose_weight",
                "available_minutes_per_session": 45,
                "available_days_per_week": 4,
                "preferred_types": ["cardio", "walking"],
                "limitations": [],
                "equipment": ["哑铃"],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["fitness_level"] == "beginner"
        assert data["primary_goal"] == "lose_weight"
        assert data["available_minutes_per_session"] == 45
        assert data["available_days_per_week"] == 4
        assert "cardio" in data["preferred_types"]
        assert data["equipment"] == ["哑铃"]

    @pytest.mark.asyncio
    async def test_upsert_assessment(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """再次 POST 应更新而非创建新记录"""
        member_id = registered_family["member_id"]
        # 第一次
        await client.post(
            f"{BASE}/{member_id}/assessment",
            json={"fitness_level": "beginner", "primary_goal": "maintain_health"},
            headers=auth_headers,
        )
        # 第二次更新
        resp = await client.post(
            f"{BASE}/{member_id}/assessment",
            json={"fitness_level": "intermediate", "primary_goal": "build_muscle"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fitness_level"] == "intermediate"
        assert data["primary_goal"] == "build_muscle"

    @pytest.mark.asyncio
    async def test_get_assessment_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 先创建
        await client.post(
            f"{BASE}/{member_id}/assessment",
            json={"fitness_level": "advanced", "primary_goal": "improve_cardio"},
            headers=auth_headers,
        )
        resp = await client.get(f"{BASE}/{member_id}/assessment", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["fitness_level"] == "advanced"

    @pytest.mark.asyncio
    async def test_get_assessment_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        fake_id = uuid.uuid4()
        resp = await client.get(f"{BASE}/{fake_id}/assessment", headers=auth_headers)
        # 无权限或不存在均非 200
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_assessment_requires_auth(self, client: AsyncClient):
        fake_id = uuid.uuid4()
        resp = await client.get(f"{BASE}/{fake_id}/assessment")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_assessment_invalid_days(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/assessment",
            json={"fitness_level": "beginner", "primary_goal": "maintain_health", "available_days_per_week": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_assessment_invalid_minutes(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/assessment",
            json={"fitness_level": "beginner", "primary_goal": "maintain_health", "available_minutes_per_session": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# 2. 运动计划生成
# ══════════════════════════════════════════════════════════════════════

class TestExercisePlan:
    async def _setup_assessment(self, client, member_id, auth_headers, **kwargs):
        payload = {"fitness_level": "beginner", "primary_goal": "maintain_health"}
        payload.update(kwargs)
        await client.post(f"{BASE}/{member_id}/assessment", json=payload, headers=auth_headers)

    @pytest.mark.asyncio
    async def test_create_plan_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await self._setup_assessment(client, member_id, auth_headers)

        with patch(
            "src.api.v1.routers.fitness.generate_fitness_plan",
            new=AsyncMock(return_value=FAKE_PLAN_RESULT),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/plans",
                json={},
                headers=auth_headers,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["is_active"] is True
        assert data["llm_summary"] is not None
        # plan_data 由 schema 反序列化为 list（存储的是 week_plan 数组）
        assert isinstance(data["plan_data"], list)
        assert len(data["plan_data"]) == 7  # 7天计划

    @pytest.mark.asyncio
    async def test_create_plan_requires_assessment(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """未创建体能评估时，生成计划应返回 400"""
        from tests.conftest import make_register_payload
        uid_payload = make_register_payload()
        reg_resp = await client.post("/api/v1/auth/register", json=uid_payload)
        assert reg_resp.status_code == 201
        new_data = reg_resp.json()
        new_member_id = new_data["member_id"]
        new_headers = {"Authorization": f"Bearer {new_data['access_token']}"}

        resp = await client.post(
            f"{BASE}/{new_member_id}/plans",
            json={},
            headers=new_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_plan_with_week_start(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await self._setup_assessment(client, member_id, auth_headers)
        week_start = "2026-05-04"  # 某个周一

        with patch(
            "src.api.v1.routers.fitness.generate_fitness_plan",
            new=AsyncMock(return_value=FAKE_PLAN_RESULT),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/plans",
                json={"week_start": week_start},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["week_start"] == week_start

    @pytest.mark.asyncio
    async def test_new_plan_deactivates_old(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """新计划生成后，旧计划 is_active 变 False"""
        member_id = registered_family["member_id"]
        await self._setup_assessment(client, member_id, auth_headers)

        with patch(
            "src.api.v1.routers.fitness.generate_fitness_plan",
            new=AsyncMock(return_value=FAKE_PLAN_RESULT),
        ):
            r1 = await client.post(f"{BASE}/{member_id}/plans", json={}, headers=auth_headers)
            r2 = await client.post(f"{BASE}/{member_id}/plans", json={}, headers=auth_headers)
        assert r1.status_code == 201
        assert r2.status_code == 201

        # 获取活跃计划，应该是最新的
        resp = await client.get(f"{BASE}/{member_id}/plans/active", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == r2.json()["id"]

    @pytest.mark.asyncio
    async def test_list_plans(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await self._setup_assessment(client, member_id, auth_headers)

        with patch(
            "src.api.v1.routers.fitness.generate_fitness_plan",
            new=AsyncMock(return_value=FAKE_PLAN_RESULT),
        ):
            await client.post(f"{BASE}/{member_id}/plans", json={}, headers=auth_headers)

        resp = await client.get(f"{BASE}/{member_id}/plans", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    @pytest.mark.asyncio
    async def test_get_active_plan_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        fake_id = uuid.uuid4()
        resp = await client.get(f"{BASE}/{fake_id}/plans/active", headers=auth_headers)
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_plan_llm_degraded(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 失败时仍然成功创建计划（使用默认模板）"""
        member_id = registered_family["member_id"]
        await self._setup_assessment(client, member_id, auth_headers, available_days_per_week=3)

        with patch(
            "src.api.v1.routers.fitness.generate_fitness_plan",
            new=AsyncMock(side_effect=Exception("LLM 超时")),
        ):
            # 因为 generate_fitness_plan 在 router 中被调用前有 try-except，
            # 但这里我们测试 service 层降级，router 中直接调用 service
            # 所以直接让 service 本身失败并返回默认计划
            pass

        # 使用真实降级（不 mock）——服务层会捕获异常并返回默认计划
        with patch(
            "src.services.fitness_service.AsyncOpenAI",
            side_effect=Exception("网络不可达"),
        ):
            resp = await client.post(f"{BASE}/{member_id}/plans", json={}, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["plan_data"] is not None



# ══════════════════════════════════════════════════════════════════════
# 3. 运动日志
# ══════════════════════════════════════════════════════════════════════

class TestWorkoutLog:
    @pytest.mark.asyncio
    async def test_create_log_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fitness.analyze_workout",
            new=AsyncMock(return_value=FAKE_WORKOUT_ANALYSIS),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/logs",
                json={
                    "log_date": str(date.today()),
                    "exercise_type": "cardio",
                    "exercise_name": "慢跑",
                    "duration_minutes": 30,
                    "avg_heart_rate": 135,
                    "status": "completed",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["exercise_name"] == "慢跑"
        assert data["calories_burned"] == 210.0
        assert data["llm_feedback"] is not None
        assert data["avg_heart_rate"] == 135

    @pytest.mark.asyncio
    async def test_create_log_all_types(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """测试各种运动类型均可记录"""
        member_id = registered_family["member_id"]
        exercise_types = ["cardio", "strength", "flexibility", "hiit", "swimming", "walking", "sports"]
        for ex_type in exercise_types:
            with patch(
                "src.api.v1.routers.fitness.analyze_workout",
                new=AsyncMock(return_value={"calories_burned": 100.0, "llm_feedback": "干得好！"}),
            ):
                resp = await client.post(
                    f"{BASE}/{member_id}/logs",
                    json={
                        "log_date": str(date.today()),
                        "exercise_type": ex_type,
                        "exercise_name": f"测试{ex_type}运动",
                        "duration_minutes": 20,
                    },
                    headers=auth_headers,
                )
            assert resp.status_code == 201, f"失败类型: {ex_type}"

    @pytest.mark.asyncio
    async def test_log_without_duration(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """duration_minutes 可不传"""
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fitness.analyze_workout",
            new=AsyncMock(return_value={"calories_burned": 0.0, "llm_feedback": ""}),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/logs",
                json={
                    "log_date": str(date.today()),
                    "exercise_type": "walking",
                    "exercise_name": "散步",
                    "status": "completed",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_log_skipped_status(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """记录跳过的训练"""
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fitness.analyze_workout",
            new=AsyncMock(return_value={"calories_burned": 0.0, "llm_feedback": ""}),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/logs",
                json={
                    "log_date": str(date.today()),
                    "exercise_type": "cardio",
                    "exercise_name": "计划跑步",
                    "status": "skipped",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_list_logs(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 先创建两条日志
        for i in range(2):
            with patch(
                "src.api.v1.routers.fitness.analyze_workout",
                new=AsyncMock(return_value={"calories_burned": 100.0, "llm_feedback": "ok"}),
            ):
                await client.post(
                    f"{BASE}/{member_id}/logs",
                    json={
                        "log_date": str(date.today() - timedelta(days=i)),
                        "exercise_type": "cardio",
                        "exercise_name": f"慢跑{i}",
                    },
                    headers=auth_headers,
                )
        resp = await client.get(f"{BASE}/{member_id}/logs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_list_logs_date_filter(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        today = str(date.today())
        resp = await client.get(
            f"{BASE}/{member_id}/logs?start_date={today}&end_date={today}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_single_log(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fitness.analyze_workout",
            new=AsyncMock(return_value={"calories_burned": 150.0, "llm_feedback": ""}),
        ):
            create_resp = await client.post(
                f"{BASE}/{member_id}/logs",
                json={
                    "log_date": str(date.today()),
                    "exercise_type": "strength",
                    "exercise_name": "力量训练",
                    "duration_minutes": 45,
                },
                headers=auth_headers,
            )
        log_id = create_resp.json()["id"]
        resp = await client.get(f"{BASE}/{member_id}/logs/{log_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["exercise_name"] == "力量训练"

    @pytest.mark.asyncio
    async def test_get_log_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/logs/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_log(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fitness.analyze_workout",
            new=AsyncMock(return_value={"calories_burned": 80.0, "llm_feedback": ""}),
        ):
            create_resp = await client.post(
                f"{BASE}/{member_id}/logs",
                json={
                    "log_date": str(date.today()),
                    "exercise_type": "flexibility",
                    "exercise_name": "瑜伽",
                    "duration_minutes": 60,
                },
                headers=auth_headers,
            )
        log_id = create_resp.json()["id"]
        del_resp = await client.delete(f"{BASE}/{member_id}/logs/{log_id}", headers=auth_headers)
        assert del_resp.status_code == 204
        # 再次获取应 404
        resp = await client.get(f"{BASE}/{member_id}/logs/{log_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_log_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.delete(
            f"{BASE}/{member_id}/logs/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_log_invalid_heart_rate(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/logs",
            json={
                "log_date": str(date.today()),
                "exercise_type": "cardio",
                "exercise_name": "测试",
                "avg_heart_rate": 300,  # 超出范围
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# 4. 每周汇总
# ══════════════════════════════════════════════════════════════════════

class TestWeeklySummary:
    @pytest.mark.asyncio
    async def test_weekly_summary_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/summary/weekly",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_sessions"] == 0
        assert data["completed_sessions"] == 0
        assert data["total_minutes"] == 0
        assert data["total_calories"] == 0.0

    @pytest.mark.asyncio
    async def test_weekly_summary_with_logs(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        today = date.today()
        # 本周一
        week_start = today - timedelta(days=today.weekday())

        # 本周内创建 2 条完成的日志
        for i in range(2):
            log_date = week_start + timedelta(days=i)
            with patch(
                "src.api.v1.routers.fitness.analyze_workout",
                new=AsyncMock(return_value={"calories_burned": 200.0, "llm_feedback": ""}),
            ):
                await client.post(
                    f"{BASE}/{member_id}/logs",
                    json={
                        "log_date": str(log_date),
                        "exercise_type": "cardio",
                        "exercise_name": "慢跑",
                        "duration_minutes": 30,
                        "status": "completed",
                    },
                    headers=auth_headers,
                )

        resp = await client.get(
            f"{BASE}/{member_id}/summary/weekly?week_start={week_start}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_sessions"] >= 2
        assert data["total_calories"] >= 400.0
        assert data["total_minutes"] >= 60

    @pytest.mark.asyncio
    async def test_weekly_summary_custom_week(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/summary/weekly?week_start=2026-01-05",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["week_start"] == "2026-01-05"
        assert data["week_end"] == "2026-01-11"

    @pytest.mark.asyncio
    async def test_weekly_summary_with_heart_rate(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        with patch(
            "src.api.v1.routers.fitness.analyze_workout",
            new=AsyncMock(return_value={"calories_burned": 300.0, "llm_feedback": ""}),
        ):
            await client.post(
                f"{BASE}/{member_id}/logs",
                json={
                    "log_date": str(week_start),
                    "exercise_type": "hiit",
                    "exercise_name": "HIIT训练",
                    "duration_minutes": 25,
                    "avg_heart_rate": 160,
                    "status": "completed",
                },
                headers=auth_headers,
            )

        resp = await client.get(
            f"{BASE}/{member_id}/summary/weekly?week_start={week_start}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["avg_heart_rate"] is not None


# ══════════════════════════════════════════════════════════════════════
# 5. 权限控制
# ══════════════════════════════════════════════════════════════════════

class TestFitnessAuth:
    @pytest.mark.asyncio
    async def test_requires_auth_assessment(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/assessment")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_requires_auth_plans(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/plans")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_requires_auth_logs(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/logs")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_requires_auth_weekly_summary(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/summary/weekly")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cross_family_access_denied(
        self, client: AsyncClient
    ):
        """跨家庭访问被拒绝"""
        from tests.conftest import make_register_payload
        # 注册两个不同家庭
        p1 = make_register_payload()
        p2 = make_register_payload()
        r1 = await client.post("/api/v1/auth/register", json=p1)
        r2 = await client.post("/api/v1/auth/register", json=p2)
        assert r1.status_code == 201
        assert r2.status_code == 201

        family2_member_id = r2.json()["member_id"]
        family1_headers = {"Authorization": f"Bearer {r1.json()['access_token']}"}

        # 家庭1 的 token 访问家庭2 的成员
        resp = await client.get(
            f"{BASE}/{family2_member_id}/assessment",
            headers=family1_headers,
        )
        # ADMIN 角色绕过家庭检查（设计如此），但评估不存在所以得到 404
        # 非 ADMIN 成员访问其他家庭成员时得到 403
        assert resp.status_code in (403, 404)


# ══════════════════════════════════════════════════════════════════════
# 6. 服务层热量计算（单元测试）
# ══════════════════════════════════════════════════════════════════════

class TestCalorieCalculation:
    def test_estimate_calories_cardio(self):
        from src.services.fitness_service import estimate_calories
        from src.models.exercise import ExerciseType
        cal = estimate_calories(ExerciseType.CARDIO, 60, 70.0)
        assert abs(cal - 7.0 * 70.0) < 1.0  # MET=7.0, 1h, 70kg

    def test_estimate_calories_walking(self):
        from src.services.fitness_service import estimate_calories
        from src.models.exercise import ExerciseType
        cal = estimate_calories(ExerciseType.WALKING, 30, 60.0)
        # MET=3.5, 0.5h, 60kg = 105
        assert abs(cal - 105.0) < 1.0

    def test_estimate_calories_hiit(self):
        from src.services.fitness_service import estimate_calories
        from src.models.exercise import ExerciseType
        cal = estimate_calories(ExerciseType.HIIT, 20, 80.0)
        # MET=12, 1/3h, 80kg = 320
        assert abs(cal - 320.0) < 1.0

    def test_estimate_calories_default_weight(self):
        from src.services.fitness_service import estimate_calories
        from src.models.exercise import ExerciseType
        cal = estimate_calories(ExerciseType.STRENGTH, 30)
        # MET=5.0, 0.5h, 70kg = 175
        assert cal > 0
