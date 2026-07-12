from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "自动化测试平台后端"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"

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
