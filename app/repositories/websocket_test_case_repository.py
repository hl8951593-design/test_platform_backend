from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.core.sensitive_data import reveal_secret_text
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseEnvironment, WebSocketTestCaseExecution
from app.models.visual_flow import VisualFlow, VisualFlowVersion


class WebSocketTestCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_project(self, *, project_id: int) -> list[WebSocketTestCase]:
        statement = select(WebSocketTestCase).options(selectinload(WebSocketTestCase.environment_links)).where(
            WebSocketTestCase.project_id == project_id
        ).order_by(WebSocketTestCase.id.desc())
        return list(self.db.scalars(statement).all())

    def get_by_id(self, *, project_id: int, test_case_id: int) -> WebSocketTestCase | None:
        statement = select(WebSocketTestCase).options(selectinload(WebSocketTestCase.environment_links)).where(
            WebSocketTestCase.project_id == project_id, WebSocketTestCase.id == test_case_id
        )
        return self.db.scalar(statement)

    def save(self, *, test_case: WebSocketTestCase, environment_ids: list[int]) -> WebSocketTestCase:
        self.db.add(test_case)
        self.db.flush()
        self.db.execute(delete(WebSocketTestCaseEnvironment).where(
            WebSocketTestCaseEnvironment.websocket_test_case_id == test_case.id
        ))
        for environment_id in environment_ids:
            self.db.add(WebSocketTestCaseEnvironment(
                project_id=test_case.project_id,
                websocket_test_case_id=test_case.id,
                environment_id=environment_id,
            ))
        self.db.commit()
        return self.get_by_id(project_id=test_case.project_id, test_case_id=test_case.id) or test_case

    def delete(self, test_case: WebSocketTestCase) -> None:
        self.db.execute(
            update(WebSocketTestCaseExecution)
            .where(WebSocketTestCaseExecution.websocket_test_case_id == test_case.id)
            .values(websocket_test_case_id=None)
        )
        self.db.execute(delete(WebSocketTestCaseEnvironment).where(
            WebSocketTestCaseEnvironment.websocket_test_case_id == test_case.id
        ))
        self.db.delete(test_case)
        self.db.commit()

    def referencing_flow_names(self, *, project_id: int, test_case_id: int) -> list[str]:
        rows = self.db.execute(
            select(VisualFlow.name, VisualFlowVersion.definition)
            .join(VisualFlowVersion, VisualFlowVersion.flow_id == VisualFlow.id)
            .where(
                VisualFlow.project_id == project_id,
                VisualFlow.status != "archived",
            )
        ).all()
        return sorted({
            name for name, definition in rows
            if self._definition_references_case(
                definition, kind="websocket_case", test_case_id=test_case_id
            )
        })

    @staticmethod
    def _definition_references_case(definition: dict, *, kind: str, test_case_id: int) -> bool:
        if not isinstance(definition, dict):
            return False
        for node in definition.get("nodes", []):
            if not isinstance(node, dict):
                continue
            reference_id = node.get("reference_id", node.get("referenceId"))
            if node.get("kind") == kind and str(reference_id) == str(test_case_id):
                return True
        return False

    def get_environment(self, *, project_id: int, environment_id: int) -> ProjectEnvironment | None:
        return self.db.scalar(select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id,
            ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        ))

    def get_environment_variables(self, *, environment_id: int) -> dict[str, str]:
        statement = select(ProjectEnvironmentVariable).where(ProjectEnvironmentVariable.environment_id == environment_id)
        return {
            item.name: reveal_secret_text(item.value) if item.is_secret else item.value
            for item in self.db.scalars(statement).all()
        }

    def create_execution(self, **values) -> WebSocketTestCaseExecution:
        execution = WebSocketTestCaseExecution(**values)
        self.db.add(execution)
        test_case_id = values.get("websocket_test_case_id")
        if test_case_id is not None:
            self.db.execute(update(WebSocketTestCase).where(
                WebSocketTestCase.id == test_case_id,
                WebSocketTestCase.project_id == values["project_id"],
            ).values(last_execution_status=values["status"], last_executed_at=func.now()))
        self.db.commit()
        self.db.refresh(execution)
        return execution
