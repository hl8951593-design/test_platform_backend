from __future__ import annotations

import re
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.ui_execution import UiExecutionLeaseRequest


ArtifactSection = Literal[
    "screenshot",
    "trace",
    "video",
    "console",
    "network",
    "download",
    "log",
]


class UiArtifactPresignRequest(UiExecutionLeaseRequest):
    client_request_id: str = Field(min_length=1, max_length=128)
    step_id: str | None = Field(default=None, max_length=128)
    section: ArtifactSection
    content_type: str = Field(min_length=1, max_length=128)
    original_filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_request_id", "content_type", "original_filename")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or any(ord(char) < 32 for char in value):
            raise ValueError("original_filename must be a base filename")
        return value

    @field_validator("content_type")
    @classmethod
    def normalize_content_type(cls, value: str) -> str:
        return value.lower().split(";", 1)[0].strip()

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("sha256 must contain 64 lowercase hex characters")
        return normalized


class UiArtifactFinalizeRequest(UiExecutionLeaseRequest):
    upload_id: str = Field(min_length=1, max_length=64)
    artifact_ref: str = Field(min_length=1, max_length=64)

    model_config = ConfigDict(extra="forbid")
