import logging
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import case, func, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import NORMAL_TESTER_GRANTABLE_PERMISSIONS, ProjectPermission
from app.models.defect import Defect
from app.models.project import Project, ProjectEnvironment, ProjectMember
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.test_case import TestCase, TestCaseExecution
from app.models.test_plan import TestPlan, TestPlanRun
from app.models.system_test_case import SystemTestCase
from app.models.visual_flow import VisualFlow, VisualFlowExecution
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseExecution
from app.repositories.project_repository import ProjectRepository
from app.repositories.media_repository import MediaRepository
from app.repositories.user_repository import UserRepository
from app.schemas.project import (
    EnvironmentTestCaseRead,
    ProjectCreateRequest,
    ProjectEnvironmentCreateRequest,
    ProjectEnvironmentDetailRead,
    ProjectEnvironmentVariableUpsertRequest,
    ProjectEnvironmentUpdateRequest,
    ProjectActivityRead,
    ProjectLatestExecutionRead,
    ProjectMemberDetailRead,
    ProjectMemberRead,
    ProjectMemberSummaryRead,
    ProjectRead,
    ProjectRecommendationRead,
    ProjectStatsRead,
    ProjectTestingCountsRead,
    ProjectTestingOverviewRead,
    ProjectTestingQualityRead,
    ProjectUpdateRequest,
    TestCaseEnvironmentBindRequest,
)
from app.services.permission_service import PermissionService
from app.services.object_storage_service import ObjectStorageService


logger = logging.getLogger(__name__)


class ProjectService:
    PASSED_STATUSES = {"passed", "success", "completed"}
    FAILED_STATUSES = {"failed", "failure", "error", "timeout"}
    STATUS_LABELS = {
        "passed": "通过",
        "success": "通过",
        "completed": "通过",
        "failed": "失败",
        "failure": "失败",
        "error": "失败",
        "running": "运行中",
        "pending": "待执行",
        "skipped": "跳过",
    }

    def __init__(self, db: Session):
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.user_repository = UserRepository(db)
        self.permission_service = PermissionService(db)
        self.media_repository = MediaRepository(db)
        self.object_storage = ObjectStorageService()

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

    def build_project_read(self, project: Project) -> ProjectRead:
        owner = self._get_user(project.created_by_id)
        owner_name = self._user_display_name(owner)
        is_active = not project.is_deleted
        return ProjectRead(
            id=project.id,
            name=project.name,
            description=project.description,
            created_by_id=project.created_by_id,
            is_deleted=project.is_deleted,
            created_at=project.created_at,
            updated_at=project.updated_at,
            owner_name=owner_name,
            status="active" if is_active else "deleted",
            is_active=is_active,
            members=self._build_project_members(project, owner=owner),
            stats=self._build_project_stats(project),
        )

    def build_project_reads(self, projects: list[Project]) -> list[ProjectRead]:
        if not projects:
            return []

        project_ids = [project.id for project in projects]
        owners = {
            project.created_by_id: project.creator
            for project in projects
            if project.creator is not None
        }
        missing_owner_ids = {project.created_by_id for project in projects if project.created_by_id not in owners}
        owners.update(self._users_by_id(missing_owner_ids))
        members_by_project = self._project_members_by_project(projects, owners)
        stats_by_project = self._project_stats_by_project(project_ids)

        reads: list[ProjectRead] = []
        for project in projects:
            owner = owners.get(project.created_by_id)
            owner_name = self._user_display_name(owner)
            is_active = not project.is_deleted
            reads.append(
                ProjectRead(
                    id=project.id,
                    name=project.name,
                    description=project.description,
                    created_by_id=project.created_by_id,
                    is_deleted=project.is_deleted,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                    owner_name=owner_name,
                    status="active" if is_active else "deleted",
                    is_active=is_active,
                    members=members_by_project.get(project.id, []),
                    stats=stats_by_project.get(project.id, ProjectStatsRead()),
                )
            )
        return reads

    def build_testing_overview(
        self,
        *,
        project_id: int,
        current_user: User,
    ) -> ProjectTestingOverviewRead:
        project = self.permission_service.require_project_access(current_user, project_id)
        stats = self._build_project_stats(project)
        latest_execution = self._latest_project_execution_detail(project_id)
        return ProjectTestingOverviewRead(
            project_id=project_id,
            generated_at=datetime.now(),
            counts=ProjectTestingCountsRead(
                http_test_cases=stats.http_test_case_count,
                websocket_test_cases=stats.websocket_test_case_count,
                system_test_cases=stats.system_test_case_count,
                api_test_cases=stats.api_case_count,
                scenarios=stats.scenario_count,
                plans=stats.plan_count,
                flows=stats.flow_count,
                total_executions=stats.run_count,
                passed_executions=stats.passed_execution_count,
                failed_executions=stats.failed_execution_count,
                open_defects=stats.open_defect_count,
                total_defects=stats.total_defect_count,
            ),
            quality=ProjectTestingQualityRead(
                pass_rate=stats.pass_rate,
                api_execution_coverage_rate=stats.api_execution_coverage_rate,
                api_success_coverage_rate=stats.api_success_coverage_rate,
                risk_score=stats.risk_score,
                risk_level=stats.risk_level,
            ),
            latest_execution=latest_execution,
            recommendations=stats.recommendations,
            activities=self._project_activities(project),
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
        media_objects = [
            (media.bucket, media.object_key)
            for media in self.media_repository.list_by_project(project_id)
        ]
        # Delete relational state first. A storage outage must never leave a live
        # project whose attachment metadata still exists but whose objects are gone.
        self.project_repository.delete_project(project)
        for bucket, object_key in media_objects:
            try:
                self.object_storage.delete(bucket=bucket, object_key=object_key)
            except Exception:  # noqa: BLE001 - object cleanup is best effort after DB commit
                logger.exception(
                    "project media cleanup failed after project deletion",
                    extra={"project_id": project_id, "bucket": bucket, "object_key": object_key},
                )

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

    def list_members(
        self,
        *,
        project_id: int,
        current_user: User,
    ) -> list[ProjectMemberDetailRead]:
        project = self.permission_service.require_project_access(current_user, project_id)
        owner = self._get_user(project.created_by_id)
        members: list[ProjectMemberDetailRead] = []
        if owner is not None:
            owner_name = self._user_display_name(owner) or owner.account
            members.append(
                ProjectMemberDetailRead(
                    id=owner.id,
                    membership_id=None,
                    project_id=project.id,
                    user_id=owner.id,
                    username=owner.account,
                    display_name=owner_name,
                    avatar_url=owner.avatar,
                    role="owner",
                    permission_codes=sorted(permission.value for permission in ProjectPermission),
                    is_active=bool(owner.is_active),
                    added_by_id=owner.id,
                    added_by_name=owner_name,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )

        for member in self.project_repository.list_members(project_id=project_id):
            if member.user_id == project.created_by_id or member.user is None:
                continue
            permission_codes = sorted(permission.permission_code for permission in member.permissions)
            members.append(self._member_detail(member, permission_codes=permission_codes))
        return members

    def update_member_permissions(
        self,
        *,
        project_id: int,
        user_id: int,
        permission_codes: set[str],
        current_user: User,
    ) -> ProjectMemberDetailRead:
        project = self.permission_service.require_can_grant_member_permissions(current_user, project_id)
        if user_id == project.created_by_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目创建者权限不可修改")
        invalid_permissions = permission_codes - NORMAL_TESTER_GRANTABLE_PERMISSIONS
        if invalid_permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效权限编码: {', '.join(sorted(invalid_permissions))}",
            )
        member = self.project_repository.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目成员不存在")
        self.project_repository.replace_member_permissions(
            member_id=member.id,
            permission_codes=permission_codes,
        )
        return self._member_detail(member, permission_codes=sorted(permission_codes))

    def remove_member(
        self,
        *,
        project_id: int,
        user_id: int,
        current_user: User,
    ) -> None:
        project = self.permission_service.require_can_grant_member_permissions(current_user, project_id)
        if user_id == project.created_by_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目创建者不能被移除")
        member = self.project_repository.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目成员不存在")
        self.project_repository.set_member_active(member=member, is_active=False)

    def _member_detail(
        self,
        member: ProjectMember,
        *,
        permission_codes: list[str],
    ) -> ProjectMemberDetailRead:
        user = member.user or self._get_user(member.user_id)
        added_by = member.added_by or self._get_user(member.added_by_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目成员用户不存在")
        user_name = self._user_display_name(user) or user.account
        added_by_name = self._user_display_name(added_by) or str(member.added_by_id)
        role = "viewer" if not permission_codes or all(code.endswith(":view") for code in permission_codes) else "tester"
        return ProjectMemberDetailRead(
            id=user.id,
            membership_id=member.id,
            project_id=member.project_id,
            user_id=user.id,
            username=user.account,
            display_name=user_name,
            avatar_url=user.avatar,
            role=role,
            permission_codes=permission_codes,
            is_active=member.is_active,
            added_by_id=member.added_by_id,
            added_by_name=added_by_name,
            created_at=member.created_at,
            updated_at=member.updated_at,
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
        counts_by_environment = self.project_repository.count_test_cases_by_environment_ids(
            project_id=project_id,
            environment_ids=[environment.id for environment in environments],
        )
        return [
            self._build_environment_detail(
                environment,
                test_case_count=counts_by_environment.get(environment.id, 0),
            )
            for environment in environments
        ]

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

    def _build_project_members(self, project: Project, *, owner: User | None) -> list[ProjectMemberSummaryRead]:
        members: list[ProjectMemberSummaryRead] = []
        seen_user_ids: set[int] = set()
        if owner is not None:
            members.append(
                ProjectMemberSummaryRead(
                    id=owner.id,
                    name=self._user_display_name(owner),
                    role="负责人",
                )
            )
            seen_user_ids.add(owner.id)

        statement = (
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.is_active.is_(True),
            )
            .order_by(ProjectMember.id.asc())
        )
        for member in self.db.scalars(statement).all():
            if member.user_id in seen_user_ids:
                continue
            user = member.user or self._get_user(member.user_id)
            if user is None:
                continue
            members.append(
                ProjectMemberSummaryRead(
                    id=user.id,
                    name=self._user_display_name(user),
                    role="成员",
                )
            )
            seen_user_ids.add(user.id)
        return members

    def _users_by_id(self, user_ids: set[int | None]) -> dict[int, User]:
        ids = [user_id for user_id in user_ids if user_id is not None]
        if not ids:
            return {}
        users = self.db.scalars(select(User).where(User.id.in_(ids))).all()
        return {user.id: user for user in users}

    def _project_members_by_project(
        self,
        projects: list[Project],
        owners: dict[int, User],
    ) -> dict[int, list[ProjectMemberSummaryRead]]:
        project_ids = [project.id for project in projects]
        members_by_project: dict[int, list[ProjectMemberSummaryRead]] = {project_id: [] for project_id in project_ids}
        seen_by_project: dict[int, set[int]] = {project_id: set() for project_id in project_ids}

        for project in projects:
            owner = owners.get(project.created_by_id)
            if owner is None:
                continue
            members_by_project[project.id].append(
                ProjectMemberSummaryRead(
                    id=owner.id,
                    name=self._user_display_name(owner),
                    role="负责人",
                )
            )
            seen_by_project[project.id].add(owner.id)

        statement = (
            select(
                ProjectMember.project_id,
                User.id,
                User.username,
                User.account,
            )
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id.in_(project_ids),
                ProjectMember.is_active.is_(True),
            )
            .order_by(ProjectMember.id.asc())
        )
        for row in self.db.execute(statement).all():
            project_id = row.project_id
            if row.id in seen_by_project[project_id]:
                continue
            members_by_project[project_id].append(
                ProjectMemberSummaryRead(
                    id=row.id,
                    name=row.username or row.account or f"用户{row.id}",
                    role="成员",
                )
            )
            seen_by_project[project_id].add(row.id)
        return members_by_project

    def _project_stats_by_project(self, project_ids: list[int]) -> dict[int, ProjectStatsRead]:
        http_case_count = self._project_count_subquery(TestCase)
        websocket_case_count = self._project_count_subquery(WebSocketTestCase)
        system_case_count = self._project_count_subquery(SystemTestCase)
        scenario_count = self._project_count_subquery(TestScenario, TestScenario.is_deleted.is_(False))
        plan_count = self._project_count_subquery(TestPlan, TestPlan.is_deleted.is_(False))
        flow_count = self._project_count_subquery(VisualFlow)
        total_defect_count = self._project_count_subquery(Defect)
        open_defect_count = self._project_count_subquery(Defect, Defect.status != "closed")
        http_run_count = self._project_count_subquery(TestCaseExecution, TestCaseExecution.scenario_run_id.is_(None))
        websocket_run_count = self._project_count_subquery(
            WebSocketTestCaseExecution, WebSocketTestCaseExecution.scenario_run_id.is_(None)
        )
        scenario_run_count = self._project_count_subquery(TestScenarioRun, TestScenarioRun.plan_run_id.is_(None))
        plan_run_count = self._project_count_subquery(TestPlanRun, TestPlanRun.is_deleted.is_(False))
        flow_run_count = self._project_count_subquery(VisualFlowExecution)
        http_passed_count = self._project_count_subquery(
            TestCaseExecution,
            TestCaseExecution.scenario_run_id.is_(None),
            TestCaseExecution.status.in_(self.PASSED_STATUSES),
        )
        websocket_passed_count = self._project_count_subquery(
            WebSocketTestCaseExecution,
            WebSocketTestCaseExecution.scenario_run_id.is_(None),
            WebSocketTestCaseExecution.status.in_(self.PASSED_STATUSES),
        )
        scenario_passed_count = self._project_count_subquery(
            TestScenarioRun,
            TestScenarioRun.plan_run_id.is_(None),
            TestScenarioRun.status.in_(self.PASSED_STATUSES),
        )
        flow_passed_count = self._project_count_subquery(
            VisualFlowExecution,
            VisualFlowExecution.status.in_(self.PASSED_STATUSES),
        )
        http_failed_count = self._project_count_subquery(
            TestCaseExecution,
            TestCaseExecution.scenario_run_id.is_(None),
            TestCaseExecution.status.in_(self.FAILED_STATUSES),
        )
        websocket_failed_count = self._project_count_subquery(
            WebSocketTestCaseExecution,
            WebSocketTestCaseExecution.scenario_run_id.is_(None),
            WebSocketTestCaseExecution.status.in_(self.FAILED_STATUSES),
        )
        scenario_failed_count = self._project_count_subquery(
            TestScenarioRun,
            TestScenarioRun.plan_run_id.is_(None),
            TestScenarioRun.status.in_(self.FAILED_STATUSES),
        )
        plan_failed_count = self._project_count_subquery(
            TestPlanRun,
            TestPlanRun.is_deleted.is_(False),
            TestPlanRun.status.in_(self.FAILED_STATUSES),
        )
        flow_failed_count = self._project_count_subquery(
            VisualFlowExecution,
            VisualFlowExecution.status.in_(self.FAILED_STATUSES),
        )
        http_covered_count = self._project_distinct_count_subquery(
            TestCaseExecution,
            TestCaseExecution.test_case_id,
            TestCaseExecution.test_case_id.is_not(None),
            TestCaseExecution.status.notin_(("queued", "pending", "running")),
        )
        websocket_covered_count = self._project_distinct_count_subquery(
            WebSocketTestCaseExecution,
            WebSocketTestCaseExecution.websocket_test_case_id,
            WebSocketTestCaseExecution.websocket_test_case_id.is_not(None),
            WebSocketTestCaseExecution.status.notin_(("queued", "pending", "running")),
        )
        http_successfully_automated_count = self._project_distinct_count_subquery(
            TestCaseExecution,
            TestCaseExecution.test_case_id,
            TestCaseExecution.test_case_id.is_not(None),
            TestCaseExecution.status.in_(self.PASSED_STATUSES),
        )
        websocket_successfully_automated_count = self._project_distinct_count_subquery(
            WebSocketTestCaseExecution,
            WebSocketTestCaseExecution.websocket_test_case_id,
            WebSocketTestCaseExecution.websocket_test_case_id.is_not(None),
            WebSocketTestCaseExecution.status.in_(self.PASSED_STATUSES),
        )
        plan_passed_count = self._project_count_subquery(
            TestPlanRun,
            TestPlanRun.is_deleted.is_(False),
            TestPlanRun.status.in_(self.PASSED_STATUSES),
        )
        stats_statement = select(
            Project.id.label("project_id"),
            http_case_count.label("http_case_count"),
            websocket_case_count.label("websocket_case_count"),
            system_case_count.label("system_case_count"),
            scenario_count.label("scenario_count"),
            plan_count.label("plan_count"),
            flow_count.label("flow_count"),
            total_defect_count.label("total_defect_count"),
            open_defect_count.label("open_defect_count"),
            (http_run_count + websocket_run_count + scenario_run_count + plan_run_count + flow_run_count).label("run_count"),
            (http_passed_count + websocket_passed_count + scenario_passed_count + plan_passed_count + flow_passed_count).label(
                "passed_count"
            ),
            (http_failed_count + websocket_failed_count + scenario_failed_count + plan_failed_count + flow_failed_count).label(
                "failed_count"
            ),
            (http_covered_count + websocket_covered_count).label("covered_count"),
            (http_successfully_automated_count + websocket_successfully_automated_count).label("automated_count"),
        ).where(Project.id.in_(project_ids))
        stats_rows = {row.project_id: row for row in self.db.execute(stats_statement).all()}
        latest_executions = self._latest_execution_by_project(project_ids)

        stats_by_project: dict[int, ProjectStatsRead] = {}
        for project_id in project_ids:
            row = stats_rows.get(project_id)
            http_case_total = int(row.http_case_count or 0) if row is not None else 0
            websocket_case_total = int(row.websocket_case_count or 0) if row is not None else 0
            api_case_count = http_case_total + websocket_case_total
            system_case_total = int(row.system_case_count or 0) if row is not None else 0
            scenario_total = int(row.scenario_count or 0) if row is not None else 0
            plan_total = int(row.plan_count or 0) if row is not None else 0
            flow_total = int(row.flow_count or 0) if row is not None else 0
            total_defects = int(row.total_defect_count or 0) if row is not None else 0
            open_defects = int(row.open_defect_count or 0) if row is not None else 0
            run_count = int(row.run_count or 0) if row is not None else 0
            passed_count = int(row.passed_count or 0) if row is not None else 0
            failed_count = int(row.failed_count or 0) if row is not None else 0
            pass_rate = round(passed_count / run_count * 100) if run_count else 0
            latest_status, last_run_at = latest_executions.get(project_id, (None, None))
            covered_count = int(row.covered_count or 0) if row is not None else 0
            automated_count = int(row.automated_count or 0) if row is not None else 0
            coverage_rate = min(100, round(covered_count / api_case_count * 100)) if api_case_count else 0
            automation_rate = min(100, round(automated_count / api_case_count * 100)) if api_case_count else 0
            risk_score = self._calculate_risk_score(
                api_case_count=api_case_count,
                pass_rate=pass_rate,
                run_count=run_count,
                defect_count=open_defects,
                coverage_rate=coverage_rate,
            )
            recommendations = self._build_structured_recommendations(
                project_id=project_id,
                api_case_count=api_case_count,
                coverage_rate=coverage_rate,
                open_defect_count=open_defects,
                failed_execution_count=failed_count,
                scenario_count=scenario_total,
                plan_count=plan_total,
                flow_count=flow_total,
            )
            activities = self._build_structured_activity(last_run_at=last_run_at)
            stats_by_project[project_id] = ProjectStatsRead(
                api_case_count=api_case_count,
                http_test_case_count=http_case_total,
                websocket_test_case_count=websocket_case_total,
                system_test_case_count=system_case_total,
                test_case_count=api_case_count,
                scenario_count=scenario_total,
                plan_count=plan_total,
                flow_count=flow_total,
                run_count=run_count,
                passed_execution_count=passed_count,
                failed_execution_count=failed_count,
                pass_rate=pass_rate,
                api_execution_coverage_rate=coverage_rate,
                api_success_coverage_rate=automation_rate,
                coverage_rate=coverage_rate,
                automation_rate=automation_rate,
                open_defect_count=open_defects,
                total_defect_count=total_defects,
                defect_count=total_defects,
                last_run_at=last_run_at,
                last_execution_status=self._status_label(latest_status),
                risk_score=risk_score,
                risk_level=self._risk_level(risk_score),
                ai_recommendations=self._build_project_recommendations(
                    api_case_count=api_case_count,
                    coverage_rate=coverage_rate,
                    defect_count=open_defects,
                    pass_rate=pass_rate,
                    run_count=run_count,
                ),
                team_activity=self._build_project_activity(last_run_at=last_run_at),
                recommendations=recommendations,
                activities=activities,
            )
        return stats_by_project

    def _project_count_subquery(self, model, *conditions):
        return (
            select(func.count())
            .select_from(model)
            .where(model.project_id == Project.id, *conditions)
            .correlate(Project)
            .scalar_subquery()
        )

    def _project_distinct_count_subquery(self, model, column, *conditions):
        return (
            select(func.count(func.distinct(column)))
            .select_from(model)
            .where(model.project_id == Project.id, *conditions)
            .correlate(Project)
            .scalar_subquery()
        )

    def _counts_by_project(self, model, project_ids: list[int], *conditions) -> dict[int, int]:
        statement = (
            select(model.project_id, func.count().label("count"))
            .where(model.project_id.in_(project_ids), *conditions)
            .group_by(model.project_id)
        )
        return {row.project_id: int(row.count or 0) for row in self.db.execute(statement).all()}

    def _execution_stats_by_project(self, project_ids: list[int]) -> dict[int, dict[str, int]]:
        status_sources = union_all(
            select(TestCaseExecution.project_id.label("project_id"), TestCaseExecution.status.label("status")).where(
                TestCaseExecution.project_id.in_(project_ids),
                TestCaseExecution.scenario_run_id.is_(None),
            ),
            select(
                WebSocketTestCaseExecution.project_id.label("project_id"),
                WebSocketTestCaseExecution.status.label("status"),
            ).where(
                WebSocketTestCaseExecution.project_id.in_(project_ids),
                WebSocketTestCaseExecution.scenario_run_id.is_(None),
            ),
            select(TestScenarioRun.project_id.label("project_id"), TestScenarioRun.status.label("status")).where(
                TestScenarioRun.project_id.in_(project_ids),
                TestScenarioRun.plan_run_id.is_(None),
            ),
            select(TestPlanRun.project_id.label("project_id"), TestPlanRun.status.label("status")).where(
                TestPlanRun.project_id.in_(project_ids),
                TestPlanRun.is_deleted.is_(False),
            ),
            select(
                VisualFlowExecution.project_id.label("project_id"),
                VisualFlowExecution.status.label("status"),
            ).where(VisualFlowExecution.project_id.in_(project_ids)),
        ).subquery()
        statement = (
            select(
                status_sources.c.project_id,
                func.count().label("total"),
                func.coalesce(
                    func.sum(case((status_sources.c.status.in_(tuple(self.PASSED_STATUSES)), 1), else_=0)),
                    0,
                ).label("passed"),
            )
            .group_by(status_sources.c.project_id)
        )
        return {
            row.project_id: {
                "total": int(row.total or 0),
                "passed": int(row.passed or 0),
            }
            for row in self.db.execute(statement).all()
        }

    def _latest_execution_by_project(self, project_ids: list[int]) -> dict[int, tuple[str | None, datetime | None]]:
        statement = select(
            Project.id.label("project_id"),
            self._latest_field_subquery(
                TestCaseExecution,
                TestCaseExecution.status,
                TestCaseExecution.created_at,
                TestCaseExecution.scenario_run_id.is_(None),
            ).label(
                "http_status"
            ),
            self._latest_field_subquery(
                TestCaseExecution,
                TestCaseExecution.created_at,
                TestCaseExecution.created_at,
                TestCaseExecution.scenario_run_id.is_(None),
            ).label("http_at"),
            self._latest_field_subquery(
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.status,
                WebSocketTestCaseExecution.created_at,
                WebSocketTestCaseExecution.scenario_run_id.is_(None),
            ).label("websocket_status"),
            self._latest_field_subquery(
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.created_at,
                WebSocketTestCaseExecution.created_at,
                WebSocketTestCaseExecution.scenario_run_id.is_(None),
            ).label("websocket_at"),
            self._latest_field_subquery(
                TestScenarioRun,
                TestScenarioRun.status,
                TestScenarioRun.started_at,
                TestScenarioRun.plan_run_id.is_(None),
            ).label("scenario_status"),
            self._latest_field_subquery(
                TestScenarioRun,
                TestScenarioRun.started_at,
                TestScenarioRun.started_at,
                TestScenarioRun.plan_run_id.is_(None),
            ).label("scenario_at"),
            self._latest_field_subquery(
                TestPlanRun,
                TestPlanRun.status,
                TestPlanRun.started_at,
                TestPlanRun.is_deleted.is_(False),
            ).label("plan_status"),
            self._latest_field_subquery(
                TestPlanRun,
                TestPlanRun.started_at,
                TestPlanRun.started_at,
                TestPlanRun.is_deleted.is_(False),
            ).label("plan_at"),
            self._latest_field_subquery(
                VisualFlowExecution,
                VisualFlowExecution.status,
                VisualFlowExecution.started_at,
            ).label("flow_status"),
            self._latest_field_subquery(
                VisualFlowExecution,
                VisualFlowExecution.started_at,
                VisualFlowExecution.started_at,
            ).label("flow_at"),
        ).where(Project.id.in_(project_ids))

        latest_by_project: dict[int, tuple[str | None, datetime | None]] = {}
        for row in self.db.execute(statement).all():
            candidates = [
                (row.http_status, row.http_at),
                (row.websocket_status, row.websocket_at),
                (row.scenario_status, row.scenario_at),
                (row.plan_status, row.plan_at),
                (row.flow_status, row.flow_at),
            ]
            valid_candidates = [candidate for candidate in candidates if candidate[1] is not None]
            if valid_candidates:
                latest_by_project[row.project_id] = max(valid_candidates, key=lambda item: item[1])
        return latest_by_project

    def _latest_field_subquery(self, model, field_column, time_column, *conditions):
        return (
            select(field_column)
            .select_from(model)
            .where(model.project_id == Project.id, *conditions)
            .order_by(time_column.desc())
            .limit(1)
            .correlate(Project)
            .scalar_subquery()
        )

    def _build_project_stats(self, project: Project) -> ProjectStatsRead:
        return self._project_stats_by_project([project.id])[project.id]

    def _build_environment_detail(
        self,
        environment: ProjectEnvironment,
        *,
        test_case_count: int | None = None,
    ) -> ProjectEnvironmentDetailRead:
        detail = ProjectEnvironmentDetailRead.model_validate(environment)
        for variable in detail.variables:
            if variable.is_secret:
                variable.value = "***"
        if test_case_count is None:
            test_case_count = self.project_repository.count_test_cases_by_environment(
                environment_id=environment.id,
            )
        detail.test_case_count = test_case_count
        return detail

    def _count(self, model, *conditions) -> int:
        statement = select(func.count()).select_from(model)
        if conditions:
            statement = statement.where(*conditions)
        return self.db.scalar(statement) or 0

    def _distinct_case_count(self, model, column, *conditions) -> int:
        statement = select(func.count(func.distinct(column))).select_from(model)
        if conditions:
            statement = statement.where(*conditions)
        return int(self.db.scalar(statement) or 0)

    def _latest_project_execution(self, project_id: int) -> tuple[str | None, datetime | None]:
        candidates: list[tuple[str, datetime]] = []
        queries = [
            select(TestCaseExecution.status, TestCaseExecution.created_at)
            .where(
                TestCaseExecution.project_id == project_id,
                TestCaseExecution.scenario_run_id.is_(None),
            )
            .order_by(TestCaseExecution.created_at.desc())
            .limit(1),
            select(WebSocketTestCaseExecution.status, WebSocketTestCaseExecution.created_at)
            .where(
                WebSocketTestCaseExecution.project_id == project_id,
                WebSocketTestCaseExecution.scenario_run_id.is_(None),
            )
            .order_by(WebSocketTestCaseExecution.created_at.desc())
            .limit(1),
            select(TestScenarioRun.status, TestScenarioRun.started_at)
            .where(
                TestScenarioRun.project_id == project_id,
                TestScenarioRun.plan_run_id.is_(None),
            )
            .order_by(TestScenarioRun.started_at.desc())
            .limit(1),
            select(VisualFlowExecution.status, VisualFlowExecution.started_at)
            .where(VisualFlowExecution.project_id == project_id)
            .order_by(VisualFlowExecution.started_at.desc())
            .limit(1),
            select(TestPlanRun.status, TestPlanRun.started_at)
            .where(
                TestPlanRun.project_id == project_id,
                TestPlanRun.is_deleted.is_(False),
            )
            .order_by(TestPlanRun.started_at.desc())
            .limit(1),
        ]
        for query in queries:
            row = self.db.execute(query).first()
            if row is not None and row[1] is not None:
                candidates.append((row[0], row[1]))
        if not candidates:
            return None, None
        return max(candidates, key=lambda item: item[1])

    def _latest_execution_candidates(self, project_id: int) -> list[dict]:
        specifications = [
            (
                "http_case",
                "case_executed",
                select(
                    TestCaseExecution.id,
                    TestCaseExecution.test_case_id,
                    TestCase.name,
                    TestCaseExecution.status,
                    TestCaseExecution.created_at,
                    TestCaseExecution.executed_by_id,
                )
                .outerjoin(TestCase, TestCase.id == TestCaseExecution.test_case_id)
                .where(
                    TestCaseExecution.project_id == project_id,
                    TestCaseExecution.scenario_run_id.is_(None),
                )
                .order_by(TestCaseExecution.created_at.desc())
                .limit(1),
            ),
            (
                "websocket_case",
                "case_executed",
                select(
                    WebSocketTestCaseExecution.id,
                    WebSocketTestCaseExecution.websocket_test_case_id,
                    WebSocketTestCase.name,
                    WebSocketTestCaseExecution.status,
                    WebSocketTestCaseExecution.created_at,
                    WebSocketTestCaseExecution.executed_by_id,
                )
                .outerjoin(
                    WebSocketTestCase,
                    WebSocketTestCase.id == WebSocketTestCaseExecution.websocket_test_case_id,
                )
                .where(
                    WebSocketTestCaseExecution.project_id == project_id,
                    WebSocketTestCaseExecution.scenario_run_id.is_(None),
                )
                .order_by(WebSocketTestCaseExecution.created_at.desc())
                .limit(1),
            ),
            (
                "scenario",
                "scenario_executed",
                select(
                    TestScenarioRun.id,
                    TestScenarioRun.scenario_id,
                    TestScenario.name,
                    TestScenarioRun.status,
                    TestScenarioRun.started_at,
                    TestScenarioRun.triggered_by_id,
                )
                .outerjoin(TestScenario, TestScenario.id == TestScenarioRun.scenario_id)
                .where(
                    TestScenarioRun.project_id == project_id,
                    TestScenarioRun.plan_run_id.is_(None),
                )
                .order_by(TestScenarioRun.started_at.desc())
                .limit(1),
            ),
            (
                "plan",
                "plan_executed",
                select(
                    TestPlanRun.id,
                    TestPlanRun.plan_id,
                    TestPlanRun.plan_name,
                    TestPlanRun.status,
                    TestPlanRun.started_at,
                    TestPlanRun.operator_id,
                )
                .where(
                    TestPlanRun.project_id == project_id,
                    TestPlanRun.is_deleted.is_(False),
                )
                .order_by(TestPlanRun.started_at.desc())
                .limit(1),
            ),
            (
                "flow",
                "flow_executed",
                select(
                    VisualFlowExecution.id,
                    VisualFlowExecution.flow_id,
                    VisualFlow.name,
                    VisualFlowExecution.status,
                    func.coalesce(VisualFlowExecution.started_at, VisualFlowExecution.created_at),
                    VisualFlowExecution.trigger_user_id,
                )
                .outerjoin(VisualFlow, VisualFlow.id == VisualFlowExecution.flow_id)
                .where(VisualFlowExecution.project_id == project_id)
                .order_by(func.coalesce(VisualFlowExecution.started_at, VisualFlowExecution.created_at).desc())
                .limit(1),
            ),
        ]
        candidates: list[dict] = []
        fallback_names = {
            "http_case": "未保存 HTTP 用例",
            "websocket_case": "未保存 WebSocket 用例",
            "scenario": "已删除场景",
            "plan": "已删除计划",
            "flow": "未保存流程",
        }
        for resource_type, activity_type, statement in specifications:
            row = self.db.execute(statement).first()
            if row is None or row[4] is None:
                continue
            candidates.append(
                {
                    "id": int(row[0]),
                    "resource_type": resource_type,
                    "activity_type": activity_type,
                    "resource_id": int(row[1]) if row[1] is not None else None,
                    "resource_name": row[2] or fallback_names[resource_type],
                    "status": str(row[3]),
                    "executed_at": row[4],
                    "operator_id": int(row[5]) if row[5] is not None else None,
                }
            )
        return candidates

    def _latest_project_execution_detail(self, project_id: int) -> ProjectLatestExecutionRead | None:
        candidates = self._latest_execution_candidates(project_id)
        if not candidates:
            return None
        latest = max(candidates, key=lambda item: item["executed_at"])
        return ProjectLatestExecutionRead(
            id=latest["id"],
            resource_type=latest["resource_type"],
            resource_id=latest["resource_id"],
            resource_name=latest["resource_name"],
            status=latest["status"],
            executed_at=latest["executed_at"],
        )

    def _project_activities(self, project: Project) -> list[ProjectActivityRead]:
        activities: list[ProjectActivityRead] = []
        for candidate in self._latest_execution_candidates(project.id):
            operator = self._get_user(candidate["operator_id"])
            status_label = self._status_label(candidate["status"]) or candidate["status"]
            activities.append(
                ProjectActivityRead(
                    id=f'{candidate["resource_type"]}_execution:{candidate["id"]}',
                    type=candidate["activity_type"],
                    title=f'{candidate["resource_name"]} 执行{status_label}',
                    operator_id=candidate["operator_id"],
                    operator_name=self._user_display_name(operator),
                    resource_type=candidate["resource_type"],
                    resource_id=candidate["resource_id"],
                    resource_name=candidate["resource_name"],
                    occurred_at=candidate["executed_at"],
                )
            )

        case_creation_specs = [
            ("http_case", TestCase),
            ("websocket_case", WebSocketTestCase),
        ]
        for resource_type, model in case_creation_specs:
            row = self.db.execute(
                select(model.id, model.name, model.created_by_id, model.created_at)
                .where(model.project_id == project.id)
                .order_by(model.created_at.desc())
                .limit(1)
            ).first()
            if row is None:
                continue
            operator = self._get_user(row[2])
            activities.append(
                ProjectActivityRead(
                    id=f"{resource_type}_created:{row[0]}",
                    type="case_created",
                    title=f"创建用例 {row[1]}",
                    operator_id=row[2],
                    operator_name=self._user_display_name(operator),
                    resource_type=resource_type,
                    resource_id=row[0],
                    resource_name=row[1],
                    occurred_at=row[3],
                )
            )

        defect = self.db.execute(
            select(Defect.id, Defect.title, Defect.reporter_id, Defect.created_at)
            .where(Defect.project_id == project.id)
            .order_by(Defect.created_at.desc())
            .limit(1)
        ).first()
        if defect is not None:
            reporter = self._get_user(defect[2])
            activities.append(
                ProjectActivityRead(
                    id=f"defect_created:{defect[0]}",
                    type="defect_created",
                    title=f"创建缺陷 {defect[1]}",
                    operator_id=defect[2],
                    operator_name=self._user_display_name(reporter),
                    resource_type="defect",
                    resource_id=defect[0],
                    resource_name=defect[1],
                    occurred_at=defect[3],
                )
            )

        activities.append(
            ProjectActivityRead(
                id=f"project_updated:{project.id}",
                type="project_updated",
                title=f"项目 {project.name} 已更新",
                resource_type="project",
                resource_id=project.id,
                resource_name=project.name,
                occurred_at=project.updated_at,
            )
        )
        return sorted(activities, key=lambda item: item.occurred_at, reverse=True)[:8]

    def _status_label(self, status_value: str | None) -> str | None:
        if status_value is None:
            return None
        return self.STATUS_LABELS.get(status_value, status_value)

    def _calculate_risk_score(
        self,
        *,
        api_case_count: int,
        pass_rate: int,
        run_count: int,
        defect_count: int,
        coverage_rate: int,
    ) -> int:
        if run_count == 0 and defect_count == 0 and api_case_count == 0:
            return 0
        score = 0
        if run_count:
            score += max(0, 100 - pass_rate)
        elif api_case_count:
            score += 20
        score += min(40, defect_count * 8)
        if coverage_rate < 80:
            score += min(20, 80 - coverage_rate)
        return min(100, score)

    def _risk_level(self, risk_score: int) -> str:
        if risk_score >= 70:
            return "high"
        if risk_score >= 40:
            return "medium"
        return "low"

    def _build_structured_recommendations(
        self,
        *,
        project_id: int,
        api_case_count: int,
        coverage_rate: int,
        open_defect_count: int,
        failed_execution_count: int,
        scenario_count: int,
        plan_count: int,
        flow_count: int,
    ) -> list[ProjectRecommendationRead]:
        recommendations: list[ProjectRecommendationRead] = []
        if api_case_count == 0:
            recommendations.append(
                ProjectRecommendationRead(
                    id=f"project:{project_id}:automation:no-api-cases",
                    type="automation",
                    title="先建立核心接口用例",
                    description="当前项目还没有 HTTP 或 WebSocket 用例，无法形成可执行的接口质量基线。",
                    severity="high",
                    action_type="create_api_case",
                )
            )
        elif coverage_rate < 80:
            recommendations.append(
                ProjectRecommendationRead(
                    id=f"project:{project_id}:coverage",
                    type="coverage",
                    title="补齐核心接口执行覆盖",
                    description=f"当前接口执行覆盖率为 {coverage_rate}%，建议优先执行尚无终态记录的接口用例。",
                    severity="high" if coverage_rate < 50 else "medium",
                    action_type="view_api_cases",
                )
            )
        if failed_execution_count:
            recommendations.append(
                ProjectRecommendationRead(
                    id=f"project:{project_id}:failure",
                    type="failure",
                    title="处理失败执行记录",
                    description=f"项目当前累计有 {failed_execution_count} 次失败执行，建议先从最近失败链路定位原因。",
                    severity="high",
                    action_type="view_execution_history",
                )
            )
        if open_defect_count:
            recommendations.append(
                ProjectRecommendationRead(
                    id=f"project:{project_id}:defect",
                    type="defect",
                    title="收敛未关闭缺陷",
                    description=f"当前仍有 {open_defect_count} 个未关闭缺陷，风险评分仅使用这些待处理缺陷。",
                    severity="high" if open_defect_count >= 5 else "medium",
                    action_type="view_defects",
                )
            )
        if api_case_count and scenario_count + plan_count + flow_count == 0:
            recommendations.append(
                ProjectRecommendationRead(
                    id=f"project:{project_id}:automation:no-orchestration",
                    type="automation",
                    title="建立自动化编排链路",
                    description="已有接口用例，但尚未建立场景、计划或可视化流程，建议补齐可重复回归的编排入口。",
                    severity="medium",
                    action_type="create_scenario",
                )
            )
        return recommendations[:4]

    def _build_structured_activity(self, *, last_run_at: datetime | None) -> list[ProjectActivityRead]:
        # List cards do not have enough context to identify a real resource or operator.
        # Structured activities are populated by the testing-overview detail endpoint.
        return []

    def _build_project_recommendations(
        self,
        *,
        api_case_count: int,
        coverage_rate: int,
        defect_count: int,
        pass_rate: int,
        run_count: int,
    ) -> list[str]:
        recommendations: list[str] = []
        if api_case_count and coverage_rate < 80:
            recommendations.append("补齐核心接口自动化覆盖率")
        if run_count and pass_rate < 100:
            recommendations.append("优先处理最近失败的用例")
        if defect_count:
            recommendations.append("优先处理最近发现的缺陷")
        return recommendations

    def _build_project_activity(self, *, last_run_at: datetime | None) -> list[str]:
        if last_run_at is None:
            return []
        return [f"最近运行于 {last_run_at:%Y-%m-%d %H:%M}"]

    def _get_user(self, user_id: int | None) -> User | None:
        if user_id is None:
            return None
        return self.db.get(User, user_id)

    def _user_display_name(self, user: User | None) -> str | None:
        if user is None:
            return None
        return user.username or user.account or f"用户{user.id}"
