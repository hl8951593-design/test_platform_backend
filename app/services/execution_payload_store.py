from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.sensitive_data import mask_sensitive
from app.models.execution_diagnostic import ExecutionPayloadArtifact
from app.repositories.execution_diagnostic_repository import (
    ExecutionDiagnosticRepository,
)
from app.schemas.execution_record import ExecutionType


MAX_ARTIFACT_CHUNK_BYTES = 65_536


class ArtifactChunk(BaseModel):
    artifact_ref: str
    offset: int
    next_offset: int | None
    has_more: bool
    raw_size_bytes: int
    sha256: str
    content: str


class DatabaseExecutionPayloadStore:
    """Project-scoped, deterministic storage for redacted execution evidence."""

    def __init__(self, db: Session):
        self.repository = ExecutionDiagnosticRepository(db)

    def put(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        step_id: str | None,
        section: str,
        value: Any,
    ) -> str:
        redacted = mask_sensitive(value)
        raw = _json_bytes(redacted)
        digest = hashlib.sha256(raw).hexdigest()
        artifact_ref = (
            f"execution-artifact://{project_id}/{execution_type}/"
            f"{execution_id}/{digest[:24]}"
        )
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        self.repository.upsert_artifact(
            {
                "artifact_ref": artifact_ref,
                "project_id": project_id,
                "execution_type": execution_type,
                "execution_id": execution_id,
                "step_id": step_id,
                "section": section,
                "storage_backend": "database",
                "storage_locator": artifact_ref,
                "content_type": "application/json",
                "encoding": "gzip+json",
                "content": compressed,
                "raw_size_bytes": len(raw),
                "stored_size_bytes": len(compressed),
                "sha256": digest,
                "redaction_version": "sensitive_data_v1",
                "retention_tier": "standard",
            }
        )
        return artifact_ref

    def get_metadata(
        self, *, project_id: int, artifact_ref: str
    ) -> ExecutionPayloadArtifact:
        artifact = self.repository.get_artifact(
            project_id=project_id, artifact_ref=artifact_ref
        )
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="execution artifact not found",
            )
        return artifact

    def read_chunk(
        self,
        *,
        project_id: int,
        artifact_ref: str,
        offset: int,
        max_bytes: int,
    ) -> ArtifactChunk:
        if offset < 0 or max_bytes < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="artifact offset and max_bytes are invalid",
            )
        artifact = self.get_metadata(
            project_id=project_id, artifact_ref=artifact_ref
        )
        raw = self._verified_raw(artifact)
        requested_offset = min(offset, len(raw))
        start = _utf8_safe_start(raw, requested_offset)
        end = _utf8_safe_end(
            raw,
            start=start,
            max_bytes=min(max_bytes, MAX_ARTIFACT_CHUNK_BYTES),
        )
        has_more = end < len(raw)
        return ArtifactChunk(
            artifact_ref=artifact.artifact_ref,
            offset=start,
            next_offset=end if has_more else None,
            has_more=has_more,
            raw_size_bytes=artifact.raw_size_bytes,
            sha256=artifact.sha256,
            content=raw[start:end].decode("utf-8"),
        )

    def read_all(self, *, project_id: int, artifact_ref: str) -> Any:
        artifact = self.get_metadata(
            project_id=project_id, artifact_ref=artifact_ref
        )
        return json.loads(self._verified_raw(artifact).decode("utf-8"))

    @staticmethod
    def _verified_raw(artifact: ExecutionPayloadArtifact) -> bytes:
        if artifact.storage_backend != "database" or artifact.content is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="execution artifact content is unavailable",
            )
        try:
            raw = gzip.decompress(artifact.content)
        except (OSError, EOFError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="execution artifact integrity check failed",
            ) from exc
        digest = hashlib.sha256(raw).hexdigest()
        if digest != artifact.sha256 or len(raw) != artifact.raw_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="execution artifact integrity check failed",
            )
        return raw


def serialized_redacted_size(value: Any) -> int:
    return len(_json_bytes(mask_sensitive(value)))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _utf8_safe_start(raw: bytes, offset: int) -> int:
    start = offset
    while start < len(raw) and raw[start] & 0b1100_0000 == 0b1000_0000:
        start += 1
    return start


def _utf8_safe_end(raw: bytes, *, start: int, max_bytes: int) -> int:
    end = min(start + max_bytes, len(raw))
    while end > start:
        try:
            raw[start:end].decode("utf-8")
            return end
        except UnicodeDecodeError:
            end -= 1
    return start
