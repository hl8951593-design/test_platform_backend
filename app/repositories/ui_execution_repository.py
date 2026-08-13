from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.desktop_device import DesktopDevice, DesktopDeviceProjectBinding
from app.models.ui_execution import (
    UiExecution,
    UiExecutionCommand,
    UiExecutionEvent,
    UiRuntimePatch,
    UiStepExecution,
)
from app.models.ui_test_case import UiTestCase


class UiExecutionRepository:
    ACTIVE_STATUSES = ("claimed", "launching", "running", "paused", "waiting_user")

    def __init__(self, db: Session):
        self.db = db

    def add(self, execution: UiExecution) -> UiExecution:
        self.db.add(execution)
        self.db.flush()
        return execution

    def get_by_client_request(
        self,
        *,
        project_id: int,
        trigger_user_id: int,
        client_request_id: str,
    ) -> UiExecution | None:
        return self.db.scalar(
            select(UiExecution).where(
                UiExecution.project_id == project_id,
                UiExecution.trigger_user_id == trigger_user_id,
                UiExecution.client_request_id == client_request_id,
            )
        )

    def get_by_public_id(
        self,
        execution_public_id: str,
        *,
        project_id: int | None = None,
    ) -> UiExecution | None:
        filters = [UiExecution.public_id == execution_public_id]
        if project_id is not None:
            filters.append(UiExecution.project_id == project_id)
        return self.db.scalar(
            select(UiExecution)
            .options(joinedload(UiExecution.ui_test_case))
            .where(*filters)
        )

    def get_detail_by_public_id(
        self,
        execution_public_id: str,
        *,
        project_id: int | None = None,
    ) -> UiExecution | None:
        filters = [UiExecution.public_id == execution_public_id]
        if project_id is not None:
            filters.append(UiExecution.project_id == project_id)
        return self.db.execute(
            select(UiExecution)
            .options(
                joinedload(UiExecution.project),
                joinedload(UiExecution.environment),
                joinedload(UiExecution.ui_test_case),
                joinedload(UiExecution.requested_device),
                joinedload(UiExecution.assigned_device),
                selectinload(UiExecution.step_executions),
                selectinload(UiExecution.runtime_patches).joinedload(
                    UiRuntimePatch.request_command
                ),
                selectinload(UiExecution.commands),
            )
            .where(*filters)
        ).unique().scalar_one_or_none()

    def get_for_update(self, execution_public_id: str) -> UiExecution | None:
        return self.db.scalar(
            select(UiExecution)
            .options(
                joinedload(UiExecution.project),
                joinedload(UiExecution.environment),
                joinedload(UiExecution.ui_test_case),
                joinedload(UiExecution.assigned_device),
                joinedload(UiExecution.requested_device),
            )
            .where(UiExecution.public_id == execution_public_id)
            .with_for_update()
        )

    def list_by_project(
        self,
        *,
        project_id: int,
        status: str | None,
        delivery_status: str | None,
        attention_only: bool,
        assigned_device_public_id: str | None,
        environment_id: int | None,
        source: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[UiExecution], int, dict[str, int]]:
        filters = [UiExecution.project_id == project_id]
        if status:
            filters.append(UiExecution.status == status)
        if delivery_status:
            filters.append(UiExecution.delivery_status == delivery_status)
        if attention_only:
            filters.append(UiExecution.attention_reason.is_not(None))
        if assigned_device_public_id:
            filters.append(
                UiExecution.assigned_device.has(
                    DesktopDevice.public_id == assigned_device_public_id
                )
            )
        if environment_id:
            filters.append(UiExecution.environment_id == environment_id)
        if source:
            filters.append(UiExecution.source == source)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    UiExecution.public_id.ilike(pattern),
                    UiExecution.ui_test_case.has(UiTestCase.name.ilike(pattern)),
                )
            )

        statement = (
            select(UiExecution, func.count().over().label("filtered_total"))
            .options(
                joinedload(UiExecution.project),
                joinedload(UiExecution.environment),
                joinedload(UiExecution.ui_test_case),
                joinedload(UiExecution.assigned_device),
                joinedload(UiExecution.requested_device),
            )
            .where(*filters)
            .order_by(UiExecution.updated_at.desc(), UiExecution.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = self.db.execute(statement).unique().all()
        items = [row[0] for row in rows]
        if rows:
            total = int(rows[0].filtered_total or 0)
        elif page > 1:
            total = int(
                self.db.scalar(
                    select(func.count()).select_from(UiExecution).where(*filters)
                )
                or 0
            )
        else:
            total = 0

        facet_counts = self.db.execute(
            select(
                func.sum(
                    case(
                        (UiExecution.status.in_(("queued", "assigned")), 1),
                        else_=0,
                    )
                ).label("queued"),
                func.sum(
                    case(
                        (UiExecution.status.in_(self.ACTIVE_STATUSES), 1),
                        else_=0,
                    )
                ).label("running"),
                func.sum(
                    case((UiExecution.status == "waiting_user", 1), else_=0)
                ).label("waiting_user"),
                func.sum(
                    case((UiExecution.delivery_status == "failed", 1), else_=0)
                ).label("delivery_failed"),
            ).where(UiExecution.project_id == project_id)
        ).one()
        facets = {
            "queued": int(facet_counts.queued or 0),
            "running": int(facet_counts.running or 0),
            "waiting_user": int(facet_counts.waiting_user or 0),
            "delivery_failed": int(facet_counts.delivery_failed or 0),
        }
        return items, total, facets

    def list_available_for_device(
        self,
        *,
        device_id: int,
        active_count: int,
        limit: int,
    ) -> tuple[list[UiExecution], int]:
        filters = [
            UiExecution.status.in_(("queued", "assigned")),
            or_(
                UiExecution.requested_device_id.is_(None),
                UiExecution.requested_device_id == device_id,
            ),
            or_(
                UiExecution.assigned_device_id.is_(None),
                UiExecution.assigned_device_id == device_id,
            ),
            DesktopDeviceProjectBinding.device_id == device_id,
            DesktopDeviceProjectBinding.enabled.is_(True),
            DesktopDeviceProjectBinding.accepting_jobs.is_(True),
            DesktopDeviceProjectBinding.concurrency_limit > active_count,
        ]
        statement = (
            select(UiExecution, func.count().over().label("filtered_total"))
            .join(
                DesktopDeviceProjectBinding,
                DesktopDeviceProjectBinding.project_id == UiExecution.project_id,
            )
            .where(*filters)
            .options(
                joinedload(UiExecution.project),
                joinedload(UiExecution.environment),
                joinedload(UiExecution.ui_test_case),
                joinedload(UiExecution.assigned_device),
                joinedload(UiExecution.requested_device),
            )
            .order_by(UiExecution.created_at.asc(), UiExecution.id.asc())
            .limit(limit)
        )
        rows = self.db.execute(statement).unique().all()
        items = [row[0] for row in rows]
        total = int(rows[0].filtered_total or 0) if rows else 0
        return items, total

    def get_available_requested_device(
        self,
        *,
        device_public_id: str,
        project_id: int,
    ) -> DesktopDevice | None:
        return self.db.scalar(
            select(DesktopDevice)
            .join(
                DesktopDeviceProjectBinding,
                DesktopDeviceProjectBinding.device_id == DesktopDevice.id,
            )
            .where(
                DesktopDevice.public_id == device_public_id,
                DesktopDevice.registration_status == "active",
                DesktopDevice.accepting_jobs.is_(True),
                DesktopDeviceProjectBinding.project_id == project_id,
                DesktopDeviceProjectBinding.enabled.is_(True),
                DesktopDeviceProjectBinding.accepting_jobs.is_(True),
            )
        )

    def get_project_binding(
        self,
        *,
        device_id: int,
        project_id: int,
    ) -> DesktopDeviceProjectBinding | None:
        return self.db.scalar(
            select(DesktopDeviceProjectBinding).where(
                DesktopDeviceProjectBinding.device_id == device_id,
                DesktopDeviceProjectBinding.project_id == project_id,
            )
        )

    def count_active_for_device(self, device_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(UiExecution)
                .where(
                    UiExecution.assigned_device_id == device_id,
                    UiExecution.status.in_(self.ACTIVE_STATUSES),
                )
            )
            or 0
        )

    def get_event_by_identity(
        self,
        *,
        execution_id: int,
        client_event_id: str,
        client_sequence: int,
    ) -> tuple[UiExecutionEvent | None, UiExecutionEvent | None]:
        by_id = self.db.scalar(
            select(UiExecutionEvent).where(
                UiExecutionEvent.ui_execution_id == execution_id,
                UiExecutionEvent.client_event_id == client_event_id,
            )
        )
        by_sequence = self.db.scalar(
            select(UiExecutionEvent).where(
                UiExecutionEvent.ui_execution_id == execution_id,
                UiExecutionEvent.client_sequence == client_sequence,
            )
        )
        return by_id, by_sequence

    def add_event(self, event: UiExecutionEvent) -> UiExecutionEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(
        self,
        *,
        execution_id: int,
        after_sequence: int,
        limit: int,
    ) -> list[UiExecutionEvent]:
        return list(
            self.db.scalars(
                select(UiExecutionEvent)
                .where(
                    UiExecutionEvent.ui_execution_id == execution_id,
                    UiExecutionEvent.client_sequence > after_sequence,
                )
                .order_by(UiExecutionEvent.client_sequence.asc())
                .limit(limit)
            ).all()
        )

    def get_step(
        self,
        *,
        execution_id: int,
        step_id: str,
        attempt: int,
    ) -> UiStepExecution | None:
        return self.db.scalar(
            select(UiStepExecution).where(
                UiStepExecution.ui_execution_id == execution_id,
                UiStepExecution.step_id == step_id,
                UiStepExecution.attempt == attempt,
            )
        )

    def add_step(self, step: UiStepExecution) -> UiStepExecution:
        self.db.add(step)
        self.db.flush()
        return step

    def list_steps(self, execution_id: int) -> list[UiStepExecution]:
        return list(
            self.db.scalars(
                select(UiStepExecution)
                .where(UiStepExecution.ui_execution_id == execution_id)
                .order_by(
                    UiStepExecution.step_index.asc(),
                    UiStepExecution.attempt.asc(),
                )
            ).all()
        )

    def add_patch(self, patch: UiRuntimePatch) -> UiRuntimePatch:
        self.db.add(patch)
        self.db.flush()
        return patch

    def list_patches(self, execution_id: int) -> list[UiRuntimePatch]:
        return list(
            self.db.scalars(
                select(UiRuntimePatch)
                .where(UiRuntimePatch.ui_execution_id == execution_id)
                .order_by(UiRuntimePatch.id.asc())
            ).all()
        )

    def get_patch_by_request_command(
        self,
        *,
        execution_id: int,
        request_command_id: int,
    ) -> UiRuntimePatch | None:
        return self.db.scalar(
            select(UiRuntimePatch).where(
                UiRuntimePatch.ui_execution_id == execution_id,
                UiRuntimePatch.request_command_id == request_command_id,
            )
        )

    def add_command(self, command: UiExecutionCommand) -> UiExecutionCommand:
        self.db.add(command)
        self.db.flush()
        return command

    def get_command(self, *, execution_id: int, command_public_id: str) -> UiExecutionCommand | None:
        return self.db.scalar(
            select(UiExecutionCommand).where(
                UiExecutionCommand.ui_execution_id == execution_id,
                UiExecutionCommand.public_id == command_public_id,
            )
        )

    def get_command_by_public_id(self, command_public_id: str) -> UiExecutionCommand | None:
        return self.db.scalar(
            select(UiExecutionCommand).where(
                UiExecutionCommand.public_id == command_public_id
            )
        )

    def list_deliverable_commands(
        self,
        *,
        execution_id: int,
        now: datetime,
    ) -> list[UiExecutionCommand]:
        commands = list(
            self.db.scalars(
                select(UiExecutionCommand)
                .where(
                    UiExecutionCommand.ui_execution_id == execution_id,
                    UiExecutionCommand.status.in_(("pending", "delivered")),
                )
                .order_by(UiExecutionCommand.id.asc())
            ).all()
        )
        for command in commands:
            if command.expires_at is not None and command.expires_at <= now:
                command.status = "expired"
        return [command for command in commands if command.status != "expired"]

    def list_expired_active(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[UiExecution]:
        statement = (
            select(UiExecution)
            .options(joinedload(UiExecution.ui_test_case))
            .where(
                UiExecution.status.in_(self.ACTIVE_STATUSES),
                UiExecution.lease_expires_at.is_not(None),
                UiExecution.lease_expires_at <= now,
            )
            .order_by(UiExecution.lease_expires_at.asc(), UiExecution.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self.db.scalars(statement).unique().all())
