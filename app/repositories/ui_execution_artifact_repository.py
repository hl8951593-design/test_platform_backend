from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.execution_diagnostic import ExecutionPayloadArtifact
from app.models.ui_execution_artifact import ExecutionArtifactUploadSession


class UiExecutionArtifactRepository:
    def __init__(self, db: Session):
        self.db = db

    def add_session(
        self, session: ExecutionArtifactUploadSession
    ) -> ExecutionArtifactUploadSession:
        self.db.add(session)
        self.db.flush()
        return session

    def get_session_by_request(
        self,
        *,
        execution_id: int,
        device_id: int,
        client_request_id: str,
    ) -> ExecutionArtifactUploadSession | None:
        return self.db.scalar(
            select(ExecutionArtifactUploadSession).where(
                ExecutionArtifactUploadSession.ui_execution_id == execution_id,
                ExecutionArtifactUploadSession.created_by_device_id == device_id,
                ExecutionArtifactUploadSession.client_request_id == client_request_id,
            )
        )

    def get_session_for_update(
        self, upload_id: str
    ) -> ExecutionArtifactUploadSession | None:
        return self.db.scalar(
            select(ExecutionArtifactUploadSession)
            .where(ExecutionArtifactUploadSession.upload_id == upload_id)
            .with_for_update()
        )

    def count_pending_sessions(self, execution_id: int, now: datetime) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(ExecutionArtifactUploadSession)
                .where(
                    ExecutionArtifactUploadSession.ui_execution_id == execution_id,
                    ExecutionArtifactUploadSession.status == "pending",
                    ExecutionArtifactUploadSession.expires_at > now,
                )
            )
            or 0
        )

    def add_artifact(self, artifact: ExecutionPayloadArtifact) -> ExecutionPayloadArtifact:
        self.db.add(artifact)
        self.db.flush()
        return artifact

    def get_artifact(
        self,
        *,
        execution_id: int,
        artifact_ref: str,
    ) -> ExecutionPayloadArtifact | None:
        return self.db.scalar(
            select(ExecutionPayloadArtifact).where(
                ExecutionPayloadArtifact.execution_type == "ui",
                ExecutionPayloadArtifact.execution_id == execution_id,
                ExecutionPayloadArtifact.artifact_ref == artifact_ref,
            )
        )

    def list_artifacts(self, execution_id: int) -> list[ExecutionPayloadArtifact]:
        return list(
            self.db.scalars(
                select(ExecutionPayloadArtifact)
                .where(
                    ExecutionPayloadArtifact.execution_type == "ui",
                    ExecutionPayloadArtifact.execution_id == execution_id,
                )
                .order_by(ExecutionPayloadArtifact.created_at.asc(), ExecutionPayloadArtifact.id.asc())
            ).all()
        )

    def delete_artifact(self, artifact: ExecutionPayloadArtifact) -> None:
        self.db.delete(artifact)

    def list_expired_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[ExecutionArtifactUploadSession]:
        return list(
            self.db.scalars(
                select(ExecutionArtifactUploadSession)
                .where(
                    ExecutionArtifactUploadSession.status == "pending",
                    ExecutionArtifactUploadSession.expires_at <= now,
                )
                .order_by(ExecutionArtifactUploadSession.expires_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
