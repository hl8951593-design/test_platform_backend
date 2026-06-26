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
    EXECUTION_WORKER_MAX_WORKERS: int = 8
    EXECUTION_WORKER_QUEUE_SIZE: int = 256
    EXECUTION_REQUEST_WAIT_TIMEOUT_SECONDS: float = 300.0
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
