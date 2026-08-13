import re
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


DatabaseProvider = Literal["mysql", "postgresql", "mongodb"]
DatabaseActionKind = Literal["database_query", "database_execute"]
DatabaseAssertionOperator = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_contains"
]


class DatabaseConnectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    connection_key: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("connection_key", "connectionKey"),
    )
    provider: DatabaseProvider
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str = Field(
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("database_name", "databaseName"),
    )
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=4096)
    options: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("is_enabled", "isEnabled")
    )
    allow_writes: bool = Field(
        default=False, validation_alias=AliasChoices("allow_writes", "allowWrites")
    )
    connect_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        validation_alias=AliasChoices("connect_timeout_ms", "connectTimeoutMs"),
    )
    statement_timeout_ms: int = Field(
        default=10000,
        ge=100,
        le=300000,
        validation_alias=AliasChoices("statement_timeout_ms", "statementTimeoutMs"),
    )
    max_rows: int = Field(
        default=100,
        ge=1,
        le=1000,
        validation_alias=AliasChoices("max_rows", "maxRows"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("connection_key")
    @classmethod
    def validate_connection_key(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", normalized):
            raise ValueError("连接键必须以字母开头，且只能包含字母、数字、下划线和连字符")
        return normalized

    @field_validator("host", "name", "database_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def apply_provider_defaults(self):
        if self.port is None:
            self.port = {"mysql": 3306, "postgresql": 5432, "mongodb": 27017}[
                self.provider
            ]
        if self.provider in {"mysql", "postgresql"} and not (self.username or "").strip():
            raise ValueError("MySQL/PostgreSQL 连接必须提供 username")
        return self


class DatabaseConnectionUpdateRequest(DatabaseConnectionCreateRequest):
    password: str | None = Field(
        default=None,
        max_length=4096,
        description="为空时保留原密码；传新值时替换",
    )


class DatabaseConnectionRead(BaseModel):
    id: int
    project_id: int
    environment_id: int
    name: str
    connection_key: str
    provider: DatabaseProvider
    host: str
    port: int | None
    database_name: str
    username: str | None
    password_configured: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool
    allow_writes: bool
    connect_timeout_ms: int
    statement_timeout_ms: int
    max_rows: int
    created_by_id: int
    created_at: datetime
    updated_at: datetime


class DatabaseConnectionTestRead(BaseModel):
    status: Literal["passed", "failed"]
    provider: DatabaseProvider
    duration_ms: int
    server_info: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""


class DatabaseAssertionConfig(BaseModel):
    type: Literal["row_count", "value", "exists", "not_exists", "affected_rows"]
    operator: DatabaseAssertionOperator = "eq"
    path: str | None = None
    expected: Any = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_path(self):
        if self.type == "value" and not (self.path or "").strip():
            raise ValueError("value 断言必须提供 path")
        return self


class DatabaseExtractorConfig(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=512)
    masked: bool = False
    required: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("取值变量名格式不合法")
        return value


class DatabaseRetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=20)
    interval_ms: int = Field(default=500, ge=0, le=60000)

    model_config = ConfigDict(extra="forbid")


class DatabaseActionConfig(BaseModel):
    connection_id: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("connection_id", "connectionId"),
    )
    connection_key: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("connection_key", "connectionKey"),
    )
    sql: str | None = Field(default=None, max_length=100000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    collection: str | None = Field(default=None, max_length=255)
    operation: str | None = Field(default=None, max_length=32)
    filter: dict[str, Any] = Field(default_factory=dict)
    projection: dict[str, Any] | None = None
    sort: list[list[Any]] = Field(default_factory=list)
    pipeline: list[dict[str, Any]] = Field(default_factory=list)
    document: dict[str, Any] | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    update: dict[str, Any] | None = None
    upsert: bool = False
    assertions: list[DatabaseAssertionConfig] = Field(default_factory=list)
    extractors: list[DatabaseExtractorConfig] = Field(default_factory=list)
    retry_policy: DatabaseRetryPolicy = Field(
        default_factory=DatabaseRetryPolicy,
        validation_alias=AliasChoices("retry_policy", "retryPolicy"),
    )
    timeout_ms: int | None = Field(default=None, ge=100, le=300000)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        validation_alias=AliasChoices("max_rows", "maxRows"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def validate_connection_reference(self):
        if self.connection_id is None and not (self.connection_key or "").strip():
            raise ValueError("数据库动作必须提供 connection_id 或 connection_key")
        return self


class ScenarioDatabaseExecuteUnsavedRequest(BaseModel):
    environment_id: int = Field(gt=0)
    kind: DatabaseActionKind
    config: DatabaseActionConfig
    input_values: dict[str, Any] = Field(default_factory=dict)


class ScenarioDatabaseExecuteUnsavedRead(BaseModel):
    status: Literal["passed", "failed", "error"]
    duration_ms: int
    output: dict[str, Any] = Field(default_factory=dict)
    assertion_results: list[dict[str, Any]] = Field(default_factory=list)
    extracted_variables: list[dict[str, Any]] = Field(default_factory=list)
    attempt_history: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str = ""
