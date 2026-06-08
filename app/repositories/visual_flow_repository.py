from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.models.test_case import TestCase
from app.models.visual_flow import VisualFlow, VisualFlowExecution, VisualFlowNodeExecution, VisualFlowVersion
from app.models.websocket_test_case import WebSocketTestCase


class VisualFlowRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_project(self, project_id: int) -> list[VisualFlow]:
        statement = (
            select(VisualFlow)
            .where(VisualFlow.project_id == project_id, VisualFlow.status != "archived")
            .order_by(VisualFlow.updated_at.desc(), VisualFlow.id.desc())
        )
        return list(self.db.scalars(statement).all())

    def get_flow(self, *, project_id: int, flow_id: int) -> VisualFlow | None:
        return self.db.scalar(
            select(VisualFlow).where(
                VisualFlow.id == flow_id,
                VisualFlow.project_id == project_id,
                VisualFlow.status != "archived",
            )
        )

    def get_version(self, *, flow_id: int, version: int) -> VisualFlowVersion | None:
        return self.db.scalar(
            select(VisualFlowVersion).where(
                VisualFlowVersion.flow_id == flow_id,
                VisualFlowVersion.version == version,
            )
        )

    def create_flow(
        self,
        *,
        project_id: int,
        name: str,
        description: str | None,
        definition: dict,
        definition_hash: str,
        user_id: int,
    ) -> tuple[VisualFlow, VisualFlowVersion]:
        flow = VisualFlow(
            project_id=project_id,
            name=name,
            description=description,
            current_version=1,
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        self.db.add(flow)
        self.db.flush()
        version = VisualFlowVersion(
            flow_id=flow.id,
            version=1,
            definition=definition,
            definition_hash=definition_hash,
            created_by_id=user_id,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(flow)
        self.db.refresh(version)
        return flow, version

    def update_flow(
        self,
        *,
        flow: VisualFlow,
        expected_version: int,
        name: str,
        description: str | None,
        definition: dict,
        definition_hash: str,
        user_id: int,
    ) -> VisualFlowVersion | None:
        next_version = expected_version + 1
        result = self.db.execute(
            update(VisualFlow)
            .where(VisualFlow.id == flow.id, VisualFlow.current_version == expected_version)
            .values(
                current_version=next_version,
                name=name,
                description=description,
                updated_by_id=user_id,
                updated_at=datetime.utcnow(),
            )
        )
        if result.rowcount != 1:
            self.db.rollback()
            return None
        version = VisualFlowVersion(
            flow_id=flow.id,
            version=next_version,
            definition=definition,
            definition_hash=definition_hash,
            created_by_id=user_id,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(flow)
        self.db.refresh(version)
        return version

    def get_environment(self, *, project_id: int, environment_id: int) -> ProjectEnvironment | None:
        return self.db.scalar(
            select(ProjectEnvironment).where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )

    def get_environment_variables(self, *, environment_id: int) -> dict[str, str]:
        statement = select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.environment_id == environment_id
        )
        return {item.name: item.value for item in self.db.scalars(statement).all()}

    def get_http_case(self, *, project_id: int, case_id: int) -> TestCase | None:
        return self.db.scalar(select(TestCase).where(TestCase.id == case_id, TestCase.project_id == project_id))

    def get_websocket_case(self, *, project_id: int, case_id: int) -> WebSocketTestCase | None:
        return self.db.scalar(
            select(WebSocketTestCase).where(
                WebSocketTestCase.id == case_id,
                WebSocketTestCase.project_id == project_id,
            )
        )

    def get_execution_by_idempotency_key(
        self, *, project_id: int, idempotency_key: str
    ) -> VisualFlowExecution | None:
        return self.db.scalar(
            select(VisualFlowExecution).where(
                VisualFlowExecution.project_id == project_id,
                VisualFlowExecution.idempotency_key == idempotency_key,
            )
        )

    def create_execution(
        self,
        *,
        flow_id: int | None,
        flow_version_id: int | None,
        project_id: int,
        environment_id: int | None,
        user_id: int,
        idempotency_key: str | None,
        context_snapshot: dict,
    ) -> VisualFlowExecution:
        execution = VisualFlowExecution(
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            project_id=project_id,
            environment_id=environment_id,
            status="running",
            trigger_user_id=user_id,
            idempotency_key=idempotency_key,
            context_snapshot=context_snapshot,
            started_at=datetime.utcnow(),
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def create_node_execution(
        self,
        *,
        execution_id: int,
        node_id: str,
        status: str,
        request_snapshot: dict | None,
        output_snapshot: dict | None,
        error: dict | None,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> VisualFlowNodeExecution:
        node_execution = VisualFlowNodeExecution(
            execution_id=execution_id,
            node_id=node_id,
            status=status,
            request_snapshot=request_snapshot,
            output_snapshot=output_snapshot,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.db.add(node_execution)
        self.db.commit()
        self.db.refresh(node_execution)
        return node_execution

    def finish_execution(self, *, execution: VisualFlowExecution, status: str) -> VisualFlowExecution:
        execution.status = status
        execution.finished_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def list_node_executions(self, execution_id: int) -> list[VisualFlowNodeExecution]:
        statement = (
            select(VisualFlowNodeExecution)
            .where(VisualFlowNodeExecution.execution_id == execution_id)
            .order_by(VisualFlowNodeExecution.id)
        )
        return list(self.db.scalars(statement).all())
