from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ProjectPermission
from app.models.project import ProjectEnvironment
from app.models.ui_test_case import UiTestCase, UiTestCaseVersion
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.ui_test_case_repository import UiTestCaseRepository
from app.schemas.ui_test_case import (
    SECRET_REFERENCE_RE,
    UiCaseDsl,
    UiTestCaseCreateRequest,
    UiTestCaseListItemRead,
    UiTestCaseRead,
    UiTestCaseUpdateRequest,
    UiTestCaseValidationRead,
    UiTestCaseVersionCreateRequest,
    UiTestCaseVersionRead,
    UiTestCaseVersionSummaryRead,
)
from app.services.permission_service import PermissionService


def _is_loopback_host(value: str) -> bool:
    normalized = value.strip().lower().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _same_navigation_host(target_host: str, environment_host: str) -> bool:
    if target_host.lower().rstrip(".") == environment_host.lower().rstrip("."):
        return True
    return _is_loopback_host(target_host) and _is_loopback_host(environment_host)


class UiTestCaseService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = UiTestCaseRepository(db)
        self.project_repository = ProjectRepository(db)
        self.permission_service = PermissionService(db)

    def validate_unsaved(
        self,
        *,
        project_id: int,
        default_environment_id: int | None,
        dsl: UiCaseDsl,
        current_user: User,
    ) -> UiTestCaseValidationRead:
        self._require_manage(current_user, project_id)
        environment = None
        if default_environment_id is not None:
            environment = self._get_environment(project_id, default_environment_id)
        return self._validate_dsl(dsl, environment=environment)

    def list_cases(
        self,
        *,
        project_id: int,
        keyword: str | None,
        case_status: str | None,
        environment_id: int | None,
        page: int,
        page_size: int,
        current_user: User,
    ) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        if environment_id is not None:
            self._get_environment(project_id, environment_id)
        items, total = self.repository.list_by_project(
            project_id=project_id,
            keyword=keyword,
            status=case_status,
            environment_id=environment_id,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._serialize_list_item(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def create_case(
        self,
        *,
        project_id: int,
        payload: UiTestCaseCreateRequest,
        current_user: User,
    ) -> UiTestCaseRead:
        self._require_manage(current_user, project_id)
        environment = self._get_environment(
            project_id,
            payload.default_environment_id,
        )
        validation = self._validate_dsl(payload.dsl, environment=environment)
        tags = self._normalize_tags(payload.tags)
        ui_test_case = UiTestCase(
            public_id=f"ui_case_{secrets.token_urlsafe(18)}",
            project_id=project_id,
            default_environment_id=environment.id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            tags_json=tags,
            created_by_id=current_user.id,
        )
        try:
            self.repository.add_case(ui_test_case)
            version = UiTestCaseVersion(
                ui_test_case_id=ui_test_case.id,
                version_number=1,
                schema_version="ui-case-v1",
                dsl_json=validation.normalized_dsl,
                checksum_sha256=validation.checksum.removeprefix("sha256:"),
                required_secret_refs_json=validation.required_secret_refs,
                change_summary=payload.change_summary,
                created_by_id=current_user.id,
            )
            self.repository.add_version(version)
            ui_test_case.current_version_id = version.id
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ui_test_case_create_conflict",
            ) from exc
        self.db.refresh(ui_test_case)
        return self._serialize_case(ui_test_case, version)

    def get_case(
        self,
        *,
        case_public_id: str,
        current_user: User,
    ) -> UiTestCaseRead:
        ui_test_case = self._get_case(case_public_id)
        self._require_view(current_user, ui_test_case.project_id)
        return self._serialize_case(ui_test_case)

    def update_case(
        self,
        *,
        case_public_id: str,
        payload: UiTestCaseUpdateRequest,
        current_user: User,
    ) -> UiTestCaseRead:
        ui_test_case = self._get_case(case_public_id)
        self._require_manage(current_user, ui_test_case.project_id)
        changes = payload.model_dump(exclude_unset=True)
        if "default_environment_id" in changes:
            environment = self._get_environment(
                ui_test_case.project_id,
                changes["default_environment_id"],
            )
            ui_test_case.default_environment_id = environment.id
        if "tags" in changes:
            ui_test_case.tags_json = self._normalize_tags(changes["tags"] or [])
        for field_name in ("name", "description", "status"):
            if field_name in changes:
                setattr(ui_test_case, field_name, changes[field_name])
        self.db.commit()
        self.db.refresh(ui_test_case)
        return self._serialize_case(ui_test_case)

    def delete_case(
        self,
        *,
        case_public_id: str,
        current_user: User,
    ) -> None:
        ui_test_case = self._get_case(case_public_id)
        self._require_manage(current_user, ui_test_case.project_id)
        ui_test_case.is_deleted = True
        ui_test_case.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.commit()

    def list_versions(
        self,
        *,
        case_public_id: str,
        current_user: User,
    ) -> list[UiTestCaseVersionSummaryRead]:
        ui_test_case = self._get_case(case_public_id)
        self._require_view(current_user, ui_test_case.project_id)
        return [
            self._serialize_version_summary(version)
            for version in self.repository.list_versions(ui_test_case.id)
        ]

    def get_version(
        self,
        *,
        case_public_id: str,
        version_number: int,
        current_user: User,
    ) -> UiTestCaseVersionRead:
        ui_test_case = self._get_case(case_public_id)
        self._require_view(current_user, ui_test_case.project_id)
        version = self.repository.get_version(
            ui_test_case_id=ui_test_case.id,
            version_number=version_number,
        )
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_test_case_version_not_found",
            )
        return self._serialize_version(version)

    def create_version(
        self,
        *,
        case_public_id: str,
        payload: UiTestCaseVersionCreateRequest,
        current_user: User,
    ) -> UiTestCaseVersionRead:
        ui_test_case = self._get_case(case_public_id, for_update=True)
        self._require_manage(current_user, ui_test_case.project_id)
        environment = self._get_environment(
            ui_test_case.project_id,
            ui_test_case.default_environment_id,
        )
        validation = self._validate_dsl(payload.dsl, environment=environment)
        checksum = validation.checksum.removeprefix("sha256:")
        current_version = ui_test_case.current_version
        if current_version is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ui_test_case_current_version_missing",
            )
        if current_version.checksum_sha256 == checksum:
            return self._serialize_version(current_version)
        if current_version.version_number != payload.base_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "UI 用例版本冲突",
                    "error": "case_version_conflict",
                    "current_version": current_version.version_number,
                },
            )
        version = UiTestCaseVersion(
            ui_test_case_id=ui_test_case.id,
            version_number=current_version.version_number + 1,
            schema_version="ui-case-v1",
            dsl_json=validation.normalized_dsl,
            checksum_sha256=checksum,
            required_secret_refs_json=validation.required_secret_refs,
            based_on_version_id=current_version.id,
            change_summary=payload.change_summary,
            created_by_id=current_user.id,
        )
        try:
            self.repository.add_version(version)
            ui_test_case.current_version_id = version.id
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="case_version_conflict",
            ) from exc
        self.db.refresh(version)
        return self._serialize_version(version)

    def get_case_model_for_execution(
        self,
        *,
        case_public_id: str,
        project_id: int,
    ) -> UiTestCase:
        ui_test_case = self.repository.get_by_public_id(
            case_public_id,
            project_id=project_id,
        )
        if ui_test_case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_test_case_not_found",
            )
        return ui_test_case

    def _validate_dsl(
        self,
        dsl: UiCaseDsl,
        *,
        environment: ProjectEnvironment | None,
    ) -> UiTestCaseValidationRead:
        if len(dsl.steps) > settings.UI_CASE_MAX_STEPS:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="ui_case_step_limit_exceeded",
            )
        canonical = dsl.canonical_dict()
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > settings.UI_CASE_MAX_DSL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="ui_case_dsl_too_large",
            )
        warnings: list[dict[str, Any]] = []
        for step in dsl.steps:
            if step.operation == "navigate":
                self._validate_navigation_target(
                    str(step.input_value or ""),
                    environment=environment,
                )
            if step.locator_by == "xpath":
                warnings.append(
                    {
                        "step_id": step.id,
                        "code": "xpath_locator_risk",
                        "message": "XPath 定位器可维护性较低，优先使用 role、label 或 test_id",
                    }
                )
            if step.kind == "assertion" and step.operation == "screenshot":
                warnings.append(
                    {
                        "step_id": step.id,
                        "code": "desktop_runtime_capability_required",
                        "message": "执行前必须由 Desktop capability 确认该操作已实现",
                    }
                )
        text = encoded.decode("utf-8")
        required_secret_refs = sorted(set(SECRET_REFERENCE_RE.findall(text)))
        return UiTestCaseValidationRead(
            checksum=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            step_count=len(dsl.steps),
            required_secret_refs=required_secret_refs,
            warnings=warnings,
            normalized_dsl=canonical,
        )

    @staticmethod
    def _validate_navigation_target(
        target: str,
        *,
        environment: ProjectEnvironment | None,
    ) -> None:
        normalized = target.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ui_case_navigation_target_required",
            )
        if normalized.startswith("${env.") or normalized.startswith("/"):
            return
        parsed = urlparse(normalized)
        if parsed.scheme == "testauto" and parsed.netloc == "smoke":
            return
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ui_case_navigation_scheme_forbidden",
            )
        if environment is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ui_case_environment_required_for_absolute_url",
            )
        environment_host = urlparse(environment.base_url).hostname
        if not environment_host or not _same_navigation_host(parsed.hostname, environment_host):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ui_case_navigation_host_forbidden",
            )

    def _normalize_tags(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = str(value).strip()
            if not tag:
                continue
            if len(tag) > 64:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="ui_test_case_tag_too_long",
                )
            if tag not in seen:
                seen.add(tag)
                normalized.append(tag)
        if len(normalized) > settings.UI_CASE_MAX_TAGS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ui_test_case_tag_limit_exceeded",
            )
        return normalized

    def _get_environment(
        self,
        project_id: int,
        environment_id: int | None,
    ) -> ProjectEnvironment:
        if environment_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ui_test_case_default_environment_required",
            )
        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_test_case_environment_not_found",
            )
        return environment

    def _get_case(
        self,
        case_public_id: str,
        *,
        for_update: bool = False,
    ) -> UiTestCase:
        ui_test_case = self.repository.get_by_public_id(
            case_public_id,
            for_update=for_update,
        )
        if ui_test_case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_test_case_not_found",
            )
        return ui_test_case

    def _require_view(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )

    def _require_manage(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )

    def _serialize_list_item(self, ui_test_case: UiTestCase) -> UiTestCaseListItemRead:
        version = ui_test_case.current_version
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ui_test_case_current_version_missing",
            )
        return UiTestCaseListItemRead(
            case_id=ui_test_case.public_id,
            project_id=ui_test_case.project_id,
            default_environment_id=ui_test_case.default_environment_id,
            default_environment_name=(
                ui_test_case.default_environment.name
                if ui_test_case.default_environment is not None
                else None
            ),
            name=ui_test_case.name,
            description=ui_test_case.description,
            status=ui_test_case.status,
            tags=ui_test_case.tags_json or [],
            current_version=version.version_number,
            step_count=len((version.dsl_json or {}).get("steps", [])),
            checksum=f"sha256:{version.checksum_sha256}",
            created_by_id=ui_test_case.created_by_id,
            created_at=ui_test_case.created_at,
            updated_at=ui_test_case.updated_at,
        )

    def _serialize_case(
        self,
        ui_test_case: UiTestCase,
        version: UiTestCaseVersion | None = None,
    ) -> UiTestCaseRead:
        version = version or ui_test_case.current_version
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ui_test_case_current_version_missing",
            )
        item = self._serialize_list_item_with_version(ui_test_case, version)
        return UiTestCaseRead(
            **item.model_dump(),
            current_version_detail=self._serialize_version(version),
        )

    def _serialize_list_item_with_version(
        self,
        ui_test_case: UiTestCase,
        version: UiTestCaseVersion,
    ) -> UiTestCaseListItemRead:
        return UiTestCaseListItemRead(
            case_id=ui_test_case.public_id,
            project_id=ui_test_case.project_id,
            default_environment_id=ui_test_case.default_environment_id,
            default_environment_name=(
                ui_test_case.default_environment.name
                if ui_test_case.default_environment is not None
                else None
            ),
            name=ui_test_case.name,
            description=ui_test_case.description,
            status=ui_test_case.status,
            tags=ui_test_case.tags_json or [],
            current_version=version.version_number,
            step_count=len((version.dsl_json or {}).get("steps", [])),
            checksum=f"sha256:{version.checksum_sha256}",
            created_by_id=ui_test_case.created_by_id,
            created_at=ui_test_case.created_at,
            updated_at=ui_test_case.updated_at,
        )

    @staticmethod
    def _serialize_version_summary(
        version: UiTestCaseVersion,
    ) -> UiTestCaseVersionSummaryRead:
        return UiTestCaseVersionSummaryRead(
            version=version.version_number,
            schema_version=version.schema_version,
            checksum=f"sha256:{version.checksum_sha256}",
            step_count=len((version.dsl_json or {}).get("steps", [])),
            required_secret_refs=version.required_secret_refs_json or [],
            based_on_version=(
                version.based_on_version.version_number
                if version.based_on_version is not None
                else None
            ),
            change_summary=version.change_summary,
            created_by_id=version.created_by_id,
            created_at=version.created_at,
        )

    @classmethod
    def _serialize_version(cls, version: UiTestCaseVersion) -> UiTestCaseVersionRead:
        summary = cls._serialize_version_summary(version)
        return UiTestCaseVersionRead(
            **summary.model_dump(),
            dsl=version.dsl_json or {},
        )
