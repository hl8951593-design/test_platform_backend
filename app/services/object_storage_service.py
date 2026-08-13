from functools import cached_property
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import settings


class ObjectStorageService:
    def _client(self, endpoint_url: str):
        scheme = "https" if settings.MINIO_SECURE else "http"
        endpoint = endpoint_url or settings.MINIO_ENDPOINT_URL
        if "://" not in endpoint:
            endpoint = f"{scheme}://{endpoint}"
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.MINIO_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @cached_property
    def client(self):
        self._require_configuration()
        return self._client(settings.MINIO_ENDPOINT_URL)

    @cached_property
    def public_client(self):
        self._require_configuration()
        return self._client(settings.MINIO_PUBLIC_ENDPOINT_URL or settings.MINIO_ENDPOINT_URL)

    def upload(self, *, fileobj: BinaryIO, object_key: str, content_type: str) -> str | None:
        try:
            response = self.client.put_object(
                Bucket=settings.MINIO_BUCKET,
                Key=object_key,
                Body=fileobj,
                ContentType=content_type,
            )
            return str(response.get("ETag", "")).strip('"') or None
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    def delete(self, *, bucket: str, object_key: str) -> None:
        try:
            self.client.delete_object(Bucket=bucket, Key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    def presigned_put_url(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str,
        sha256: str,
        expires_in: int,
    ) -> tuple[str, dict[str, str]]:
        required_headers = {
            "Content-Type": content_type,
            "x-amz-meta-sha256": sha256,
        }
        try:
            url = self.public_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                    "Metadata": {"sha256": sha256},
                },
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
            return url, required_headers
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    def head(self, *, bucket: str, object_key: str) -> dict[str, Any]:
        try:
            response = self.client.head_object(Bucket=bucket, Key=object_key)
            return {
                "size_bytes": int(response.get("ContentLength") or 0),
                "content_type": str(response.get("ContentType") or ""),
                "metadata": {
                    str(key).lower(): str(value)
                    for key, value in (response.get("Metadata") or {}).items()
                },
                "etag": str(response.get("ETag") or "").strip('"') or None,
            }
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    def presigned_get_url(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in: int | None = None,
    ) -> str:
        try:
            return self.public_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": object_key},
                ExpiresIn=expires_in or settings.MEDIA_PRESIGNED_URL_EXPIRE_SECONDS,
            )
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    @staticmethod
    def _require_configuration() -> None:
        if not settings.MINIO_ACCESS_KEY or not settings.MINIO_SECRET_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="媒体存储未配置",
            )

    @staticmethod
    def _unavailable() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="媒体存储暂不可用",
        )
