from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RetryPolicyConfig(BaseModel):
    enabled: bool = False
    max_attempts: int = Field(default=1, ge=1, le=10)
    base_delay_ms: int = Field(default=500, ge=0, le=60000)
    max_delay_ms: int = Field(default=10000, ge=0, le=300000)
    jitter: Literal["full", "none"] = "full"
    respect_retry_after: bool = True
    retry_network_errors: bool = True
    retry_timeouts: bool = True
    status_codes: list[int] = Field(
        default_factory=lambda: [408, 429, 500, 502, 503, 504]
    )
    retry_unsafe_methods: bool = False

    @model_validator(mode="after")
    def validate_policy(self):
        if self.max_delay_ms < self.base_delay_ms:
            raise ValueError("max_delay_ms 不能小于 base_delay_ms")
        if any(code < 100 or code > 599 for code in self.status_codes):
            raise ValueError("status_codes 必须是合法 HTTP 状态码")
        self.status_codes = list(dict.fromkeys(self.status_codes))
        return self

    @property
    def attempts(self) -> int:
        return self.max_attempts if self.enabled else 1
