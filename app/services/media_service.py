from pathlib import Path
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ProjectPermission
from app.models.defect import Defect
from app.models.media import MediaObject
from app.models.user import User
from app.repositories.media_repository import MediaRepository
from app.services.object_storage_service import ObjectStorageService
from app.services.permission_service import PermissionService


IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class MediaService:
    def __init__(self, db: Session, storage: ObjectStorageService | None = None):
        self.db = db
        self.repository = MediaRepository(db)
        self.permission_service = PermissionService(db)
        self.storage = storage or ObjectStorageService()

    def upload_image(self, *, project_id: int, upload: UploadFile, current_user: User) -> MediaObject:
        can_create = self.permission_service.has_project_permission(
            current_user, project_id, ProjectPermission.CREATE_DEFECT.value
        )
        can_update = self.permission_service.has_project_permission(
            current_user, project_id, ProjectPermission.UPDATE_DEFECT.value
        )
        if not can_create and not can_update:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无媒体上传权限")
        content_type = (upload.content_type or "").lower()
        self._validate_image(upload, content_type)
        size = self._file_size(upload)
        object_key = (
            f"projects/{project_id}/defects/"
            f"{uuid.uuid4().hex}{IMAGE_EXTENSIONS[content_type]}"
        )
        upload.file.seek(0)
        etag = self.storage.upload(
            fileobj=upload.file,
            object_key=object_key,
            content_type=content_type,
        )
        try:
            return self.repository.create(
                project_id=project_id,
                owner_id=current_user.id,
                bucket=settings.MINIO_BUCKET,
                object_key=object_key,
                original_filename=self._safe_filename(upload.filename),
                content_type=content_type,
                size_bytes=size,
                etag=etag,
            )
        except Exception:
            self.storage.delete(bucket=settings.MINIO_BUCKET, object_key=object_key)
            raise

    def delete_media(self, *, project_id: int, media_id: int, current_user: User) -> None:
        media = self._get_or_404(project_id=project_id, media_id=media_id)
        can_update = self.permission_service.has_project_permission(
            current_user, project_id, ProjectPermission.UPDATE_DEFECT.value
        )
        if media.owner_id != current_user.id and not can_update:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无媒体删除权限")
        self.storage.delete(bucket=media.bucket, object_key=media.object_key)
        self.repository.delete(media)

    def get_download_url(self, *, project_id: int, media_id: int, current_user: User) -> str:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.VIEW_DEFECT.value
        )
        media = self._get_or_404(project_id=project_id, media_id=media_id)
        return self.storage.presigned_get_url(bucket=media.bucket, object_key=media.object_key)

    def resolve_pending_attachments(
        self,
        *,
        project_id: int,
        media_ids: list[int],
        current_user: User,
        defect_id: int | None = None,
    ) -> list[MediaObject]:
        unique_ids = list(dict.fromkeys(media_ids))
        attachments = self.repository.list_by_ids(unique_ids)
        if len(attachments) != len(unique_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="媒体对象不存在")
        for media in attachments:
            if media.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="媒体对象不属于当前项目")
            if media.owner_id != current_user.id and media.defect_id != defect_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能绑定其他用户的媒体对象")
            if media.defect_id is not None and media.defect_id != defect_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="媒体对象已绑定其他缺陷")
        return attachments

    def attach_download_urls(self, defect: Defect) -> Defect:
        for media in getattr(defect, "attachments", ()):
            media.download_url = self.storage.presigned_get_url(
                bucket=media.bucket,
                object_key=media.object_key,
            )
        return defect

    def prepare_media_read(self, media: MediaObject) -> MediaObject:
        media.download_url = self.storage.presigned_get_url(
            bucket=media.bucket,
            object_key=media.object_key,
        )
        return media

    def _get_or_404(self, *, project_id: int, media_id: int) -> MediaObject:
        media = self.repository.get_by_id(project_id=project_id, media_id=media_id)
        if media is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="媒体对象不存在")
        return media

    @staticmethod
    def _validate_image(upload: UploadFile, content_type: str) -> None:
        signatures = IMAGE_SIGNATURES.get(content_type)
        if signatures is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="仅支持 PNG、JPEG、GIF 和 WebP 图片",
            )
        upload.file.seek(0)
        header = upload.file.read(12)
        upload.file.seek(0)
        valid = any(header.startswith(signature) for signature in signatures)
        if content_type == "image/webp":
            valid = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        if not valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片内容与类型不匹配")

    @staticmethod
    def _file_size(upload: UploadFile) -> int:
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
        if size <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片不能为空")
        if size > settings.MEDIA_MAX_IMAGE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="图片超过大小限制")
        return size

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        name = Path(filename or "image").name.strip()
        return (name or "image")[:255]
