import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.defect import Defect
from app.models.notification import NotificationReadState
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.test_plan import TestPlanRun
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.notification import NotificationItemRead
from app.services.permission_service import PermissionService


logger = logging.getLogger(__name__)


def send_plan_run_notification(*, recipients: list[str], plan_name: str, status: str, run_id: int) -> None:
    if not recipients:
        return
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        logger.warning("Plan run %s notification skipped because SMTP is not configured", run_id)
        return

    message = EmailMessage()
    message["Subject"] = f"[Test Plan] {plan_name}: {status}"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message.set_content(f"Test plan '{plan_name}' finished with status '{status}'. Run ID: {run_id}.")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
        if settings.SMTP_USE_TLS:
            client.starttls()
        if settings.SMTP_USERNAME:
            client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        client.send_message(message)


class NotificationService:
    CLOSED_DEFECT_STATUSES = {"closed", "resolved", "done", "已关闭", "已解决"}
    FAILED_RUN_STATUSES = {"failed", "failure", "error"}
    ACTIVE_RUN_STATUSES = {"running", "retrying", "queued"}

    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)
        self.project_repository = ProjectRepository(db)

    def list_notifications(
        self,
        *,
        project_id: int | None,
        current_user: User,
        unread_only: bool = False,
        notification_type: str | None = None,
    ) -> list[NotificationItemRead]:
        items: list[NotificationItemRead] = []
        for visible_project_id in self._visible_project_ids(project_id=project_id, current_user=current_user):
            items.extend(self._collect_notifications(project_id=visible_project_id, current_user=current_user))
        if unread_only:
            items = [item for item in items if item.unread]
        if notification_type:
            items = [item for item in items if item.type == notification_type]
        return sorted(items, key=lambda item: item.occurred_at, reverse=True)[:50]

    def mark_read(
        self,
        *,
        notification_id: str,
        current_user: User,
        project_id: int | None = None,
    ) -> dict[str, object]:
        resolved_project_id = project_id or self._resolve_project_id(notification_id)
        self.permission_service.require_project_access(current_user, resolved_project_id)
        self._mark_one_read(
            notification_id=notification_id,
            project_id=resolved_project_id,
            current_user=current_user,
        )
        return {"updated": 1}

    def mark_all_read(self, *, project_id: int | None, current_user: User) -> dict[str, int]:
        updated_count = 0
        for visible_project_id in self._visible_project_ids(project_id=project_id, current_user=current_user):
            items = self._collect_notifications(project_id=visible_project_id, current_user=current_user)
            existing_read_ids = self._read_notification_ids(
                notification_ids=[item.notification_id for item in items],
                project_id=visible_project_id,
                current_user=current_user,
            )
            for item in items:
                if item.unread:
                    updated_count += 1
                if item.notification_id in existing_read_ids:
                    continue
                self.db.add(
                    NotificationReadState(
                        user_id=current_user.id,
                        project_id=visible_project_id,
                        notification_id=item.notification_id,
                    )
                )
                existing_read_ids.add(item.notification_id)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
        return {"updated": updated_count}

    def _visible_project_ids(self, *, project_id: int | None, current_user: User) -> list[int]:
        if project_id is not None:
            project = self.permission_service.require_project_access(current_user, project_id)
            return [project.id]
        projects = self.project_repository.list_visible_for_user(
            user_id=current_user.id,
            is_admin=current_user.is_admin,
        )
        return [project.id for project in projects]

    def _collect_notifications(self, *, project_id: int, current_user: User) -> list[NotificationItemRead]:
        items: list[NotificationItemRead] = []
        items.extend(self._defect_notifications(project_id=project_id, current_user=current_user))
        items.extend(self._scenario_run_notifications(project_id=project_id, current_user=current_user))
        items.extend(self._plan_run_notifications(project_id=project_id, current_user=current_user))
        return self._with_read_states(items, project_id=project_id, current_user=current_user)

    def _defect_notifications(self, *, project_id: int, current_user: User) -> list[NotificationItemRead]:
        statement = (
            select(
                Defect.id,
                Defect.title,
                Defect.status,
                Defect.urgency,
                Defect.updated_at,
                Defect.created_at,
            )
            .where(
                Defect.project_id == project_id,
                ~Defect.status.in_(self.CLOSED_DEFECT_STATUSES),
            )
            .order_by(Defect.updated_at.desc(), Defect.id.desc())
            .limit(20)
        )
        rows = self.db.execute(statement).all()
        return [
            NotificationItemRead(
                notification_id=f"defect:{row.id}",
                title="缺陷待处理",
                message=f"{row.title}（{row.status}）",
                source="缺陷中心",
                severity=self._severity_for_defect(row.urgency),
                type="alert",
                unread=True,
                occurred_at=row.updated_at or row.created_at or datetime.now(),
                action_label="查看缺陷",
            )
            for row in rows
        ]

    def _scenario_run_notifications(self, *, project_id: int, current_user: User) -> list[NotificationItemRead]:
        statuses = self.FAILED_RUN_STATUSES | self.ACTIVE_RUN_STATUSES
        statement = (
            select(
                TestScenarioRun.id,
                TestScenarioRun.scenario_id,
                TestScenarioRun.status,
                TestScenarioRun.finished_at,
                TestScenarioRun.started_at,
                TestScenarioRun.created_at,
                TestScenario.name.label("scenario_name"),
            )
            .outerjoin(TestScenario, TestScenario.id == TestScenarioRun.scenario_id)
            .where(
                TestScenarioRun.project_id == project_id,
                TestScenarioRun.status.in_(statuses),
            )
            .order_by(TestScenarioRun.started_at.desc(), TestScenarioRun.id.desc())
            .limit(20)
        )
        rows = self.db.execute(statement).all()
        return [
            NotificationItemRead(
                notification_id=f"scenario-run:{row.id}",
                title=self._scenario_run_title(row.status),
                message=f"{self._scenario_run_name(row)} 当前状态：{row.status}",
                source="执行中心",
                severity=self._severity_for_run(row.status),
                type="run",
                unread=row.status in self.FAILED_RUN_STATUSES,
                occurred_at=row.finished_at or row.started_at or row.created_at or datetime.now(),
                action_label="查看执行",
            )
            for row in rows
        ]

    def _plan_run_notifications(self, *, project_id: int, current_user: User) -> list[NotificationItemRead]:
        statement = (
            select(
                TestPlanRun.id,
                TestPlanRun.plan_name,
                TestPlanRun.status,
                TestPlanRun.finished_at,
                TestPlanRun.started_at,
                TestPlanRun.created_at,
            )
            .where(
                TestPlanRun.project_id == project_id,
                ~TestPlanRun.status.in_(self.ACTIVE_RUN_STATUSES),
            )
            .order_by(TestPlanRun.started_at.desc(), TestPlanRun.id.desc())
            .limit(10)
        )
        rows = self.db.execute(statement).all()
        return [
            NotificationItemRead(
                notification_id=f"plan-run:{row.id}",
                title=self._plan_run_title(row.status),
                message=f"{row.plan_name} 执行状态：{row.status}",
                source="测试计划",
                severity=self._severity_for_run(row.status),
                type="run",
                unread=row.status in self.FAILED_RUN_STATUSES,
                occurred_at=row.finished_at or row.started_at or row.created_at or datetime.now(),
                action_label="查看报告",
            )
            for row in rows
        ]

    def _with_read_states(
        self,
        items: list[NotificationItemRead],
        *,
        project_id: int,
        current_user: User,
    ) -> list[NotificationItemRead]:
        if not items:
            return items
        read_ids = self._read_notification_ids(
            notification_ids=[item.notification_id for item in items],
            project_id=project_id,
            current_user=current_user,
        )
        if not read_ids:
            return items
        return [
            item.model_copy(update={"unread": False})
            if item.notification_id in read_ids
            else item
            for item in items
        ]

    def _read_notification_ids(
        self,
        *,
        notification_ids: list[str],
        project_id: int,
        current_user: User,
    ) -> set[str]:
        unique_ids = list(dict.fromkeys(notification_ids))
        if not unique_ids:
            return set()
        rows = (
            self.db.query(NotificationReadState.notification_id)
            .filter(
                NotificationReadState.user_id == current_user.id,
                NotificationReadState.project_id == project_id,
                NotificationReadState.notification_id.in_(unique_ids),
            )
            .all()
        )
        return {str(row[0]) for row in rows}

    def _with_read_state(
        self,
        item: NotificationItemRead,
        *,
        project_id: int,
        current_user: User,
    ) -> NotificationItemRead:
        if not self._is_read(
            notification_id=item.notification_id,
            project_id=project_id,
            current_user=current_user,
        ):
            return item
        return item.model_copy(update={"unread": False})

    def _is_read(self, *, notification_id: str, project_id: int, current_user: User) -> bool:
        return (
            self.db.query(NotificationReadState.id)
            .filter(
                NotificationReadState.user_id == current_user.id,
                NotificationReadState.project_id == project_id,
                NotificationReadState.notification_id == notification_id,
            )
            .first()
            is not None
        )

    def _mark_one_read(
        self,
        *,
        notification_id: str,
        project_id: int,
        current_user: User,
        commit: bool = True,
    ) -> None:
        if self._is_read(notification_id=notification_id, project_id=project_id, current_user=current_user):
            return
        self.db.add(
            NotificationReadState(
                user_id=current_user.id,
                project_id=project_id,
                notification_id=notification_id,
            )
        )
        if not commit:
            return
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()

    def _resolve_project_id(self, notification_id: str) -> int:
        prefix, _, raw_id = notification_id.partition(":")
        if not raw_id.isdigit():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
        item_id = int(raw_id)

        if prefix == "defect":
            row = self.db.query(Defect.project_id).filter(Defect.id == item_id).first()
        elif prefix == "scenario-run":
            row = self.db.query(TestScenarioRun.project_id).filter(TestScenarioRun.id == item_id).first()
        elif prefix == "plan-run":
            row = self.db.query(TestPlanRun.project_id).filter(TestPlanRun.id == item_id).first()
        else:
            row = None
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
        return int(row[0])

    def _severity_for_defect(self, urgency: str) -> str:
        if urgency in {"紧急", "高", "P0", "P1"}:
            return "danger"
        if urgency in {"中", "P2"}:
            return "warning"
        return "info"

    def _severity_for_run(self, status_value: str) -> str:
        if status_value in self.FAILED_RUN_STATUSES:
            return "danger"
        if status_value == "passed":
            return "success"
        if status_value == "retrying":
            return "warning"
        return "info"

    def _scenario_run_title(self, status_value: str) -> str:
        if status_value in self.FAILED_RUN_STATUSES:
            return "场景执行失败"
        if status_value == "retrying":
            return "场景执行重试中"
        if status_value == "queued":
            return "场景执行排队中"
        return "场景执行中"

    def _plan_run_title(self, status_value: str) -> str:
        if status_value in self.FAILED_RUN_STATUSES:
            return "测试计划执行失败"
        if status_value == "passed":
            return "测试计划执行通过"
        return "测试计划执行完成"

    def _scenario_run_name(self, row) -> str:
        name = getattr(row, "scenario_name", None)
        if isinstance(name, str) and name.strip():
            return name
        return f"场景 {row.scenario_id or row.id}"
