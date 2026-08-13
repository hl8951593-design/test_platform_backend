from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class DesktopDeviceRegisterRequest(BaseModel):
    installation_id: str = Field(
        min_length=16,
        max_length=128,
        validation_alias=AliasChoices("installation_id", "installationId"),
    )
    name: str = Field(min_length=1, max_length=128)
    desktop_version: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("desktop_version", "desktopVersion"),
    )
    os_name: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("os_name", "osName"),
    )
    os_version: str = Field(
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("os_version", "osVersion"),
    )
    architecture: str = Field(min_length=1, max_length=32)
    supported_protocols: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("supported_protocols", "supportedProtocols"),
    )
    capabilities: dict[str, Any] = Field(default_factory=dict)
    device_public_key: str | None = Field(
        default=None,
        max_length=16384,
        validation_alias=AliasChoices("device_public_key", "devicePublicKey"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator(
        "installation_id",
        "name",
        "desktop_version",
        "os_name",
        "os_version",
        "architecture",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()


class DesktopDeviceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    accepting_jobs: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("accepting_jobs", "acceptingJobs"),
    )
    concurrency_limit: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("concurrency_limit", "concurrencyLimit"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class DesktopDeviceProjectBindingUpdateRequest(BaseModel):
    enabled: bool = True
    accepting_jobs: bool = Field(
        default=True,
        validation_alias=AliasChoices("accepting_jobs", "acceptingJobs"),
    )
    concurrency_limit: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices("concurrency_limit", "concurrencyLimit"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class DesktopDeviceRefreshRequest(BaseModel):
    refresh_token: str = Field(
        min_length=40,
        max_length=512,
        validation_alias=AliasChoices("refresh_token", "refreshToken"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class DesktopDeviceHeartbeatRequest(BaseModel):
    desktop_version: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("desktop_version", "desktopVersion"),
    )
    supported_protocols: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("supported_protocols", "supportedProtocols"),
    )
    capabilities: dict[str, Any] = Field(default_factory=dict)
    active_execution_ids: list[str] = Field(
        default_factory=list,
        max_length=100,
        validation_alias=AliasChoices("active_execution_ids", "activeExecutionIds"),
    )
    local_outbox_events: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("local_outbox_events", "localOutboxEvents"),
    )
    local_outbox_artifacts: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("local_outbox_artifacts", "localOutboxArtifacts"),
    )
    current_load: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("current_load", "currentLoad"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class DesktopDeviceCredentialRead(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    access_expires_in: int
    refresh_expires_at: datetime


class DesktopDeviceProjectBindingRead(BaseModel):
    project_id: int
    enabled: bool
    accepting_jobs: bool
    concurrency_limit: int
    created_at: datetime
    updated_at: datetime


class DesktopDeviceRead(BaseModel):
    device_id: str
    owner_id: int
    name: str
    registration_status: Literal["active", "revoked"]
    online: bool
    accepting_jobs: bool
    concurrency_limit: int
    desktop_version: str
    os_name: str
    os_version: str
    architecture: str
    supported_protocols: dict[str, Any]
    capabilities: dict[str, Any]
    runtime_state: dict[str, Any]
    last_heartbeat_at: datetime | None
    registered_at: datetime
    revoked_at: datetime | None
    project_bindings: list[DesktopDeviceProjectBindingRead] = Field(default_factory=list)


class DesktopDeviceRegisterRead(BaseModel):
    device: DesktopDeviceRead
    credential: DesktopDeviceCredentialRead


class DesktopRuntimePolicyRead(BaseModel):
    min_desktop_version: str
    supported_dsl_versions: list[str]
    supported_ipc_versions: list[str]
    heartbeat_interval_seconds: int
    offline_after_seconds: int
    max_concurrency: int
    control_transport: Literal["wss_rest"] = "wss_rest"


class DesktopDeviceHeartbeatRead(BaseModel):
    device_id: str
    server_time: datetime
    online: bool = True
    runtime_compatible: bool
    accepting_jobs: bool
    heartbeat_interval_seconds: int
    commands_cursor: str | None = None
