from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.browser_capture import BrowserCapture, BrowserCaptureEntry
from app.models.project import ProjectEnvironment
from app.models.user import User
from app.schemas.browser_capture import BrowserCaptureCreateRequest, BrowserCaptureEntryBatchRequest, BrowserCaptureEntryUpdateRequest, BrowserCaptureUpdateRequest
from app.services.permission_service import PermissionService


class BrowserCaptureService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_captures(self, *, project_id: int, current_user: User):
        self._require_view(project_id, current_user)
        return list(self.db.scalars(select(BrowserCapture).where(
            BrowserCapture.project_id == project_id, BrowserCapture.is_deleted.is_(False)
        ).order_by(BrowserCapture.id.desc())).all())

    def create_capture(self, *, project_id: int, payload: BrowserCaptureCreateRequest, current_user: User):
        self._require_manage(project_id, current_user)
        self._require_environment(project_id, payload.environment_id)
        capture = BrowserCapture(project_id=project_id, environment_id=payload.environment_id, name=payload.name.strip(),
                                 source_url=payload.source_url, created_by_id=current_user.id)
        self.db.add(capture)
        self.db.commit()
        self.db.refresh(capture)
        return capture

    def update_capture(self, *, project_id: int, capture_id: int, payload: BrowserCaptureUpdateRequest, current_user: User):
        self._require_manage(project_id, current_user)
        capture = self._capture_or_404(project_id, capture_id)
        if payload.name is not None:
            capture.name = payload.name.strip()
        if payload.status is not None:
            capture.status = payload.status
        self.db.commit()
        self.db.refresh(capture)
        return capture

    def delete_capture(self, *, project_id: int, capture_id: int, current_user: User):
        self._require_manage(project_id, current_user)
        capture = self._capture_or_404(project_id, capture_id)
        capture.is_deleted = True
        self.db.commit()

    def list_entries(self, *, project_id: int, capture_id: int, current_user: User):
        self._require_view(project_id, current_user)
        self._capture_or_404(project_id, capture_id)
        return list(self.db.scalars(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.project_id == project_id, BrowserCaptureEntry.capture_id == capture_id
        ).order_by(BrowserCaptureEntry.id.desc())).all())

    def get_entry(self, *, project_id: int, capture_id: int, entry_id: int, current_user: User, manage: bool = False):
        (self._require_manage if manage else self._require_view)(project_id, current_user)
        self._capture_or_404(project_id, capture_id)
        entry = self.db.scalar(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.project_id == project_id, BrowserCaptureEntry.capture_id == capture_id,
            BrowserCaptureEntry.id == entry_id,
        ))
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集草稿不存在")
        return entry

    def upsert_entries(self, *, project_id: int, capture_id: int, payload: BrowserCaptureEntryBatchRequest, current_user: User):
        self._require_manage(project_id, current_user)
        capture = self._capture_or_404(project_id, capture_id)
        existing = {item.client_entry_id: item for item in self.db.scalars(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.capture_id == capture_id,
            BrowserCaptureEntry.client_entry_id.in_([entry.client_entry_id for entry in payload.entries]),
        )).all()}
        result = []
        for entry_payload in payload.entries:
            values = entry_payload.model_dump()
            entry = existing.get(entry_payload.client_entry_id)
            if entry is None:
                entry = BrowserCaptureEntry(capture_id=capture_id, project_id=project_id, **values)
                self.db.add(entry)
            else:
                for key, value in values.items():
                    setattr(entry, key, value)
            result.append(entry)
        capture.status = "reviewing"
        self.db.commit()
        for entry in result:
            self.db.refresh(entry)
        return result

    def update_entry(self, *, project_id: int, capture_id: int, entry_id: int, payload: BrowserCaptureEntryUpdateRequest, current_user: User):
        entry = self.get_entry(project_id=project_id, capture_id=capture_id, entry_id=entry_id, current_user=current_user, manage=True)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entry, key, value)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def _capture_or_404(self, project_id: int, capture_id: int):
        capture = self.db.scalar(select(BrowserCapture).where(
            BrowserCapture.id == capture_id, BrowserCapture.project_id == project_id, BrowserCapture.is_deleted.is_(False)
        ))
        if capture is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集批次不存在")
        return capture

    def _require_environment(self, project_id: int, environment_id: int):
        if self.db.scalar(select(ProjectEnvironment.id).where(
            ProjectEnvironment.id == environment_id, ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        )) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

    def _require_view(self, project_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.VIEW_CASE.value)

    def _require_manage(self, project_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
