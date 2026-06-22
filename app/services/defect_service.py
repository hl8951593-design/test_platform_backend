from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.defect import Defect
from app.models.user import User
from app.repositories.defect_repository import DefectRepository
from app.schemas.defect import (
    DefectCreateRequest,
    DefectStatusUpdateRequest,
    DefectUpdateRequest,
)
from app.services.permission_service import PermissionService
from app.services.media_service import MediaService


ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "new": {"active", "confirmed", "closed"},
    "active": {"confirmed", "fixed", "closed"},
    "confirmed": {"fixed", "closed"},
    "fixed": {"verified", "reopened"},
    "verified": {"closed", "reopened"},
    "closed": {"reopened"},
    "reopened": {"active", "confirmed", "fixed", "closed"},
}


class DefectService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = DefectRepository(db)
        self.permission_service = PermissionService(db)
        self.media_service = MediaService(db)

    def list_defects(
        self,
        *,
        project_id: int,
        current_user: User,
        keyword: str | None,
        status: str | None,
        urgency: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_DEFECT.value,
        )
        items, total = self.repository.list_by_project(
            project_id=project_id,
            keyword=keyword,
            status=status,
            urgency=urgency,
            page=page,
            page_size=page_size,
        )
        items = [self.media_service.attach_download_urls(item) for item in items]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_defect(self, *, project_id: int, defect_id: int, current_user: User) -> Defect:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_DEFECT.value,
        )
        defect = self._get_defect_or_404(project_id=project_id, defect_id=defect_id)
        return self.media_service.attach_download_urls(defect)

    def create_defect(
        self,
        *,
        project_id: int,
        payload: DefectCreateRequest,
        current_user: User,
    ) -> Defect:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.CREATE_DEFECT.value,
        )
        attachments = self.media_service.resolve_pending_attachments(
            project_id=project_id,
            media_ids=payload.media_ids,
            current_user=current_user,
        )
        defect = self.repository.create(
            project_id=project_id,
            title=payload.title,
            assignee=payload.assignee,
            bug_type=payload.bug_type,
            urgency=payload.urgency,
            status=payload.status,
            content_html=sanitize_defect_html(payload.content_html),
            reporter_id=current_user.id,
        )
        if attachments:
            defect = self.repository.replace_attachments(defect=defect, attachments=attachments)
        return self.media_service.attach_download_urls(defect)

    def update_defect(
        self,
        *,
        project_id: int,
        defect_id: int,
        payload: DefectUpdateRequest,
        current_user: User,
    ) -> Defect:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.UPDATE_DEFECT.value,
        )
        defect = self._get_defect_or_404(project_id=project_id, defect_id=defect_id)
        self._validate_transition(defect.status, payload.status)
        attachments = None
        if payload.media_ids is not None:
            attachments = self.media_service.resolve_pending_attachments(
                project_id=project_id,
                media_ids=payload.media_ids,
                current_user=current_user,
                defect_id=defect_id,
            )
        updated = self.repository.update(
            defect=defect,
            title=payload.title,
            assignee=payload.assignee,
            bug_type=payload.bug_type,
            urgency=payload.urgency,
            status=payload.status,
            content_html=sanitize_defect_html(payload.content_html),
        )
        if attachments is not None:
            updated = self.repository.replace_attachments(
                defect=updated,
                attachments=attachments,
            )
        return self.media_service.attach_download_urls(updated)

    def delete_defect(self, *, project_id: int, defect_id: int, current_user: User) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.DELETE_DEFECT.value,
        )
        defect = self._get_defect_or_404(project_id=project_id, defect_id=defect_id)
        for media in getattr(defect, "attachments", ()):
            self.media_service.storage.delete(bucket=media.bucket, object_key=media.object_key)
        self.repository.delete(defect)

    def transition_status(
        self,
        *,
        project_id: int,
        defect_id: int,
        payload: DefectStatusUpdateRequest,
        current_user: User,
    ) -> Defect:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.TRANSITION_DEFECT.value,
        )
        defect = self._get_defect_or_404(project_id=project_id, defect_id=defect_id)
        self._validate_transition(defect.status, payload.status)
        if defect.status == payload.status:
            return defect
        return self.repository.update_status(defect=defect, status=payload.status)

    def _get_defect_or_404(self, *, project_id: int, defect_id: int) -> Defect:
        defect = self.repository.get_by_id(project_id=project_id, defect_id=defect_id)
        if defect is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")
        return defect

    def _validate_transition(self, current_status: str, next_status: str) -> None:
        if current_status == next_status:
            return
        if next_status not in ALLOWED_STATUS_TRANSITIONS.get(current_status, set()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "缺陷状态流转不合法",
                    "current_status": current_status,
                    "target_status": next_status,
                },
            )


class _DefectHTMLSanitizer(HTMLParser):
    allowed_tags = {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
    void_tags = {"br", "hr", "img"}
    blocked_tags = {"script", "style", "iframe", "object", "embed", "meta", "link"}
    global_attrs = {"class", "title"}
    tag_attrs = {
        "a": {"href", "target", "rel"},
        "img": {"src", "alt", "width", "height"},
        "td": {"colspan", "rowspan"},
        "th": {"colspan", "rowspan"},
    }
    data_image_pattern = re.compile(r"^data:image/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$", re.I)

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.blocked_tags:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in self.allowed_tags:
            return
        cleaned_attrs = self._clean_attrs(tag, attrs)
        attr_text = "".join(f' {name}="{escape(value, quote=True)}"' for name, value in cleaned_attrs)
        if tag in self.void_tags:
            self.parts.append(f"<{tag}{attr_text}>")
        else:
            self.parts.append(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.blocked_tags and self.blocked_depth:
            self.blocked_depth -= 1
            return
        if self.blocked_depth or tag not in self.allowed_tags or tag in self.void_tags:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self.blocked_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.blocked_depth:
            self.parts.append(f"&#{name};")

    def _clean_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
        allowed = self.global_attrs | self.tag_attrs.get(tag, set())
        cleaned: list[tuple[str, str]] = []
        for name, value in attrs:
            attr_name = name.lower()
            attr_value = value or ""
            if attr_name.startswith("on") or attr_name not in allowed:
                continue
            if attr_name in {"href", "src"} and not self._is_safe_url(attr_value):
                continue
            if attr_name == "target" and attr_value not in {"_blank", "_self"}:
                continue
            cleaned.append((attr_name, attr_value))
        if tag == "a" and any(name == "target" and value == "_blank" for name, value in cleaned):
            rel_values = {value for name, value in cleaned if name == "rel"}
            if "noopener noreferrer" not in rel_values:
                cleaned.append(("rel", "noopener noreferrer"))
        return cleaned

    def _is_safe_url(self, value: str) -> bool:
        stripped = value.strip()
        if not stripped:
            return False
        lower = stripped.lower()
        if lower.startswith(("data:", "javascript:", "vbscript:")):
            return bool(self.data_image_pattern.match(stripped))
        parsed = urlparse(stripped)
        return parsed.scheme in {"", "http", "https"}


def sanitize_defect_html(content_html: str) -> str:
    sanitizer = _DefectHTMLSanitizer()
    sanitizer.feed(content_html)
    sanitizer.close()
    return "".join(sanitizer.parts).strip()
