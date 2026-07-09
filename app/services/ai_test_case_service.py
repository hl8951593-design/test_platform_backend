import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.ai_skills import get_ai_skill
from app.ai_skills.base import AISkillRunner
from app.ai_skills.base import load_model_json
from app.core.permissions import ProjectPermission
from app.core.sensitive_data import mask_sensitive
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.schemas.ai import (
    AIGeneratedTestCaseResponse,
    AIChatMessage,
    AIChatRequest,
    AIHttpTestCaseDescriptionSummaryRequest,
    AIHttpTestCaseDescriptionSummaryResponse,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_run_event_service import AIRunTrace
from app.services.permission_service import PermissionService


class AITestCaseService:
    skill_id = "http-test-case"

    def __init__(self, db: Session):
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.test_case_repository = TestCaseRepository(db)
        self.permission_service = PermissionService(db)
        self.ai_service = AIService()

    def generate_test_cases(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: AITestCaseGenerateRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedTestCaseResponse:
        environment, variables = self._context(project_id, environment_id, current_user)
        context = {
            "mode": "generate",
            "project_id": project_id,
            "environment_id": environment_id,
            "environment": environment,
            "variables": variables,
            "payload": payload,
            "include_assertions": payload.include_assertions,
        }
        skill = get_ai_skill(self.skill_id)
        return self._runner().run_traced(skill, context, trace) if trace else self._runner().run(skill, context)

    def expand_test_cases(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        payload: AITestCaseExpandRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedTestCaseResponse:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        source_case = self.test_case_repository.get_by_id(
            project_id=project_id,
            test_case_id=test_case_id,
        )
        if source_case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")

        selected_environment_id = (
            environment_id
            or source_case.environment_id
            or (source_case.environment_ids[0] if source_case.environment_ids else None)
        )
        if selected_environment_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试用例未绑定环境")

        environment, variables = self._context(project_id, selected_environment_id, current_user)
        source_case_data = self._source_case_to_dict(source_case)
        context = {
            "mode": "expand",
            "project_id": project_id,
            "environment_id": selected_environment_id,
            "environment": environment,
            "variables": variables,
            "payload": payload,
            "include_assertions": payload.include_assertions,
            "source_test_case": source_case_data,
        }
        skill = get_ai_skill(self.skill_id)
        return self._runner().run_traced(skill, context, trace) if trace else self._runner().run(skill, context)

    def summarize_description(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        source_id: int | None,
        payload: AIHttpTestCaseDescriptionSummaryRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIHttpTestCaseDescriptionSummaryResponse:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        source_case_id = source_id or payload.test_case_id
        source_case = None
        if source_case_id is not None:
            source_case = self.test_case_repository.get_by_id(
                project_id=project_id,
                test_case_id=source_case_id,
            )
            if source_case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")

        context = self._description_summary_context(
            project_id=project_id,
            environment_id=environment_id,
            source_id=source_case_id,
            payload=payload,
            source_case=source_case,
        )
        request = AIChatRequest(
            messages=[
                AIChatMessage(
                    role="system",
                    content=(
                        "你是接口测试用例描述总结助手。只输出合法 JSON，不要 Markdown，不要解释。"
                        "根对象只能包含 description、source_summary、warnings 三个字段。"
                        "严格使用结构 {\"description\":\"\",\"source_summary\":\"request\",\"warnings\":[]}。"
                        "description 用于保存到测试用例描述字段。mode=request 时输出一到两句中文，说明接口用途和请求结构。"
                        "mode=request_response 时输出两到四句中文，必须更完整地说明接口用途、请求结构、调试结果和响应数据结构；"
                        "响应结构请使用“响应结构：...”短句，明确写出关键路径，例如 code、data.total、data.records[]。"
                        "不要复制完整请求或响应 JSON。"
                        "source_summary 只能是 request 或 request_response，与输入 mode 保持一致。"
                        "warnings 必须是字符串数组；不确定的信息写入 warnings。"
                    ),
                ),
                AIChatMessage(
                    role="user",
                    content=json.dumps(context, ensure_ascii=False, indent=2),
                ),
            ],
            thinking="disabled",
            temperature=0.1,
            max_tokens=1000,
            response_format="json",
        )
        if trace is not None:
            trace.model_started(request.model)
        response = self.ai_service.chat(request)
        if trace is not None:
            trace.model_delta(response.content)
            trace.model_completed(model=getattr(response, "model", None), usage=getattr(response, "usage", None))
        try:
            raw = load_model_json(response.content)
        except ValueError:
            raw = self._fallback_description_summary(context)
        normalized = self._normalize_description_summary(raw, context)
        return AIHttpTestCaseDescriptionSummaryResponse.model_validate(normalized)

    def _context(self, project_id: int, environment_id: int, current_user: User):
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        return environment, self.project_repository.list_environment_variables(environment_id=environment_id)

    def _runner(self) -> AISkillRunner:
        return AISkillRunner(self.ai_service)

    def _description_summary_context(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        source_id: int | None,
        payload: AIHttpTestCaseDescriptionSummaryRequest,
        source_case: Any | None,
    ) -> dict[str, Any]:
        source_case_data = self._source_case_to_dict(source_case) if source_case is not None else None
        request_data = dict(payload.request or {})
        if source_case_data:
            request_data = {
                "environment_id": payload.environment_id or source_case_data.get("environment_id"),
                "environment_ids": payload.environment_ids or source_case_data.get("environment_ids") or [],
                "method": request_data.get("method") or source_case_data.get("method"),
                "path": request_data.get("path") or source_case_data.get("path"),
                "headers": request_data.get("headers", source_case_data.get("headers") or {}),
                "query_params": request_data.get("query_params", source_case_data.get("query_params") or {}),
                "body_type": request_data.get("body_type") or source_case_data.get("body_type") or "none",
                "body": request_data.get("body", source_case_data.get("body")),
                "assertions": request_data.get("assertions", source_case_data.get("assertions") or []),
                "extractors": request_data.get("extractors", source_case_data.get("extractors") or []),
            }

        response_data = self._normalize_summary_response(payload.response)
        response_structure = self._response_structure_summary(response_data)
        context = {
            "operation": "summarize_description",
            "project_id": project_id,
            "environment_id": environment_id or payload.environment_id or (source_case_data or {}).get("environment_id"),
            "source_id": source_id,
            "mode": payload.mode,
            "test_case": {
                "id": payload.test_case_id or source_id,
                "name": payload.name or (source_case_data or {}).get("name") or "",
                "protocol": payload.protocol,
                "existing_description": (source_case_data or {}).get("description"),
            },
            "request": self._mask_summary_payload(request_data),
            "response": self._mask_summary_payload(response_data) if response_data is not None else None,
            "response_structure": response_structure,
            "output_contract": {
                "description": (
                    "request 模式一到两句中文，少于 180 个字符；"
                    "request_response 模式两到四句中文，少于 420 个字符，并明确响应结构"
                ),
                "source_summary": payload.mode,
                "warnings": [],
            },
            "rules": [
                "description 用于测试用例 description 字段",
                "不要输出完整请求或响应 JSON",
                "不要编造响应字段；没有 response 时只总结请求意图和请求结构",
                "有 response_structure 时必须在 description 中体现关键响应路径",
            ],
        }
        return context

    def _normalize_summary_response(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        response = dict(value)
        for key in ("headers", "body", "assertions"):
            response[key] = self._coerce_json_if_possible(response.get(key))
        return response

    def _mask_summary_payload(self, value: Any) -> Any:
        return mask_sensitive(value)

    def _coerce_json_if_possible(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text or text[0] not in "{[":
            return value
        try:
            return json.loads(text)
        except ValueError:
            return value

    def _normalize_description_summary(self, raw: Any, context: dict[str, Any]) -> dict[str, Any]:
        data = raw if isinstance(raw, dict) else {}
        warnings = self._summary_string_list(data.get("warnings"))
        description = str(
            data.get("description")
            or data.get("summary")
            or data.get("content")
            or data.get("text")
            or ""
        ).strip()
        if not description:
            fallback = self._fallback_description_summary(context)
            description = fallback["description"]
            warnings.extend(fallback["warnings"])
        if self._should_append_response_structure(description, context):
            description = self._append_sentence(
                description,
                f"响应结构：{context['response_structure']}",
            )
        return {
            "description": self._compact_text(
                description,
                limit=420 if context["mode"] == "request_response" else 240,
            ),
            "source_summary": context["mode"],
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _summary_string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item not in (None, "")]
        if value in (None, ""):
            return []
        return [str(value)]

    def _fallback_description_summary(self, context: dict[str, Any]) -> dict[str, Any]:
        request = context.get("request") or {}
        response = context.get("response") or {}
        method = str(request.get("method") or "HTTP").upper()
        path = str(request.get("path") or "接口")
        name = str((context.get("test_case") or {}).get("name") or "")
        intent = name or f"{method} {path}"
        request_parts = []
        if request.get("query_params"):
            request_parts.append("query 参数")
        if request.get("body") not in (None, {}, [], ""):
            request_parts.append("请求体")
        request_hint = f"，请求包含{'、'.join(request_parts)}" if request_parts else ""
        response_structure = str(context.get("response_structure") or "").strip()
        response_hint = f"。响应结构：{response_structure}" if response_structure else ""
        return {
            "description": self._compact_text(f"该接口用于{intent}{request_hint}{response_hint}。", limit=420),
            "source_summary": context["mode"],
            "warnings": ["AI 未返回可用描述，已根据请求/响应结构生成兜底描述"],
        }

    def _compact_text(self, value: str, *, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _response_structure_summary(self, response: dict[str, Any] | None) -> str:
        if not isinstance(response, dict):
            return ""
        parts: list[str] = []
        status_code = response.get("status_code")
        if status_code is not None:
            parts.append(f"HTTP {status_code}")
        body = response.get("body")
        scalar_paths, list_summaries = self._response_body_paths(body)
        if scalar_paths:
            parts.append("body字段：" + "、".join(scalar_paths[:12]))
        parts.extend(list_summaries[:3])
        if not parts and body is not None:
            parts.append(f"响应体类型：{self._summary_value_type(body)}")
        return "；".join(parts)

    def _response_body_paths(self, value: Any) -> tuple[list[str], list[str]]:
        scalar_paths: list[str] = []
        list_summaries: list[str] = []

        def walk(item: Any, path: str) -> None:
            if len(scalar_paths) >= 20:
                return
            if isinstance(item, dict):
                if not item and path:
                    scalar_paths.append(path)
                    return
                for key, nested in item.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    walk(nested, child_path)
                return
            if isinstance(item, list):
                list_path = f"{path}[]"
                scalar_paths.append(list_path)
                if item and isinstance(item[0], dict):
                    keys = list(item[0].keys())[:8]
                    if keys:
                        list_summaries.append(f"{list_path}项字段：" + "、".join(str(key) for key in keys))
                elif item:
                    list_summaries.append(f"{list_path}项类型：{self._summary_value_type(item[0])}")
                return
            if path:
                scalar_paths.append(path)

        walk(value, "")
        return scalar_paths, list_summaries

    def _summary_value_type(self, value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and not isinstance(value, bool):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        if value is None:
            return "null"
        return "string"

    def _should_append_response_structure(self, description: str, context: dict[str, Any]) -> bool:
        response_structure = str(context.get("response_structure") or "").strip()
        if context.get("mode") != "request_response" or not response_structure:
            return False
        text = str(description or "")
        if "响应结构" in text:
            return False
        markers = self._response_structure_markers(response_structure)
        return not any(marker and marker in text for marker in markers)

    def _response_structure_markers(self, response_structure: str) -> list[str]:
        markers: list[str] = []
        for separator in ("；", "、", "："):
            response_structure = response_structure.replace(separator, " ")
        for token in response_structure.split():
            cleaned = token.strip("。，,;:()（）")
            if "." in cleaned or "[]" in cleaned:
                markers.append(cleaned)
        return markers

    def _append_sentence(self, description: str, sentence: str) -> str:
        prefix = str(description or "").strip()
        suffix = str(sentence or "").strip().rstrip("。")
        if not prefix:
            return suffix + "。"
        if prefix.endswith(("。", "！", "？")):
            return prefix + suffix + "。"
        return prefix + "。" + suffix + "。"

    def _source_case_to_dict(self, source_case: Any) -> dict[str, Any]:
        return {
            "id": source_case.id,
            "name": source_case.name,
            "description": source_case.description,
            "environment_id": source_case.environment_id,
            "environment_ids": source_case.environment_ids,
            "method": source_case.method,
            "path": source_case.path,
            "headers": source_case.headers or {},
            "query_params": source_case.query_params or {},
            "body_type": source_case.body_type,
            "body": source_case.body,
            "assertions": source_case.assertions or [],
            "extractors": source_case.extractors or [],
        }
