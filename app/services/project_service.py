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
    ProjectMemberRead,
    ProjectMemberSummaryRead,
    ProjectRead,
    ProjectStatsRead,
    ProjectUpdateRequest,
    TestCaseEnvironmentBindRequest,
)
from app.services.permission_service import PermissionService
from app.services.object_storage_service import ObjectStorageService


class ProjectService:
    PASSED_STATUSES = {"passed", "success", "completed"}
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

    def update(self, project_id: int, payload: ProjectUpdateRequest, current_user: User) -> Project:
        project = self.permission_service.require_project_creator_or_admin(current_user, project_id)
        return self.project_repository.update(
            project=project,
            name=payload.name,
            description=payload.description,
        )

    def delete(self, project_id: int, current_user: User) -> None:
        project = self.permission_service.require_project_creator_or_admin(current_user, project_id)
        for media in self.media_repository.list_by_project(project_id):
            self.object_storage.delete(bucket=media.bucket, object_key=media.object_key)
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
        scenario_count = self._project_count_subquery(TestScenario, TestScenario.is_deleted.is_(False))
        plan_count = self._project_count_subquery(TestPlan, TestPlan.is_deleted.is_(False))
        defect_count = self._project_count_subquery(Defect)
        http_run_count = self._project_count_subquery(TestCaseExecution)
        websocket_run_count = self._project_count_subquery(WebSocketTestCaseExecution)
        scenario_run_count = self._project_count_subquery(TestScenarioRun)
        plan_run_count = self._project_count_subquery(TestPlanRun, TestPlanRun.is_deleted.is_(False))
        http_passed_count = self._project_count_subquery(
            TestCaseExecution,
            TestCaseExecution.status.in_(self.PASSED_STATUSES),
        )
        websocket_passed_count = self._project_count_subquery(
            WebSocketTestCaseExecution,
            WebSocketTestCaseExecution.status.in_(self.PASSED_STATUSES),
        )
        scenario_passed_count = self._project_count_subquery(
            TestScenarioRun,
            TestScenarioRun.status.in_(self.PASSED_STATUSES),
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
            scenario_count.label("scenario_count"),
            plan_count.label("plan_count"),
            defect_count.label("defect_count"),
            (http_run_count + websocket_run_count + scenario_run_count + plan_run_count).label("run_count"),
            (http_passed_count + websocket_passed_count + scenario_passed_count + plan_passed_count).label(
                "passed_count"
            ),
        ).where(Project.id.in_(project_ids))
        stats_rows = {row.project_id: row for row in self.db.execute(stats_statement).all()}
        latest_executions = self._latest_execution_by_project(project_ids)

        stats_by_project: dict[int, ProjectStatsRead] = {}
        for project_id in project_ids:
            row = stats_rows.get(project_id)
            http_case_total = int(row.http_case_count or 0) if row is not None else 0
            websocket_case_total = int(row.websocket_case_count or 0) if row is not None else 0
            api_case_count = http_case_total + websocket_case_total
            scenario_total = int(row.scenario_count or 0) if row is not None else 0
            plan_total = int(row.plan_count or 0) if row is not None else 0
            defect_total = int(row.defect_count or 0) if row is not None else 0
            run_count = int(row.run_count or 0) if row is not None else 0
            passed_count = int(row.passed_count or 0) if row is not None else 0
            pass_rate = round(passed_count / run_count * 100) if run_count else 0
            latest_status, last_run_at = latest_executions.get(project_id, (None, None))
            coverage_rate = min(100, round(scenario_total / api_case_count * 100)) if api_case_count else 0
            automation_rate = 100 if api_case_count and scenario_total else 0
            risk_score = self._calculate_risk_score(
                pass_rate=pass_rate,
                run_count=run_count,
                defect_count=defect_total,
                coverage_rate=coverage_rate,
            )
            stats_by_project[project_id] = ProjectStatsRead(
                api_case_count=api_case_count,
                http_test_case_count=http_case_total,
                websocket_test_case_count=websocket_case_total,
                test_case_count=api_case_count,
                scenario_count=scenario_total,
                plan_count=plan_total,
                run_count=run_count,
                pass_rate=pass_rate,
                coverage_rate=coverage_rate,
                automation_rate=automation_rate,
                defect_count=defect_total,
                last_run_at=last_run_at,
                last_execution_status=self._status_label(latest_status),
                risk_score=risk_score,
                ai_recommendations=self._build_project_recommendations(
                    api_case_count=api_case_count,
                    coverage_rate=coverage_rate,
                    defect_count=defect_total,
                    pass_rate=pass_rate,
                    run_count=run_count,
                ),
                team_activity=self._build_project_activity(last_run_at=last_run_at),
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
                TestCaseExecution.project_id.in_(project_ids)
            ),
            select(
                WebSocketTestCaseExecution.project_id.label("project_id"),
                WebSocketTestCaseExecution.status.label("status"),
            ).where(WebSocketTestCaseExecution.project_id.in_(project_ids)),
            select(TestScenarioRun.project_id.label("project_id"), TestScenarioRun.status.label("status")).where(
                TestScenarioRun.project_id.in_(project_ids)
            ),
            select(TestPlanRun.project_id.label("project_id"), TestPlanRun.status.label("status")).where(
                TestPlanRun.project_id.in_(project_ids),
                TestPlanRun.is_deleted.is_(False),
            ),
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
            self._latest_field_subquery(TestCaseExecution, TestCaseExecution.status, TestCaseExecution.created_at).label(
                "http_status"
            ),
            self._latest_field_subquery(
                TestCaseExecution,
                TestCaseExecution.created_at,
                TestCaseExecution.created_at,
            ).label("http_at"),
            self._latest_field_subquery(
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.status,
                WebSocketTestCaseExecution.created_at,
            ).label("websocket_status"),
            self._latest_field_subquery(
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.created_at,
                WebSocketTestCaseExecution.created_at,
            ).label("websocket_at"),
            self._latest_field_subquery(
                TestScenarioRun,
                TestScenarioRun.status,
                TestScenarioRun.started_at,
            ).label("scenario_status"),
            self._latest_field_subquery(
                TestScenarioRun,
                TestScenarioRun.started_at,
                TestScenarioRun.started_at,
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
        ).where(Project.id.in_(project_ids))

        latest_by_project: dict[int, tuple[str | None, datetime | None]] = {}
        for row in self.db.execute(statement).all():
            candidates = [
                (row.http_status, row.http_at),
                (row.websocket_status, row.websocket_at),
                (row.scenario_status, row.scenario_at),
                (row.plan_status, row.plan_at),
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
        project_id = project.id
        http_case_count = self._count(TestCase, TestCase.project_id == project_id)
        websocket_case_count = self._count(WebSocketTestCase, WebSocketTestCase.project_id == project_id)
        api_case_count = http_case_count + websocket_case_count
        scenario_count = self._count(
            TestScenario,
            TestScenario.project_id == project_id,
            TestScenario.is_deleted.is_(False),
        )
        plan_count = self._count(
            TestPlan,
            TestPlan.project_id == project_id,
            TestPlan.is_deleted.is_(False),
        )
        defect_count = self._count(Defect, Defect.project_id == project_id)

        http_run_count = self._count(TestCaseExecution, TestCaseExecution.project_id == project_id)
        websocket_run_count = self._count(
            WebSocketTestCaseExecution,
            WebSocketTestCaseExecution.project_id == project_id,
        )
        scenario_run_count = self._count(TestScenarioRun, TestScenarioRun.project_id == project_id)
        plan_run_count = self._count(
            TestPlanRun,
            TestPlanRun.project_id == project_id,
            TestPlanRun.is_deleted.is_(False),
        )
        run_count = http_run_count + websocket_run_count + scenario_run_count + plan_run_count

        passed_count = (
            self._count(
                TestCaseExecution,
                TestCaseExecution.project_id == project_id,
                TestCaseExecution.status.in_(self.PASSED_STATUSES),
            )
            + self._count(
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.project_id == project_id,
                WebSocketTestCaseExecution.status.in_(self.PASSED_STATUSES),
            )
            + self._count(
                TestScenarioRun,
                TestScenarioRun.project_id == project_id,
                TestScenarioRun.status.in_(self.PASSED_STATUSES),
            )
            + self._count(
                TestPlanRun,
                TestPlanRun.project_id == project_id,
                TestPlanRun.is_deleted.is_(False),
                TestPlanRun.status.in_(self.PASSED_STATUSES),
            )
        )
        pass_rate = round(passed_count / run_count * 100) if run_count else 0
        latest_status, last_run_at = self._latest_project_execution(project_id)
        coverage_rate = min(100, round(scenario_count / api_case_count * 100)) if api_case_count else 0
        automation_rate = 100 if api_case_count and scenario_count else 0
        risk_score = self._calculate_risk_score(
            pass_rate=pass_rate,
            run_count=run_count,
            defect_count=defect_count,
            coverage_rate=coverage_rate,
        )

        return ProjectStatsRead(
            api_case_count=api_case_count,
            http_test_case_count=http_case_count,
            websocket_test_case_count=websocket_case_count,
            test_case_count=api_case_count,
            scenario_count=scenario_count,
            plan_count=plan_count,
            run_count=run_count,
            pass_rate=pass_rate,
            coverage_rate=coverage_rate,
            automation_rate=automation_rate,
            defect_count=defect_count,
            last_run_at=last_run_at,
            last_execution_status=self._status_label(latest_status),
            risk_score=risk_score,
            ai_recommendations=self._build_project_recommendations(
                api_case_count=api_case_count,
                coverage_rate=coverage_rate,
                defect_count=defect_count,
                pass_rate=pass_rate,
                run_count=run_count,
            ),
            team_activity=self._build_project_activity(last_run_at=last_run_at),
        )

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

    def _latest_project_execution(self, project_id: int) -> tuple[str | None, datetime | None]:
        candidates: list[tuple[str, datetime]] = []
        queries = [
            select(TestCaseExecution.status, TestCaseExecution.created_at)
            .where(TestCaseExecution.project_id == project_id)
            .order_by(TestCaseExecution.created_at.desc())
            .limit(1),
            select(WebSocketTestCaseExecution.status, WebSocketTestCaseExecution.created_at)
            .where(WebSocketTestCaseExecution.project_id == project_id)
            .order_by(WebSocketTestCaseExecution.created_at.desc())
            .limit(1),
            select(TestScenarioRun.status, TestScenarioRun.started_at)
            .where(TestScenarioRun.project_id == project_id)
            .order_by(TestScenarioRun.started_at.desc())
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

    def _status_label(self, status_value: str | None) -> str | None:
        if status_value is None:
            return None
        return self.STATUS_LABELS.get(status_value, status_value)

    def _calculate_risk_score(
        self,
        *,
        pass_rate: int,
        run_count: int,
        defect_count: int,
        coverage_rate: int,
    ) -> int:
        if run_count == 0 and defect_count == 0:
            return 0
        score = 0
        if run_count:
            score += max(0, 100 - pass_rate)
        score += min(40, defect_count * 8)
        if coverage_rate < 80:
            score += min(20, 80 - coverage_rate)
        return min(100, score)

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
