from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.project import (
    Project,
    ProjectEnvironment,
    ProjectEnvironmentVariable,
    ProjectMember,
    ProjectMemberPermission,
)
from app.models.defect import Defect
from app.models.scenario import (
    TestScenario,
    TestScenarioExecution,
    TestScenarioRun,
    TestScenarioRunEvent,
    TestScenarioVersion,
)
from app.models.test_case import TestCase, TestCaseEnvironment
from app.models.test_case import TestCaseExecution
from app.models.test_plan import (
    TestPlan,
    TestPlanEnvironment,
    TestPlanRun,
    TestPlanScenario,
    TestPlanWebhookEvent,
)
from app.models.visual_flow import (
    VisualFlow,
    VisualFlowExecution,
    VisualFlowNodeExecution,
    VisualFlowVersion,
)
from app.models.websocket_test_case import (
    WebSocketTestCase,
    WebSocketTestCaseEnvironment,
    WebSocketTestCaseExecution,
)
from app.core.sensitive_data import protect_secret_text, reveal_secret_text


class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, project_id: int) -> Project | None:
        return self.db.get(Project, project_id)

    def list_visible_for_user(self, *, user_id: int, is_admin: bool) -> list[Project]:
        statement = select(Project).where(Project.is_deleted.is_(False)).order_by(Project.id.desc())
        if not is_admin:
            statement = (
                statement.outerjoin(ProjectMember)
                .where(
                    or_(
                        Project.created_by_id == user_id,
                        ProjectMember.user_id == user_id,
                    )
                )
                .distinct()
            )
        return list(self.db.scalars(statement).all())

    def create(self, *, name: str, description: str | None, created_by_id: int) -> Project:
        project = Project(name=name, description=description, created_by_id=created_by_id)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update(self, *, project: Project, name: str, description: str | None) -> Project:
        project.name = name
        project.description = description
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete_project(self, project: Project) -> None:
        project_id = project.id
        flow_ids = list(self.db.scalars(
            select(VisualFlow.id).where(VisualFlow.project_id == project_id)
        ).all())
        flow_execution_ids = list(self.db.scalars(
            select(VisualFlowExecution.id).where(VisualFlowExecution.project_id == project_id)
        ).all())
        scenario_ids = list(self.db.scalars(
            select(TestScenario.id).where(TestScenario.project_id == project_id)
        ).all())
        environment_ids = list(self.db.scalars(
            select(ProjectEnvironment.id).where(ProjectEnvironment.project_id == project_id)
        ).all())
        member_ids = list(self.db.scalars(
            select(ProjectMember.id).where(ProjectMember.project_id == project_id)
        ).all())

        if flow_execution_ids:
            self.db.execute(
                delete(VisualFlowNodeExecution).where(
                    VisualFlowNodeExecution.execution_id.in_(flow_execution_ids)
                )
            )
        self.db.execute(delete(VisualFlowExecution).where(VisualFlowExecution.project_id == project_id))
        if flow_ids:
            self.db.execute(delete(VisualFlowVersion).where(VisualFlowVersion.flow_id.in_(flow_ids)))
        self.db.execute(delete(VisualFlow).where(VisualFlow.project_id == project_id))

        self.db.execute(delete(TestCaseExecution).where(TestCaseExecution.project_id == project_id))
        self.db.execute(
            delete(WebSocketTestCaseExecution).where(
                WebSocketTestCaseExecution.project_id == project_id
            )
        )
        scenario_run_ids = list(self.db.scalars(
            select(TestScenarioRun.id).where(TestScenarioRun.project_id == project_id)
        ).all())
        if scenario_run_ids:
            self.db.execute(
                delete(TestScenarioRunEvent).where(
                    TestScenarioRunEvent.run_id.in_(scenario_run_ids)
                )
            )
        self.db.execute(delete(TestScenarioRun).where(TestScenarioRun.project_id == project_id))
        self.db.execute(
            delete(TestScenarioExecution).where(
                TestScenarioExecution.project_id == project_id
            )
        )
        self.db.execute(delete(TestPlanRun).where(TestPlanRun.project_id == project_id))
        self.db.execute(
            delete(TestPlanWebhookEvent).where(TestPlanWebhookEvent.project_id == project_id)
        )
        self.db.execute(delete(TestPlanScenario).where(TestPlanScenario.project_id == project_id))
        self.db.execute(
            delete(TestPlanEnvironment).where(TestPlanEnvironment.project_id == project_id)
        )
        self.db.execute(delete(TestPlan).where(TestPlan.project_id == project_id))

        if scenario_ids:
            self.db.execute(
                delete(TestScenarioVersion).where(
                    TestScenarioVersion.scenario_id.in_(scenario_ids)
                )
            )
        self.db.execute(delete(TestScenario).where(TestScenario.project_id == project_id))
        self.db.execute(delete(TestCaseEnvironment).where(TestCaseEnvironment.project_id == project_id))
        self.db.execute(
            delete(WebSocketTestCaseEnvironment).where(
                WebSocketTestCaseEnvironment.project_id == project_id
            )
        )
        self.db.execute(delete(TestCase).where(TestCase.project_id == project_id))
        self.db.execute(
            delete(WebSocketTestCase).where(WebSocketTestCase.project_id == project_id)
        )
        self.db.execute(delete(Defect).where(Defect.project_id == project_id))

        if environment_ids:
            self.db.execute(
                delete(ProjectEnvironmentVariable).where(
                    ProjectEnvironmentVariable.environment_id.in_(environment_ids)
                )
            )
        self.db.execute(
            delete(ProjectEnvironment).where(ProjectEnvironment.project_id == project_id)
        )
        if member_ids:
            self.db.execute(
                delete(ProjectMemberPermission).where(
                    ProjectMemberPermission.member_id.in_(member_ids)
                )
            )
        self.db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
        self.db.delete(project)
        self.db.commit()

    def get_member(self, *, project_id: int, user_id: int) -> ProjectMember | None:
        statement = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
        return self.db.scalar(statement)

    def add_member(self, *, project_id: int, user_id: int, added_by_id: int) -> ProjectMember:
        member = ProjectMember(project_id=project_id, user_id=user_id, added_by_id=added_by_id)
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def replace_member_permissions(self, *, member_id: int, permission_codes: set[str]) -> None:
        self.db.execute(
            delete(ProjectMemberPermission).where(ProjectMemberPermission.member_id == member_id)
        )
        for permission_code in sorted(permission_codes):
            self.db.add(
                ProjectMemberPermission(member_id=member_id, permission_code=permission_code)
            )
        self.db.commit()

    def get_member_permission_codes(self, *, project_id: int, user_id: int) -> set[str]:
        statement = (
            select(ProjectMemberPermission.permission_code)
            .join(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.is_active.is_(True),
            )
        )
        return set(self.db.scalars(statement).all())

    def list_environments(self, *, project_id: int) -> list[ProjectEnvironment]:
        statement = (
            select(ProjectEnvironment)
            .where(
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
            .order_by(ProjectEnvironment.is_default.desc(), ProjectEnvironment.id.desc())
        )
        return list(self.db.scalars(statement).all())

    def list_environments_with_context(self, *, project_id: int) -> list[ProjectEnvironment]:
        statement = (
            select(ProjectEnvironment)
            .options(
                selectinload(ProjectEnvironment.project),
                selectinload(ProjectEnvironment.created_by),
                selectinload(ProjectEnvironment.variables),
            )
            .where(
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
            .order_by(ProjectEnvironment.is_default.desc(), ProjectEnvironment.id.desc())
        )
        return list(self.db.scalars(statement).all())

    def get_environment(self, *, project_id: int, environment_id: int) -> ProjectEnvironment | None:
        statement = select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id,
            ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        )
        return self.db.scalar(statement)

    def get_environment_with_context(
        self,
        *,
        project_id: int,
        environment_id: int,
    ) -> ProjectEnvironment | None:
        statement = (
            select(ProjectEnvironment)
            .options(
                selectinload(ProjectEnvironment.project),
                selectinload(ProjectEnvironment.created_by),
                selectinload(ProjectEnvironment.variables),
            )
            .where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )
        return self.db.scalar(statement)

    def create_environment(
        self,
        *,
        project_id: int,
        name: str,
        base_url: str,
        description: str | None,
        is_default: bool,
        created_by_id: int,
    ) -> ProjectEnvironment:
        self._purge_deleted_environment_name(project_id=project_id, name=name)
        environment = ProjectEnvironment(
            project_id=project_id,
            name=name,
            base_url=base_url,
            description=description,
            is_default=is_default,
            created_by_id=created_by_id,
        )
        if is_default:
            self.clear_default_environment(project_id=project_id)
        self.db.add(environment)
        self.db.commit()
        self.db.refresh(environment)
        return environment

    def update_environment(
        self,
        *,
        environment: ProjectEnvironment,
        name: str,
        base_url: str,
        description: str | None,
        is_default: bool,
    ) -> ProjectEnvironment:
        if is_default:
            self.clear_default_environment(project_id=environment.project_id)
        environment.name = name
        environment.base_url = base_url
        environment.description = description
        environment.is_default = is_default
        self.db.commit()
        self.db.refresh(environment)
        return environment

    def delete_environment(self, environment: ProjectEnvironment) -> None:
        environment_id = environment.id
        plans = list(self.db.scalars(
            select(TestPlan)
            .join(TestPlanEnvironment, TestPlanEnvironment.plan_id == TestPlan.id)
            .where(TestPlanEnvironment.environment_id == environment_id)
        ).all())
        for plan in plans:
            plan.environment_ids = [
                item for item in plan.environment_ids if item != environment_id
            ]

        self.db.execute(
            update(TestCase)
            .where(TestCase.environment_id == environment_id)
            .values(environment_id=None)
        )
        self.db.execute(
            update(WebSocketTestCase)
            .where(WebSocketTestCase.environment_id == environment_id)
            .values(environment_id=None)
        )
        self.db.execute(
            update(TestCaseExecution)
            .where(TestCaseExecution.environment_id == environment_id)
            .values(environment_id=None)
        )
        self.db.execute(
            update(WebSocketTestCaseExecution)
            .where(WebSocketTestCaseExecution.environment_id == environment_id)
            .values(environment_id=None)
        )
        self.db.execute(
            update(TestPlanRun)
            .where(TestPlanRun.environment_id == environment_id)
            .values(environment_id=None)
        )
        self.db.execute(
            update(VisualFlowExecution)
            .where(VisualFlowExecution.environment_id == environment_id)
            .values(environment_id=None)
        )
        self.db.execute(
            delete(TestCaseEnvironment).where(
                TestCaseEnvironment.environment_id == environment_id
            )
        )
        self.db.execute(
            delete(WebSocketTestCaseEnvironment).where(
                WebSocketTestCaseEnvironment.environment_id == environment_id
            )
        )
        self.db.execute(
            delete(TestPlanEnvironment).where(
                TestPlanEnvironment.environment_id == environment_id
            )
        )
        self.db.execute(
            delete(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.environment_id == environment_id
            )
        )
        self.db.delete(environment)
        self.db.commit()

    def _purge_deleted_environment_name(self, *, project_id: int, name: str) -> None:
        environment = self.db.scalar(
            select(ProjectEnvironment).where(
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.name == name,
                ProjectEnvironment.is_deleted.is_(True),
            )
        )
        if environment is None:
            return
        self.delete_environment(environment)

    def clear_default_environment(self, *, project_id: int) -> None:
        self.db.execute(
            update(ProjectEnvironment)
            .where(
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
                ProjectEnvironment.is_default.is_(True),
            )
            .values(is_default=False)
        )

    def list_environment_variables(self, *, environment_id: int) -> list[ProjectEnvironmentVariable]:
        statement = select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.environment_id == environment_id
        ).order_by(ProjectEnvironmentVariable.id.desc())
        return list(self.db.scalars(statement).all())

    def get_environment_variable_values(self, *, environment_id: int) -> dict[str, str]:
        variables = self.list_environment_variables(environment_id=environment_id)
        return {
            variable.name: reveal_secret_text(variable.value) if variable.is_secret else variable.value
            for variable in variables
        }

    def count_test_cases_by_environment(self, *, environment_id: int) -> int:
        statement = select(func.count()).select_from(TestCaseEnvironment).where(
            TestCaseEnvironment.environment_id == environment_id
        )
        return int(self.db.scalar(statement) or 0)

    def list_test_cases_by_environment(self, *, project_id: int, environment_id: int) -> list[TestCase]:
        statement = (
            select(TestCase)
            .join(TestCaseEnvironment, TestCaseEnvironment.test_case_id == TestCase.id)
            .options(selectinload(TestCase.environment_links))
            .where(
                TestCase.project_id == project_id,
                TestCaseEnvironment.environment_id == environment_id,
            )
            .distinct()
            .order_by(TestCase.id.desc())
        )
        return list(self.db.scalars(statement).all())

    def get_test_case(self, *, project_id: int, test_case_id: int) -> TestCase | None:
        statement = select(TestCase).where(
            TestCase.project_id == project_id,
            TestCase.id == test_case_id,
        )
        return self.db.scalar(statement)

    def set_test_case_environment(
        self,
        *,
        test_case: TestCase,
        environment_id: int | None,
    ) -> TestCase:
        test_case.environment_id = environment_id
        self.db.commit()
        self.db.refresh(test_case)
        return test_case

    def get_environment_variable(self, *, environment_id: int, variable_id: int) -> ProjectEnvironmentVariable | None:
        statement = select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.environment_id == environment_id,
            ProjectEnvironmentVariable.id == variable_id,
        )
        return self.db.scalar(statement)

    def upsert_environment_variable(
        self,
        *,
        environment_id: int,
        name: str,
        value: str,
        is_secret: bool,
    ) -> ProjectEnvironmentVariable:
        statement = select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.environment_id == environment_id,
            ProjectEnvironmentVariable.name == name,
        )
        variable = self.db.scalar(statement)
        if variable is None:
            variable = ProjectEnvironmentVariable(
                environment_id=environment_id,
                name=name,
                value=protect_secret_text(value) if is_secret else value,
                is_secret=is_secret,
            )
            self.db.add(variable)
        else:
            variable.value = protect_secret_text(value) if is_secret else value
            variable.is_secret = is_secret
        self.db.commit()
        self.db.refresh(variable)
        return variable

    def delete_environment_variable(self, variable: ProjectEnvironmentVariable) -> None:
        self.db.delete(variable)
        self.db.commit()
