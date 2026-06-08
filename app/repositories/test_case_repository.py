from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.models.test_case import TestCase, TestCaseEnvironment, TestCaseExecution


class TestCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_project(self, *, project_id: int) -> list[TestCase]:
        statement = (
            select(TestCase)
            .options(selectinload(TestCase.environment_links))
            .where(TestCase.project_id == project_id)
            .order_by(TestCase.id.desc())
        )
        return list(self.db.scalars(statement).all())

    def get_by_id(self, *, project_id: int, test_case_id: int) -> TestCase | None:
        statement = (
            select(TestCase)
            .options(selectinload(TestCase.environment_links))
            .where(TestCase.project_id == project_id, TestCase.id == test_case_id)
        )
        return self.db.scalar(statement)

    def create(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        environment_ids: list[int],
        name: str,
        description: str | None,
        method: str,
        path: str,
        headers: dict | None,
        query_params: dict | None,
        body_type: str,
        body: dict | list | str | None,
        assertions: list | None,
        extractors: list | None,
        created_by_id: int,
    ) -> TestCase:
        test_case = TestCase(
            project_id=project_id,
            environment_id=environment_id,
            name=name,
            description=description,
            method=method,
            path=path,
            headers=headers,
            query_params=query_params,
            body_type=body_type,
            body=body,
            assertions=assertions,
            extractors=extractors,
            created_by_id=created_by_id,
        )
        self.db.add(test_case)
        self.db.flush()
        self._replace_environment_links(
            test_case_id=test_case.id,
            project_id=project_id,
            environment_ids=environment_ids,
        )
        self.db.commit()
        created_test_case = self.get_by_id(project_id=project_id, test_case_id=test_case.id)
        return created_test_case or test_case

    def update(
        self,
        *,
        test_case: TestCase,
        environment_id: int | None,
        environment_ids: list[int],
        name: str,
        description: str | None,
        method: str,
        path: str,
        headers: dict | None,
        query_params: dict | None,
        body_type: str,
        body: dict | list | str | None,
        assertions: list | None,
        extractors: list | None,
    ) -> TestCase:
        test_case.environment_id = environment_id
        test_case.name = name
        test_case.description = description
        test_case.method = method
        test_case.path = path
        test_case.headers = headers
        test_case.query_params = query_params
        test_case.body_type = body_type
        test_case.body = body
        test_case.assertions = assertions
        test_case.extractors = extractors
        self._replace_environment_links(
            test_case_id=test_case.id,
            project_id=test_case.project_id,
            environment_ids=environment_ids,
        )
        self.db.commit()
        updated_test_case = self.get_by_id(project_id=test_case.project_id, test_case_id=test_case.id)
        return updated_test_case or test_case

    def _replace_environment_links(
        self,
        *,
        test_case_id: int,
        project_id: int,
        environment_ids: list[int],
    ) -> None:
        self.db.execute(
            delete(TestCaseEnvironment).where(TestCaseEnvironment.test_case_id == test_case_id)
        )
        for environment_id in environment_ids:
            self.db.add(
                TestCaseEnvironment(
                    project_id=project_id,
                    test_case_id=test_case_id,
                    environment_id=environment_id,
                )
            )

    def get_environment(self, *, project_id: int, environment_id: int) -> ProjectEnvironment | None:
        statement = select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id,
            ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        )
        return self.db.scalar(statement)

    def get_environment_variables(self, *, environment_id: int) -> dict[str, str]:
        statement = select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.environment_id == environment_id
        )
        return {variable.name: variable.value for variable in self.db.scalars(statement).all()}

    def create_execution(
        self,
        *,
        project_id: int,
        test_case_id: int | None,
        environment_id: int | None,
        executed_by_id: int,
        status: str,
        request_snapshot: dict,
        response_snapshot: dict | None,
        assertion_results: list | None,
        error_message: str | None,
        duration_ms: int | None,
    ) -> TestCaseExecution:
        execution = TestCaseExecution(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            executed_by_id=executed_by_id,
            status=status,
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
            assertion_results=assertion_results,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        self.db.add(execution)
        if test_case_id is not None:
            self.db.execute(
                update(TestCase)
                .where(TestCase.id == test_case_id, TestCase.project_id == project_id)
                .values(last_execution_status=status, last_executed_at=func.now())
            )
        self.db.commit()
        self.db.refresh(execution)
        return execution
