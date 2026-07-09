import unittest
from datetime import datetime, timedelta

from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.api import api_router
from app.api.v1.routers import notifications
from app.db.base import Base
from app.models.defect import Defect
from app.models.project import Project
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.test_plan import TestPlanRun
from app.models.user import User


class NotificationsContractTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.engine = engine
        self.db = sessionmaker(bind=engine)()

        self.owner = User(
            username="当前用户",
            account="owner",
            password_hash="hash",
            phone="10000000000",
            email="owner@example.com",
        )
        self.db.add(self.owner)
        self.db.flush()

        self.project = Project(name="通知项目", created_by_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()

        self.scenario = TestScenario(
            project_id=self.project.id,
            environment_id=1,
            name="企业信息全链路回归",
            tags=[],
            created_by_id=self.owner.id,
            updated_by_id=self.owner.id,
        )
        self.db.add(self.scenario)
        self.db.flush()

        now = datetime(2026, 7, 8, 23, 0, 0)
        self.db.add_all([
            Defect(
                project_id=self.project.id,
                title="鉴权变量失效",
                bug_type="功能缺陷",
                urgency="高",
                status="open",
                content_html="<p>token expired</p>",
                reporter_id=self.owner.id,
                updated_at=now,
            ),
            TestScenarioRun(
                scenario_id=self.scenario.id,
                project_id=self.project.id,
                environment_id=1,
                status="failed",
                trigger_type="manual",
                scenario_snapshot={"name": self.scenario.name},
                variables_snapshot={},
                step_results=[],
                triggered_by_id=self.owner.id,
                started_at=now - timedelta(minutes=5),
                finished_at=now - timedelta(minutes=3),
                duration_ms=120000,
            ),
            TestPlanRun(
                plan_id=None,
                project_id=self.project.id,
                plan_name="企业回归计划",
                plan_version=1,
                environment_id=1,
                environment_name="test",
                status="passed",
                trigger="manual",
                plan_snapshot={},
                target_results=[],
                target_count=1,
                passed_count=1,
                failed_count=0,
                operator_id=self.owner.id,
                started_at=now - timedelta(minutes=20),
                finished_at=now - timedelta(minutes=18),
                duration_ms=120000,
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_list_notifications_returns_frontend_array_shape(self):
        response = notifications.list_notifications(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        data = response["data"]
        self.assertGreaterEqual(len(data), 3)
        first = data[0]
        self.assertIn("notification_id", first)
        self.assertNotIn("id", first)
        self.assertIn("title", first)
        self.assertIn("message", first)
        self.assertIn(first["severity"], {"info", "success", "warning", "danger"})
        self.assertIn(first["type"], {"alert", "run", "approval", "system"})
        self.assertIn("unread", first)
        self.assertIn("occurred_at", first)

        global_response = notifications.list_notifications(db=self.db, current_user=self.owner)
        self.assertEqual(global_response["code"], 0)
        self.assertGreaterEqual(len(global_response["data"]), 3)

    def test_notifications_router_is_registered_under_api_v1(self):
        registered = {(route.path, ",".join(sorted(route.methods))) for route in api_router.routes}

        self.assertIn(("/notifications", "GET"), registered)
        self.assertIn(("/notifications/{notification_id}/read", "POST"), registered)
        self.assertIn(("/notifications/read-all", "POST"), registered)

    def test_list_notifications_batches_read_state_lookup(self):
        now = datetime(2026, 7, 8, 23, 30, 0)
        self.db.add_all([
            Defect(
                project_id=self.project.id,
                title=f"批量缺陷 {index}",
                bug_type="功能缺陷",
                urgency="中",
                status="open",
                content_html="<p>batch</p>",
                reporter_id=self.owner.id,
                updated_at=now - timedelta(minutes=index),
            )
            for index in range(12)
        ])
        self.db.commit()

        statements: list[str] = []

        def capture_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        sqlalchemy_event.listen(self.engine, "before_cursor_execute", capture_sql)
        try:
            response = notifications.list_notifications(
                project_id=self.project.id,
                db=self.db,
                current_user=self.owner,
            )
        finally:
            sqlalchemy_event.remove(self.engine, "before_cursor_execute", capture_sql)

        self.assertEqual(response["code"], 0)
        self.assertGreaterEqual(len(response["data"]), 10)
        read_state_queries = [
            statement
            for statement in statements
            if "notification_read_states" in statement
            and statement.lstrip().startswith("select")
        ]
        list_selects = [
            statement
            for statement in statements
            if statement.lstrip().startswith("select")
        ]
        self.assertLessEqual(
            len(read_state_queries),
            1,
            "notification list must batch read-state lookup instead of querying per item",
        )
        heavy_columns = {
            "content_html",
            "scenario_snapshot",
            "variables_snapshot",
            "step_results",
            "plan_snapshot",
            "target_results",
        }
        for statement in list_selects:
            selected_columns = statement.split(" from ", 1)[0]
            self.assertFalse(
                any(column in selected_columns for column in heavy_columns),
                "notification list must project lightweight columns only",
            )

    def test_filters_and_mark_read_match_frontend_calls(self):
        unread = notifications.list_notifications(
            project_id=self.project.id,
            unread_only=True,
            db=self.db,
            current_user=self.owner,
        )["data"]
        self.assertTrue(unread)

        notification_id = unread[0]["notification_id"]
        mark_response = notifications.mark_notification_read(
            notification_id=notification_id,
            db=self.db,
            current_user=self.owner,
        )
        self.assertEqual(mark_response["code"], 0)
        self.assertEqual(mark_response["message"], "ok")
        self.assertEqual(mark_response["data"]["updated"], 1)

        unread_after_mark = notifications.list_notifications(
            project_id=self.project.id,
            unread_only=True,
            db=self.db,
            current_user=self.owner,
        )["data"]
        self.assertNotIn(notification_id, {item["notification_id"] for item in unread_after_mark})

        mark_all_response = notifications.mark_all_notifications_read(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )
        self.assertEqual(mark_all_response["code"], 0)
        self.assertEqual(mark_all_response["message"], "ok")
        self.assertIn("updated", mark_all_response["data"])
        self.assertEqual(
            notifications.list_notifications(
                project_id=self.project.id,
                unread_only=True,
                db=self.db,
                current_user=self.owner,
            )["data"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
