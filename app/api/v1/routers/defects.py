from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.defect import (
    DefectCreateRequest,
    DefectRead,
    DefectStatus,
    DefectStatusUpdateRequest,
    DefectUpdateRequest,
    DefectUrgency,
)
from app.services.defect_service import DefectService

router = APIRouter()


@router.get("", summary="查询项目缺陷列表")
def list_defects(
    project_id: int,
    keyword: str | None = None,
    status: DefectStatus | None = None,
    urgency: DefectUrgency | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DefectService(db).list_defects(
        project_id=project_id,
        current_user=current_user,
        keyword=keyword,
        status=status,
        urgency=urgency,
        page=page,
        page_size=page_size,
    )
    result["items"] = [DefectRead.model_validate(item) for item in result["items"]]
    return success(data=result)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建项目缺陷")
def create_defect(
    project_id: int,
    payload: DefectCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    defect = DefectService(db).create_defect(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=DefectRead.model_validate(defect), message="缺陷创建成功")


@router.get("/{defect_id}", summary="查询缺陷详情")
def get_defect(
    project_id: int,
    defect_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    defect = DefectService(db).get_defect(
        project_id=project_id,
        defect_id=defect_id,
        current_user=current_user,
    )
    return success(data=DefectRead.model_validate(defect))


@router.put("/{defect_id}", summary="更新缺陷")
def update_defect(
    project_id: int,
    defect_id: int,
    payload: DefectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    defect = DefectService(db).update_defect(
        project_id=project_id,
        defect_id=defect_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=DefectRead.model_validate(defect), message="缺陷更新成功")


@router.delete("/{defect_id}", summary="删除缺陷")
def delete_defect(
    project_id: int,
    defect_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    DefectService(db).delete_defect(
        project_id=project_id,
        defect_id=defect_id,
        current_user=current_user,
    )
    return success(message="缺陷删除成功")


@router.put("/{defect_id}/status", summary="推进缺陷状态")
def transition_defect_status(
    project_id: int,
    defect_id: int,
    payload: DefectStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    defect = DefectService(db).transition_status(
        project_id=project_id,
        defect_id=defect_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=DefectRead.model_validate(defect), message="缺陷状态已更新")
