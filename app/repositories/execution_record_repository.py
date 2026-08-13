from datetime import datetime
from typing import Any

from sqlalchemy import String, cast, func, literal, select, union_all
from sqlalchemy.orm import Session, selectinload

from app.models.scenario import TestScenario, TestScenarioRun, TestScenarioRunEvent
from app.models.desktop_device import DesktopDevice
from app.models.test_case import TestCase, TestCaseExecution
from app.models.ui_execution import UiExecution
from app.models.execution_diagnostic import ExecutionPayloadArtifact
from app.models.ui_test_case import UiTestCase
from app.models.visual_flow import VisualFlow, VisualFlowExecution, VisualFlowNodeExecution
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseExecution


class ExecutionRecordRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _http_select():
        return select(
            literal("http").label("execution_type"),
            TestCaseExecution.id.label("execution_id"),
            TestCaseExecution.project_id.label("project_id"),
            TestCaseExecution.test_case_id.label("resource_id"),
            TestCase.name.label("resource_name"),
            TestCaseExecution.environment_id.label("environment_id"),
            TestCaseExecution.scenario_run_id.label("scenario_run_id"),
            TestCaseExecution.status.label("status"),
            literal("scenario").label("scenario_trigger"),
            TestCaseExecution.executed_by_id.label("trigger_user_id"),
            TestCaseExecution.duration_ms.label("duration_ms"),
            TestCaseExecution.error_message.label("error_message"),
            cast(None, String(128)).label("dataset_id"),
            cast(None, String(128)).label("dataset_name"),
            cast(None, String(128)).label("record_id"),
            cast(None, String(128)).label("record_name"),
            TestCaseExecution.created_at.label("started_at"),
            cast(None, TestCaseExecution.created_at.type).label("finished_at"),
            TestCaseExecution.created_at.label("created_at"),
            cast(None, String(64)).label("worker_id"),
        ).select_from(TestCaseExecution).outerjoin(
            TestCase, TestCase.id == TestCaseExecution.test_case_id
        )

    @staticmethod
    def _websocket_select():
        return select(
            literal("websocket").label("execution_type"),
            WebSocketTestCaseExecution.id.label("execution_id"),
            WebSocketTestCaseExecution.project_id.label("project_id"),
            WebSocketTestCaseExecution.websocket_test_case_id.label("resource_id"),
            WebSocketTestCase.name.label("resource_name"),
            WebSocketTestCaseExecution.environment_id.label("environment_id"),
            WebSocketTestCaseExecution.scenario_run_id.label("scenario_run_id"),
            WebSocketTestCaseExecution.status.label("status"),
            literal("scenario").label("scenario_trigger"),
            WebSocketTestCaseExecution.executed_by_id.label("trigger_user_id"),
            WebSocketTestCaseExecution.duration_ms.label("duration_ms"),
            WebSocketTestCaseExecution.error_message.label("error_message"),
            cast(None, String(128)).label("dataset_id"),
            cast(None, String(128)).label("dataset_name"),
            cast(None, String(128)).label("record_id"),
            cast(None, String(128)).label("record_name"),
            WebSocketTestCaseExecution.created_at.label("started_at"),
            cast(None, WebSocketTestCaseExecution.created_at.type).label("finished_at"),
            WebSocketTestCaseExecution.created_at.label("created_at"),
            cast(None, String(64)).label("worker_id"),
        ).select_from(WebSocketTestCaseExecution).outerjoin(
            WebSocketTestCase,
            WebSocketTestCase.id == WebSocketTestCaseExecution.websocket_test_case_id,
        )

    @staticmethod
    def _scenario_select():
        return select(
            literal("scenario").label("execution_type"),
            TestScenarioRun.id.label("execution_id"),
            TestScenarioRun.project_id.label("project_id"),
            TestScenarioRun.scenario_id.label("resource_id"),
            TestScenario.name.label("resource_name"),
            TestScenarioRun.environment_id.label("environment_id"),
            cast(None, TestScenarioRun.id.type).label("scenario_run_id"),
            TestScenarioRun.status.label("status"),
            TestScenarioRun.trigger_type.label("scenario_trigger"),
            TestScenarioRun.triggered_by_id.label("trigger_user_id"),
            TestScenarioRun.duration_ms.label("duration_ms"),
            cast(None, String).label("error_message"),
            TestScenarioRun.dataset_id.label("dataset_id"),
            TestScenarioRun.dataset_name.label("dataset_name"),
            TestScenarioRun.record_id.label("record_id"),
            TestScenarioRun.record_name.label("record_name"),
            TestScenarioRun.started_at.label("started_at"),
            TestScenarioRun.finished_at.label("finished_at"),
            TestScenarioRun.created_at.label("created_at"),
            cast(None, String(64)).label("worker_id"),
        ).select_from(TestScenarioRun).outerjoin(
            TestScenario, TestScenario.id == TestScenarioRun.scenario_id
        )

    @staticmethod
    def _flow_select():
        return select(
            literal("flow").label("execution_type"),
            VisualFlowExecution.id.label("execution_id"),
            VisualFlowExecution.project_id.label("project_id"),
            VisualFlowExecution.flow_id.label("resource_id"),
            VisualFlow.name.label("resource_name"),
            VisualFlowExecution.environment_id.label("environment_id"),
            cast(None, VisualFlowExecution.id.type).label("scenario_run_id"),
            VisualFlowExecution.status.label("status"),
            VisualFlowExecution.trigger_type.label("scenario_trigger"),
            VisualFlowExecution.trigger_user_id.label("trigger_user_id"),
            cast(None, VisualFlowExecution.id.type).label("duration_ms"),
            cast(None, String).label("error_message"),
            cast(None, String(128)).label("dataset_id"),
            cast(None, String(128)).label("dataset_name"),
            cast(None, String(128)).label("record_id"),
            cast(None, String(128)).label("record_name"),
            VisualFlowExecution.started_at.label("started_at"),
            VisualFlowExecution.finished_at.label("finished_at"),
            VisualFlowExecution.created_at.label("created_at"),
            cast(None, String(64)).label("worker_id"),
        ).select_from(VisualFlowExecution).outerjoin(
            VisualFlow, VisualFlow.id == VisualFlowExecution.flow_id
        )

    @staticmethod
    def _ui_select():
        return select(
            literal("ui").label("execution_type"),
            UiExecution.id.label("execution_id"),
            UiExecution.project_id.label("project_id"),
            UiExecution.ui_test_case_id.label("resource_id"),
            UiTestCase.name.label("resource_name"),
            UiExecution.environment_id.label("environment_id"),
            cast(None, UiExecution.id.type).label("scenario_run_id"),
            UiExecution.status.label("status"),
            UiExecution.trigger_type.label("scenario_trigger"),
            UiExecution.trigger_user_id.label("trigger_user_id"),
            UiExecution.duration_ms.label("duration_ms"),
            UiExecution.error_message.label("error_message"),
            cast(None, String(128)).label("dataset_id"),
            cast(None, String(128)).label("dataset_name"),
            cast(None, String(128)).label("record_id"),
            cast(None, String(128)).label("record_name"),
            UiExecution.created_at.label("started_at"),
            UiExecution.finished_at.label("finished_at"),
            UiExecution.created_at.label("created_at"),
            DesktopDevice.public_id.label("worker_id"),
        ).select_from(UiExecution).outerjoin(
            UiTestCase, UiTestCase.id == UiExecution.ui_test_case_id
        ).outerjoin(
            DesktopDevice, DesktopDevice.id == UiExecution.assigned_device_id
        )

    def list_records(
        self,
        *,
        project_id: int,
        execution_type: str | None,
        status: str | None,
        environment_id: int | None,
        trigger_user_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        records = union_all(
            self._http_select(),
            self._websocket_select(),
            self._scenario_select(),
            self._flow_select(),
            self._ui_select(),
        ).subquery("execution_records")

        filters = [records.c.project_id == project_id]
        if execution_type is not None:
            filters.append(records.c.execution_type == execution_type)
        if status is not None:
            public_statuses = {
                "running": ("running", "queued", "pending", "claimed", "launching"),
                "paused": ("paused", "waiting_user"),
                "passed": ("passed", "success", "completed", "assisted"),
                "failed": ("failed", "error", "timeout", "lost"),
            }
            filters.append(
                records.c.status.in_(public_statuses[status])
                if status in public_statuses
                else records.c.status == status
            )
        if environment_id is not None:
            filters.append(records.c.environment_id == environment_id)
        if trigger_user_id is not None:
            filters.append(records.c.trigger_user_id == trigger_user_id)
        if started_from is not None:
            filters.append(records.c.started_at >= started_from)
        if started_to is not None:
            filters.append(records.c.started_at <= started_to)
        if keyword:
            filters.append(records.c.resource_name.ilike(f"%{keyword.strip()}%"))

        total = self.db.scalar(
            select(func.count()).select_from(records).where(*filters)
        ) or 0
        rows = self.db.execute(
            select(records)
            .where(*filters)
            .order_by(records.c.started_at.desc(), records.c.execution_type, records.c.execution_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).mappings().all()
        return [dict(row) for row in rows], int(total)

    def get_http(self, *, project_id: int, execution_id: int):
        return self.db.execute(
            select(TestCaseExecution, TestCase.name)
            .outerjoin(TestCase, TestCase.id == TestCaseExecution.test_case_id)
            .where(
                TestCaseExecution.project_id == project_id,
                TestCaseExecution.id == execution_id,
            )
        ).one_or_none()

    def get_websocket(self, *, project_id: int, execution_id: int):
        return self.db.execute(
            select(WebSocketTestCaseExecution, WebSocketTestCase.name)
            .outerjoin(
                WebSocketTestCase,
                WebSocketTestCase.id == WebSocketTestCaseExecution.websocket_test_case_id,
            )
            .where(
                WebSocketTestCaseExecution.project_id == project_id,
                WebSocketTestCaseExecution.id == execution_id,
            )
        ).one_or_none()

    def get_scenario(self, *, project_id: int, execution_id: int):
        return self.db.execute(
            select(TestScenarioRun, TestScenario.name)
            .outerjoin(TestScenario, TestScenario.id == TestScenarioRun.scenario_id)
            .where(
                TestScenarioRun.project_id == project_id,
                TestScenarioRun.id == execution_id,
            )
        ).one_or_none()

    def list_scenario_events(self, execution_id: int) -> list[TestScenarioRunEvent]:
        return list(self.db.scalars(
            select(TestScenarioRunEvent)
            .where(TestScenarioRunEvent.run_id == execution_id)
            .order_by(TestScenarioRunEvent.sequence)
        ).all())

    def get_flow(self, *, project_id: int, execution_id: int):
        return self.db.execute(
            select(VisualFlowExecution, VisualFlow.name)
            .outerjoin(VisualFlow, VisualFlow.id == VisualFlowExecution.flow_id)
            .where(
                VisualFlowExecution.project_id == project_id,
                VisualFlowExecution.id == execution_id,
            )
        ).one_or_none()

    def get_ui(self, *, project_id: int, execution_id: int):
        return self.db.execute(
            select(UiExecution, UiTestCase.name)
            .options(
                selectinload(UiExecution.step_executions),
                selectinload(UiExecution.runtime_patches),
                selectinload(UiExecution.commands),
            )
            .outerjoin(UiTestCase, UiTestCase.id == UiExecution.ui_test_case_id)
            .where(
                UiExecution.project_id == project_id,
                UiExecution.id == execution_id,
            )
        ).one_or_none()

    def list_ui_artifacts(
        self,
        *,
        project_id: int,
        execution_id: int,
    ) -> list[ExecutionPayloadArtifact]:
        return list(
            self.db.scalars(
                select(ExecutionPayloadArtifact)
                .where(
                    ExecutionPayloadArtifact.project_id == project_id,
                    ExecutionPayloadArtifact.execution_type == "ui",
                    ExecutionPayloadArtifact.execution_id == execution_id,
                )
                .order_by(ExecutionPayloadArtifact.created_at, ExecutionPayloadArtifact.id)
            ).all()
        )

    def list_flow_nodes(self, execution_id: int) -> list[VisualFlowNodeExecution]:
        return list(self.db.scalars(
            select(VisualFlowNodeExecution)
            .where(VisualFlowNodeExecution.execution_id == execution_id)
            .order_by(VisualFlowNodeExecution.id)
        ).all())
