from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.core.sensitive_data import reveal_secret_text
from app.models.test_case import TestCase, TestCaseEnvironment, TestCaseExecution
from app.models.visual_flow import VisualFlow, VisualFlowVersion


class TestCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_project(
        self,
        *,
        project_id: int,
        keyword: str | None,
        environment_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TestCase], int]:
        conditions = [TestCase.project_id == project_id]
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(TestCase.name.ilike(pattern), TestCase.description.ilike(pattern))
            )
        if environment_id is not None:
            conditions.append(
                or_(
                    TestCase.environment_id == environment_id,
                    TestCase.environment_links.any(
                        TestCaseEnvironment.environment_id == environment_id
                    ),
                )
            )
        total = self.db.scalar(
            select(func.count(TestCase.id)).where(*conditions)
        ) or 0
        statement = (
            select(TestCase)
            .options(selectinload(TestCase.environment_links))
            .where(*conditions)
            .order_by(TestCase.updated_at.desc(), TestCase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(statement).all()), int(total)

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
        retry_policy: dict | None,
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
            retry_policy=retry_policy,
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
        retry_policy: dict | None,
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
        test_case.retry_policy = retry_policy
        self._replace_environment_links(
            test_case_id=test_case.id,
            project_id=test_case.project_id,
            environment_ids=environment_ids,
        )
        self.db.commit()
        updated_test_case = self.get_by_id(project_id=test_case.project_id, test_case_id=test_case.id)
        return updated_test_case or test_case

    def delete(self, test_case: TestCase) -> None:
        self.db.execute(
            update(TestCaseExecution)
            .where(TestCaseExecution.test_case_id == test_case.id)
            .values(test_case_id=None)
        )
        self.db.execute(
            delete(TestCaseEnvironment).where(TestCaseEnvironment.test_case_id == test_case.id)
        )
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
                definition, kind="api_case", test_case_id=test_case_id
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
        return {
            variable.name: reveal_secret_text(variable.value) if variable.is_secret else variable.value
            for variable in self.db.scalars(statement).all()
        }

    def create_execution(
        self,
        *,
        project_id: int,
        test_case_id: int | None,
        environment_id: int | None,
        scenario_run_id: int | None,
        executed_by_id: int,
        status: str,
        request_snapshot: dict,
        response_snapshot: dict | None,
        assertion_results: list | None,
        attempt_history: list | None,
        error_message: str | None,
        duration_ms: int | None,
    ) -> TestCaseExecution:
        execution = TestCaseExecution(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            scenario_run_id=scenario_run_id,
            executed_by_id=executed_by_id,
            status=status,
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
            assertion_results=assertion_results,
            attempt_history=attempt_history,
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
