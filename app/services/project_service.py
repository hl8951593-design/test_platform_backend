from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import NORMAL_TESTER_GRANTABLE_PERMISSIONS, ProjectPermission
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.project import (
    EnvironmentTestCaseRead,
    ProjectCreateRequest,
    ProjectEnvironmentCreateRequest,
    ProjectEnvironmentDetailRead,
    ProjectEnvironmentVariableUpsertRequest,
    ProjectEnvironmentUpdateRequest,
    ProjectMemberRead,
    ProjectUpdateRequest,
    TestCaseEnvironmentBindRequest,
)
from app.services.permission_service import PermissionService


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.user_repository = UserRepository(db)
        self.permission_service = PermissionService(db)

    def create(self, payload: ProjectCreateRequest, current_user: User) -> Project:
        return self.project_repository.create(
            name=payload.name,
            description=payload.description,
            created_by_id=current_user.id,
        )

    def get_visible_project(self, project_id: int, current_user: User) -> Project:
        return self.permission_service.require_project_access(current_user, project_id)

    def list_visible_projects(self, current_user: User) -> list[Project]:
        return self.project_repository.list_visible_for_user(
            user_id=current_user.id,
            is_admin=current_user.is_admin,
        )

    def update(self, project_id: int, payload: ProjectUpdateRequest, current_user: User) -> Project:
        project = self.permission_service.require_project_creator_or_admin(current_user, project_id)
        return self.project_repository.update(
            project=project,
            name=payload.name,
            description=payload.description,
        )

    def delete(self, project_id: int, current_user: User) -> None:
        project = self.permission_service.require_project_creator_or_admin(current_user, project_id)
        self.project_repository.delete_project(project)

    def grant_normal_tester_permissions(
        self,
        *,
        project_id: int,
        user_id: int,
        permission_codes: set[str],
        current_user: User,
    ) -> ProjectMemberRead:
        target_user = self.user_repository.get_by_id(user_id)
        if target_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        if target_user.is_admin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="管理员不需要加入项目授权")

        invalid_permissions = permission_codes - NORMAL_TESTER_GRANTABLE_PERMISSIONS
        if invalid_permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效权限编码: {', '.join(sorted(invalid_permissions))}",
            )

        member = self.permission_service.add_normal_tester(
            operator=current_user,
            project_id=project_id,
            user_id=user_id,
            permission_codes=permission_codes,
        )
        return ProjectMemberRead(
            id=member.id,
            project_id=member.project_id,
            user_id=member.user_id,
            added_by_id=member.added_by_id,
            is_active=member.is_active,
            permission_codes=permission_codes,
            created_at=member.created_at,
        )

    def list_environments(self, project_id: int, current_user: User) -> list[ProjectEnvironment]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_ENVIRONMENT.value,
        )
        return self.project_repository.list_environments(project_id=project_id)

    def list_environment_configs(
        self,
        *,
        project_id: int,
        current_user: User,
    ) -> list[ProjectEnvironmentDetailRead]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_ENVIRONMENT.value,
        )
        environments = self.project_repository.list_environments_with_context(project_id=project_id)
        return [self._build_environment_detail(environment) for environment in environments]

    def get_environment_config(
        self,
        *,
        project_id: int,
        environment_id: int,
        current_user: User,
    ) -> ProjectEnvironmentDetailRead:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_ENVIRONMENT.value,
        )
        environment = self.project_repository.get_environment_with_context(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        return self._build_environment_detail(environment)

    def create_environment(
        self,
        *,
        project_id: int,
        payload: ProjectEnvironmentCreateRequest,
        current_user: User,
    ) -> ProjectEnvironment:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_ENVIRONMENT.value,
        )
        try:
            return self.project_repository.create_environment(
                project_id=project_id,
                name=payload.name,
                base_url=payload.base_url,
                description=payload.description,
                is_default=payload.is_default,
                created_by_id=current_user.id,
            )
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一项目下环境名称不能重复",
            ) from exc

    def update_environment(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: ProjectEnvironmentUpdateRequest,
        current_user: User,
    ) -> ProjectEnvironment:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_ENVIRONMENT.value,
        )
        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        try:
            return self.project_repository.update_environment(
                environment=environment,
                name=payload.name,
                base_url=payload.base_url,
                description=payload.description,
                is_default=payload.is_default,
            )
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一项目下环境名称不能重复",
            ) from exc

    def delete_environment(self, *, project_id: int, environment_id: int, current_user: User) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_ENVIRONMENT.value,
        )
        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        scenario_count = self.db.scalar(
            select(func.count())
            .select_from(TestScenario)
            .where(TestScenario.environment_id == environment_id)
        ) or 0
        run_count = self.db.scalar(
            select(func.count())
            .select_from(TestScenarioRun)
            .where(TestScenarioRun.environment_id == environment_id)
        ) or 0
        if scenario_count or run_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="环境仍被场景或场景执行记录使用，不能删除",
            )
        self.project_repository.delete_environment(environment)

    def list_environment_test_cases(
        self,
        *,
        project_id: int,
        environment_id: int,
        current_user: User,
    ) -> list[EnvironmentTestCaseRead]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        test_cases = self.project_repository.list_test_cases_by_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        return [EnvironmentTestCaseRead.model_validate(test_case) for test_case in test_cases]

    def bind_test_case_environment(
        self,
        *,
        project_id: int,
        test_case_id: int,
        payload: TestCaseEnvironmentBindRequest,
        current_user: User,
    ) -> EnvironmentTestCaseRead:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        if payload.environment_id is not None:
            environment = self.project_repository.get_environment(
                project_id=project_id,
                environment_id=payload.environment_id,
            )
            if environment is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

        test_case = self.project_repository.get_test_case(
            project_id=project_id,
            test_case_id=test_case_id,
        )
        if test_case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")

        updated_test_case = self.project_repository.set_test_case_environment(
            test_case=test_case,
            environment_id=payload.environment_id,
        )
        return EnvironmentTestCaseRead.model_validate(updated_test_case)

    def list_environment_variables(self, *, project_id: int, environment_id: int, current_user: User):
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_ENVIRONMENT.value,
        )
        environment = self.project_repository.get_environment(project_id=project_id, environment_id=environment_id)
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        variables = self.project_repository.list_environment_variables(environment_id=environment_id)
        return [
            {
                "id": variable.id,
                "environment_id": variable.environment_id,
                "name": variable.name,
                "value": "***" if variable.is_secret else variable.value,
                "is_secret": variable.is_secret,
                "created_at": variable.created_at,
                "updated_at": variable.updated_at,
            }
            for variable in variables
        ]

    def upsert_environment_variable(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: ProjectEnvironmentVariableUpsertRequest,
        current_user: User,
    ):
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_ENVIRONMENT.value,
        )
        environment = self.project_repository.get_environment(project_id=project_id, environment_id=environment_id)
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        variable = self.project_repository.upsert_environment_variable(
            environment_id=environment_id,
            name=payload.name,
            value=payload.value,
            is_secret=payload.is_secret,
        )
        return {
            "id": variable.id,
            "environment_id": variable.environment_id,
            "name": variable.name,
            "value": "***" if variable.is_secret else variable.value,
            "is_secret": variable.is_secret,
            "created_at": variable.created_at,
            "updated_at": variable.updated_at,
        }

    def delete_environment_variable(
        self,
        *,
        project_id: int,
        environment_id: int,
        variable_id: int,
        current_user: User,
    ) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_ENVIRONMENT.value,
        )
        environment = self.project_repository.get_environment(project_id=project_id, environment_id=environment_id)
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        variable = self.project_repository.get_environment_variable(
            environment_id=environment_id,
            variable_id=variable_id,
        )
        if variable is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境变量不存在")
        self.project_repository.delete_environment_variable(variable)

    def _build_environment_detail(self, environment: ProjectEnvironment) -> ProjectEnvironmentDetailRead:
        detail = ProjectEnvironmentDetailRead.model_validate(environment)
        for variable in detail.variables:
            if variable.is_secret:
                variable.value = "***"
        detail.test_case_count = self.project_repository.count_test_cases_by_environment(
            environment_id=environment.id,
        )
        return detail
