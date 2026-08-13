from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "自动化测试平台后端"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    PLATFORM_WEB_BASE_URL: str = Field(
        default="http://127.0.0.1:5174",
        pattern=r"^https?://",
    )

    DATABASE_URL: str = Field(
        default="mysql+pymysql://root:password@127.0.0.1:3306/devtestbackend?charset=utf8mb4"
    )
    DB_POOL_PRE_PING: bool = True
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: float = 30.0
    DB_CONNECT_TIMEOUT_SECONDS: int = 10

    JWT_SECRET_KEY: str = "change-this-secret-key-for-devtestbackend"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    DESKTOP_DEVICE_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=5, le=1440)
    DESKTOP_DEVICE_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=90, ge=1, le=365)
    DESKTOP_HEARTBEAT_INTERVAL_SECONDS: int = Field(default=20, ge=5, le=300)
    DESKTOP_HEARTBEAT_PERSIST_SECONDS: int = Field(default=60, ge=10, le=3600)
    DESKTOP_DEVICE_OFFLINE_AFTER_SECONDS: int = Field(default=75, ge=15, le=3600)
    DESKTOP_REDIS_RETRY_SECONDS: int = Field(default=5, ge=1, le=300)
    DESKTOP_CONTROL_REDIS_CHANNEL_PREFIX: str = "testauto:desktop:control:"
    DESKTOP_PRESENCE_REDIS_KEY_PREFIX: str = "testauto:desktop:presence:"
    DESKTOP_MIN_VERSION: str = "0.1.0"
    DESKTOP_MAX_CONCURRENCY: int = Field(default=4, ge=1, le=64)
    DESKTOP_SUPPORTED_DSL_VERSIONS: list[str] = ["ui-case-v1"]
    DESKTOP_SUPPORTED_IPC_VERSIONS: list[str] = ["desktop-ipc-v1"]
    UI_CASE_MAX_STEPS: int = Field(default=200, ge=1, le=2000)
    UI_CASE_MAX_DSL_BYTES: int = Field(default=1048576, ge=16384, le=8388608)
    UI_CASE_MAX_TAGS: int = Field(default=50, ge=1, le=200)
    UI_EXECUTION_LEASE_SECONDS: int = Field(default=60, ge=15, le=900)
    UI_EXECUTION_LEASE_RENEW_AFTER_SECONDS: int = Field(default=20, ge=5, le=300)
    UI_EXECUTION_EVENT_BATCH_MAX: int = Field(default=100, ge=1, le=1000)
    UI_EXECUTION_EVENT_BATCH_MAX_BYTES: int = Field(default=524288, ge=16384, le=8388608)
    UI_EXECUTION_EVENT_MAX_BYTES: int = Field(default=16384, ge=1024, le=1048576)
    UI_EXECUTION_COMMAND_TTL_SECONDS: int = Field(default=300, ge=30, le=86400)
    UI_EXECUTION_LEASE_SWEEP_ENABLED: bool = True
    UI_EXECUTION_LEASE_SWEEP_INTERVAL_SECONDS: int = Field(default=10, ge=5, le=300)
    UI_EXECUTION_LEASE_SWEEP_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    UI_EXECUTION_SSE_POLL_SECONDS: float = Field(default=0.5, ge=0.1, le=5.0)
    UI_EXECUTION_SSE_HEARTBEAT_SECONDS: int = Field(default=15, ge=5, le=60)
    UI_ARTIFACT_UPLOAD_EXPIRE_SECONDS: int = Field(default=600, ge=60, le=86400)
    UI_ARTIFACT_DOWNLOAD_EXPIRE_SECONDS: int = Field(default=300, ge=60, le=3600)
    UI_ARTIFACT_MAX_BYTES: int = Field(default=536870912, ge=1024, le=2147483648)
    UI_ARTIFACT_ALLOWED_CONTENT_TYPES: list[str] = [
        "image/png",
        "image/jpeg",
        "application/zip",
        "application/json",
        "application/octet-stream",
        "text/plain",
        "text/html",
        "video/webm",
    ]
    UI_ARTIFACT_OBJECT_PREFIX: str = "ui-executions"
    UI_ARTIFACT_CLEANUP_ENABLED: bool = True
    UI_ARTIFACT_CLEANUP_INTERVAL_SECONDS: int = Field(default=300, ge=30, le=86400)
    UI_ARTIFACT_CLEANUP_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)

    MINIO_ENDPOINT_URL: str = "http://127.0.0.1:9000"
    MINIO_PUBLIC_ENDPOINT_URL: str = ""
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "testplatform"
    MINIO_REGION: str = "us-east-1"
    MINIO_SECURE: bool = False
    MEDIA_MAX_IMAGE_BYTES: int = 10 * 1024 * 1024
    MEDIA_PRESIGNED_URL_EXPIRE_SECONDS: int = 3600

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_TIMEOUT_SECONDS: float = 60.0
    DEEPSEEK_STREAM_MAX_RETRIES: int = 2
    DEEPSEEK_STREAM_RETRY_BASE_SECONDS: float = 0.5
    DEEPSEEK_STREAM_RETRY_MAX_SECONDS: float = 4.0
    EXECUTION_WORKER_MAX_WORKERS: int = 8
    EXECUTION_WORKER_QUEUE_SIZE: int = 256
    EXECUTION_REQUEST_WAIT_TIMEOUT_SECONDS: float = 300.0
    EXECUTION_RESPONSE_MAX_BYTES: int = Field(default=1048576, ge=1024, le=16777216)
    EXECUTION_OUTBOUND_ALLOW_PRIVATE_NETWORKS: bool = False
    EXECUTION_OUTBOUND_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    DATABASE_EXECUTION_ALLOW_PRIVATE_NETWORKS: bool = False
    DATABASE_EXECUTION_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    EXECUTION_DIAGNOSTIC_MODEL_MAX_CHARS: int = 12000
    EXECUTION_DIAGNOSTIC_MODEL_HARD_MAX_CHARS: int = 24000
    EXECUTION_ARTIFACT_INLINE_THRESHOLD_BYTES: int = Field(
        default=65536, ge=16384, le=1048576
    )
    EXECUTION_ARTIFACT_CHUNK_BYTES: int = Field(default=8192, ge=1024, le=65536)
    EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED: bool = True
    EXECUTION_METRICS_SCHEDULER_ENABLED: bool = True
    EXECUTION_METRICS_SCHEDULER_INTERVAL_SECONDS: int = Field(
        default=60, ge=10, le=3600
    )
    DASHBOARD_ASSET_SNAPSHOT_SCHEDULER_ENABLED: bool = True
    DASHBOARD_ASSET_SNAPSHOT_SCHEDULER_INTERVAL_SECONDS: int = Field(
        default=300, ge=60, le=86400
    )
    AGENT_RUN_STALE_TIMEOUT_SECONDS: float = 900.0
    AGENT_TRACE_VERBOSE_PAYLOADS: bool = False
    AGENT_TRACE_FULL_PAYLOADS: bool = False
    AGENT_TRACE_PAYLOAD_MAX_CHARS: int = 12000
    AGENT_LLM_INTENT_DECISION_ENABLED: bool = True
    AGENT_NATIVE_TOOL_CALLING_ENABLED: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FILE_PATH: str = "logs/app.log"
    LOG_REQUESTS: bool = True
    LOG_SLOW_REQUEST_MS: int = 1000
    TEST_PLAN_SCHEDULER_ENABLED: bool = True
    TEST_PLAN_SCHEDULER_INTERVAL_SECONDS: int = 30
    TEST_PLAN_DEFAULT_TIMEZONE: str = "Asia/Shanghai"
    TEST_PLAN_RUN_STALE_SECONDS: int = 3600
    TEST_PLAN_WEBHOOK_SECRET: str = ""
    TEST_PLAN_WEBHOOK_MAX_AGE_SECONDS: int = 300
    SNAPSHOT_ENCRYPTION_KEY: str = ""
    TEST_REPORT_EXPORT_EXPIRE_SECONDS: int = Field(default=300, ge=60, le=3600)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
