from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.browser_capture import BrowserCaptureCreateRequest, BrowserCaptureEntryBatchRequest, BrowserCaptureEntryRead, BrowserCaptureEntryUpdateRequest, BrowserCaptureRead, BrowserCaptureUpdateRequest
from app.services.browser_capture_service import BrowserCaptureService

router = APIRouter()


@router.get("")
def list_captures(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=[BrowserCaptureRead.model_validate(item) for item in BrowserCaptureService(db).list_captures(project_id=project_id, current_user=current_user)])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_capture(project_id: int, payload: BrowserCaptureCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=BrowserCaptureRead.model_validate(BrowserCaptureService(db).create_capture(project_id=project_id, payload=payload, current_user=current_user)), message="采集批次创建成功")


@router.put("/{capture_id}")
def update_capture(project_id: int, capture_id: int, payload: BrowserCaptureUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=BrowserCaptureRead.model_validate(BrowserCaptureService(db).update_capture(project_id=project_id, capture_id=capture_id, payload=payload, current_user=current_user)), message="采集批次更新成功")


@router.delete("/{capture_id}")
def delete_capture(project_id: int, capture_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    BrowserCaptureService(db).delete_capture(project_id=project_id, capture_id=capture_id, current_user=current_user)
    return success(message="采集批次删除成功")


@router.get("/{capture_id}/entries")
def list_entries(project_id: int, capture_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=[BrowserCaptureEntryRead.model_validate(item) for item in BrowserCaptureService(db).list_entries(project_id=project_id, capture_id=capture_id, current_user=current_user)])


@router.post("/{capture_id}/entries/batch")
def upsert_entries(project_id: int, capture_id: int, payload: BrowserCaptureEntryBatchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=[BrowserCaptureEntryRead.model_validate(item) for item in BrowserCaptureService(db).upsert_entries(project_id=project_id, capture_id=capture_id, payload=payload, current_user=current_user)], message="采集草稿同步成功")


@router.put("/{capture_id}/entries/{entry_id}")
def update_entry(project_id: int, capture_id: int, entry_id: int, payload: BrowserCaptureEntryUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=BrowserCaptureEntryRead.model_validate(BrowserCaptureService(db).update_entry(project_id=project_id, capture_id=capture_id, entry_id=entry_id, payload=payload, current_user=current_user)), message="采集草稿更新成功")
