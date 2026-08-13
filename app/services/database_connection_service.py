import ipaddress
import socket
import time
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ProjectPermission
from app.core.sensitive_data import protect_secret_text
from app.models.database_connection import ProjectDatabaseConnection
from app.models.project import ProjectEnvironment
from app.models.user import User
from app.repositories.database_connection_repository import DatabaseConnectionRepository
from app.schemas.database_connection import (
    DatabaseConnectionCreateRequest,
    DatabaseConnectionRead,
    DatabaseConnectionTestRead,
    DatabaseConnectionUpdateRequest,
)
from app.services.permission_service import PermissionService


_COMMON_OPTIONS = {"tls"}
_PROVIDER_OPTIONS = {
    "mysql": {"charset", "ssl_ca"},
    "postgresql": {"ssl_mode", "ssl_root_cert"},
    "mongodb": {"auth_source", "replica_set", "use_srv"},
}


class DatabaseConnectionService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = DatabaseConnectionRepository(db)
        self.permission_service = PermissionService(db)

    def list_connections(
        self, *, project_id: int, environment_id: int, current_user: User
    ) -> list[DatabaseConnectionRead]:
        self._require_environment(project_id, environment_id)
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.VIEW_DATABASE.value
        )
        return [
            self.to_read(item)
            for item in self.repository.list_connections(
                project_id=project_id, environment_id=environment_id
            )
        ]

    def create_connection(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: DatabaseConnectionCreateRequest,
        current_user: User,
    ) -> DatabaseConnectionRead:
        self._require_environment(project_id, environment_id)
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.MANAGE_DATABASE.value
        )
        options = self._validated_options(payload.provider, payload.options)
        self._validate_target_host(payload.host, payload.port)
        item = ProjectDatabaseConnection(
            project_id=project_id,
            environment_id=environment_id,
            name=payload.name,
            connection_key=payload.connection_key,
            provider=payload.provider,
            host=payload.host,
            port=payload.port,
            database_name=payload.database_name,
            username=(payload.username or "").strip() or None,
            password_encrypted=(
                protect_secret_text(payload.password) if payload.password else None
            ),
            options_json=options,
            is_enabled=payload.is_enabled,
            allow_writes=payload.allow_writes,
            connect_timeout_ms=payload.connect_timeout_ms,
            statement_timeout_ms=payload.statement_timeout_ms,
            max_rows=payload.max_rows,
            created_by_id=current_user.id,
        )
        try:
            self.repository.add_connection(item)
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一环境下数据库连接键不能重复",
            ) from exc
        return self.to_read(item)

    def update_connection(
        self,
        *,
        project_id: int,
        environment_id: int,
        connection_id: int,
        payload: DatabaseConnectionUpdateRequest,
        current_user: User,
    ) -> DatabaseConnectionRead:
        self._require_environment(project_id, environment_id)
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.MANAGE_DATABASE.value
        )
        item = self._get(project_id, environment_id, connection_id)
        self._validate_target_host(payload.host, payload.port)
        item.name = payload.name
        item.connection_key = payload.connection_key
        item.provider = payload.provider
        item.host = payload.host
        item.port = payload.port
        item.database_name = payload.database_name
        item.username = (payload.username or "").strip() or None
        if payload.password:
            item.password_encrypted = protect_secret_text(payload.password)
        item.options_json = self._validated_options(payload.provider, payload.options)
        item.is_enabled = payload.is_enabled
        item.allow_writes = payload.allow_writes
        item.connect_timeout_ms = payload.connect_timeout_ms
        item.statement_timeout_ms = payload.statement_timeout_ms
        item.max_rows = payload.max_rows
        try:
            self.repository.save_connection(item)
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一环境下数据库连接键不能重复",
            ) from exc
        return self.to_read(item)

    def delete_connection(
        self,
        *,
        project_id: int,
        environment_id: int,
        connection_id: int,
        current_user: User,
    ) -> None:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.MANAGE_DATABASE.value
        )
        item = self._get(project_id, environment_id, connection_id)
        suffix = f"__deleted__{item.id}"
        item.connection_key = f"{item.connection_key[: 64 - len(suffix)]}{suffix}"
        item.is_deleted = True
        item.is_enabled = False
        self.repository.save_connection(item)

    def test_connection(
        self,
        *,
        project_id: int,
        environment_id: int,
        connection_id: int,
        current_user: User,
    ) -> DatabaseConnectionTestRead:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.MANAGE_DATABASE.value
        )
        item = self._get(project_id, environment_id, connection_id)
        self._validate_target_host(item.host, item.port)
        started = time.perf_counter()
        try:
            from app.services.database_action_service import DatabaseTargetClient

            server_info = DatabaseTargetClient(item).test_connection()
            return DatabaseConnectionTestRead(
                status="passed",
                provider=item.provider,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                server_info=server_info,
            )
        except Exception as exc:  # noqa: BLE001
            return DatabaseConnectionTestRead(
                status="failed",
                provider=item.provider,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                error_message=str(exc),
            )

    @staticmethod
    def to_read(item: ProjectDatabaseConnection) -> DatabaseConnectionRead:
        return DatabaseConnectionRead(
            id=item.id,
            project_id=item.project_id,
            environment_id=item.environment_id,
            name=item.name,
            connection_key=item.connection_key,
            provider=item.provider,
            host=item.host,
            port=item.port,
            database_name=item.database_name,
            username=item.username,
            password_configured=bool(item.password_encrypted),
            options=dict(item.options_json or {}),
            is_enabled=item.is_enabled,
            allow_writes=item.allow_writes,
            connect_timeout_ms=item.connect_timeout_ms,
            statement_timeout_ms=item.statement_timeout_ms,
            max_rows=item.max_rows,
            created_by_id=item.created_by_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    def _get(
        self, project_id: int, environment_id: int, connection_id: int
    ) -> ProjectDatabaseConnection:
        item = self.repository.get_connection(
            project_id=project_id,
            environment_id=environment_id,
            connection_id=connection_id,
        )
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据库连接不存在")
        return item

    def _require_environment(self, project_id: int, environment_id: int) -> None:
        item = self.db.get(ProjectEnvironment, environment_id)
        if item is None or item.project_id != project_id or item.is_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

    @staticmethod
    def _validated_options(provider: str, options: dict[str, Any]) -> dict[str, Any]:
        invalid = set(options) - _COMMON_OPTIONS - _PROVIDER_OPTIONS[provider]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"不支持的数据库连接选项: {', '.join(sorted(invalid))}",
            )
        result = dict(options)
        if provider == "postgresql" and "ssl_mode" in result:
            allowed = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
            if result["ssl_mode"] not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="PostgreSQL ssl_mode 不合法",
                )
        return result

    @staticmethod
    def _validate_target_host(host: str, port: int | None) -> None:
        hostname = host.rstrip(".").lower()
        allowed_hosts = {
            item.rstrip(".").lower()
            for item in settings.DATABASE_EXECUTION_ALLOWED_HOSTS
        }
        if hostname in allowed_hosts or settings.DATABASE_EXECUTION_ALLOW_PRIVATE_NETWORKS:
            return
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"数据库主机无法解析: {hostname}",
            ) from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"数据库目标 {hostname} 位于受保护网络；如确需访问，请加入 "
                        "DATABASE_EXECUTION_ALLOWED_HOSTS"
                    ),
                )
