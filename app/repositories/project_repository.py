from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.project import (
    Project,
    ProjectEnvironment,
    ProjectEnvironmentVariable,
    ProjectMember,
    ProjectMemberPermission,
)
from app.models.test_case import TestCase, TestCaseEnvironment


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

    def soft_delete(self, project: Project) -> Project:
        project.is_deleted = True
        self.db.commit()
        self.db.refresh(project)
        return project

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

    def soft_delete_environment(self, environment: ProjectEnvironment) -> ProjectEnvironment:
        environment.is_deleted = True
        environment.is_default = False
        self.db.commit()
        self.db.refresh(environment)
        return environment

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
                value=value,
                is_secret=is_secret,
            )
            self.db.add(variable)
        else:
            variable.value = value
            variable.is_secret = is_secret
        self.db.commit()
        self.db.refresh(variable)
        return variable

    def delete_environment_variable(self, variable: ProjectEnvironmentVariable) -> None:
        self.db.delete(variable)
        self.db.commit()
