from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.config import settings
from app.core.response import success
from app.models.user import User
from app.schemas.media import MediaObjectRead
from app.services.media_service import MediaService


router = APIRouter()


@router.post("/images", status_code=status.HTTP_201_CREATED, summary="上传缺陷图片")
def upload_image(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MediaService(db)
    media = service.upload_image(project_id=project_id, upload=file, current_user=current_user)
    return success(
        data=MediaObjectRead.model_validate(service.prepare_media_read(media)),
        message="图片上传成功",
    )


@router.get("/{media_id}/url", summary="刷新媒体临时访问地址")
def get_media_url(
    media_id: int,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = MediaService(db).get_download_url(
        project_id=project_id,
        media_id=media_id,
        current_user=current_user,
    )
    return success(data={"url": url, "expires_in": settings.MEDIA_PRESIGNED_URL_EXPIRE_SECONDS})


@router.delete("/{media_id}", summary="删除媒体对象")
def delete_media(
    media_id: int,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    MediaService(db).delete_media(
        project_id=project_id,
        media_id=media_id,
        current_user=current_user,
    )
    return success(message="媒体对象删除成功")
