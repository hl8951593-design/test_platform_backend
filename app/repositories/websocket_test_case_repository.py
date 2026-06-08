from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseEnvironment, WebSocketTestCaseExecution


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

    def get_environment(self, *, project_id: int, environment_id: int) -> ProjectEnvironment | None:
        return self.db.scalar(select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id,
            ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        ))

    def get_environment_variables(self, *, environment_id: int) -> dict[str, str]:
        statement = select(ProjectEnvironmentVariable).where(ProjectEnvironmentVariable.environment_id == environment_id)
        return {item.name: item.value for item in self.db.scalars(statement).all()}

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
