from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.read_response_cache import read_response_cache
from app.core.response import success
from app.models.user import User
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("", summary="查询通知中心列表")
def list_notifications(
    project_id: int | None = None,
    unread_only: bool = False,
    notification_type: Annotated[str | None, Query(alias="type")] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = (
        "notifications",
        id(db.get_bind()),
        current_user.id,
        bool(current_user.is_admin),
        project_id,
        unread_only,
        notification_type or "",
    )

    def build_response():
        items = NotificationService(db).list_notifications(
            project_id=project_id,
            current_user=current_user,
            unread_only=unread_only,
            notification_type=notification_type,
        )
        return success(data=items)

    return read_response_cache.get_or_set(cache_key, build_response)


@router.post("/{notification_id}/read", summary="标记单条通知已读")
def mark_notification_read(
    notification_id: str,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = NotificationService(db).mark_read(
        notification_id=notification_id,
        project_id=project_id,
        current_user=current_user,
    )
    read_response_cache.clear_prefix(("notifications",))
    return success(data=result, message="ok")


@router.post("/read-all", summary="标记全部通知已读")
def mark_all_notifications_read(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = NotificationService(db).mark_all_read(project_id=project_id, current_user=current_user)
    read_response_cache.clear_prefix(("notifications",))
    return success(data=result, message="ok")
