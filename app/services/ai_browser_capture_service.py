import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.user import User
from app.schemas.ai import (
    AIChatMessage,
    AIChatRequest,
    AIBrowserCaptureAnalysisResult,
    AIBrowserCaptureAnalyzeRequest,
    AIBrowserCaptureBatchAnalyzeRequest,
    AIBrowserCaptureBatchGenerateRequest,
    AIBrowserCaptureGenerateRequest,
    AIBrowserCaptureRelationsRequest,
    AIBrowserCaptureScenarioRequest,
    AIExecutionDiagnoseRequest,
    AITestCaseGenerateRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_test_case_service import AITestCaseService
from app.services.ai_websocket_test_case_service import AIWebSocketTestCaseService
from app.services.browser_capture_service import BrowserCaptureService
from app.services.permission_service import PermissionService


class AIBrowserCaptureService:
    MAX_ANALYSIS_TEST_POINTS = 6
    MAX_ANALYSIS_RISKS = 6
    MAX_ANALYSIS_FIELDS_PER_SECTION = 80

    SENSITIVE_KEYWORDS = {
        "authorization",
        "cookie",
        "set-cookie",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "apikey",
        "api_key",
        "auth",
    }

    def __init__(self, db: Session):
        self.db = db
        self.capture_service = BrowserCaptureService(db)
        self.permission_service = PermissionService(db)

    def generate_cases(self, *, project_id: int, capture_id: int, entry_id: int, payload: AIBrowserCaptureGenerateRequest, current_user: User):
        entry = self.capture_service.get_entry(project_id=project_id, capture_id=capture_id, entry_id=entry_id, current_user=current_user, manage=True)
        source = json.dumps({"name": entry.name, "method": entry.method, "path": entry.path, "source_url": entry.source_url,
                             "request": entry.request_data, "response": entry.response_data, "draft": entry.draft_data},
                            ensure_ascii=False, indent=2)
        capture = entry.capture
        if entry.protocol == "websocket":
            result = AIWebSocketTestCaseService(self.db).generate_test_cases(
                project_id=project_id, environment_id=capture.environment_id,
                payload=AIWebSocketTestCaseGenerateRequest(websocket_text=source, generate_count=payload.generate_count,
                                                           include_assertions=payload.include_assertions, extra_requirements=payload.extra_requirements),
                current_user=current_user,
            )
        else:
            result = AITestCaseService(self.db).generate_test_cases(
                project_id=project_id, environment_id=capture.environment_id,
                payload=AITestCaseGenerateRequest(interface_text=source, request_method=entry.method,
                                                  generate_count=payload.generate_count, include_assertions=payload.include_assertions,
                                                  extra_requirements=payload.extra_requirements),
                current_user=current_user,
            )
        entry.ai_analysis = result.model_dump(mode="json")
        entry.ai_analysis_model = getattr(result, "model", None)
        entry.ai_analyzed_at = datetime.now(UTC)
        entry.status = "review_required"
        self.db.commit()
        return result

    def analyze_draft(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: AIBrowserCaptureAnalyzeRequest,
        current_user: User,
    ) -> dict[str, Any]:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.ANALYZE_AI.value
        )
        self.capture_service._require_environment(project_id, environment_id)
        protocol = payload.protocol or self._infer_protocol(payload.draft_data)
        return self._analyze_payload(
            protocol=protocol,
            draft_data=payload.draft_data,
            analysis_focus=payload.analysis_focus,
            include_examples=payload.include_examples,
        )

    def analyze_entry(
        self,
        *,
        project_id: int,
        capture_id: int,
        entry_id: int,
        payload: AIBrowserCaptureAnalyzeRequest,
        current_user: User,
    ) -> dict[str, Any]:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.ANALYZE_AI.value
        )
        entry = self.capture_service.get_entry(
            project_id=project_id,
            capture_id=capture_id,
            entry_id=entry_id,
            current_user=current_user,
            manage=False,
        )
        entry.status = "analyzing"
        self.db.commit()
        try:
            result = self._analyze_payload(
                protocol=payload.protocol or entry.protocol,
                draft_data={
                    "name": entry.name,
                    "method": entry.method,
                    "path": entry.path,
                    "source_url": entry.source_url,
                    "request": entry.request_data,
                    "response": entry.response_data,
                    "draft": entry.draft_data,
                },
                analysis_focus=payload.analysis_focus,
                include_examples=payload.include_examples,
            )
        except Exception:
            entry.status = "failed"
            self.db.commit()
            raise
        entry.ai_analysis = result
        entry.ai_analysis_model = result.get("model")
        entry.ai_analyzed_at = datetime.fromisoformat(result["analyzed_at"])
        entry.status = "review_required"
        self.db.commit()
        return result

    def generate_batch(self, *, project_id: int, capture_id: int, payload: AIBrowserCaptureBatchGenerateRequest,
                       current_user: User) -> dict[str, Any]:
        results = []
        request = AIBrowserCaptureGenerateRequest(
            generate_count=payload.generate_count,
            include_assertions=payload.include_assertions,
            extra_requirements=payload.extra_requirements,
        )
        for entry_id in dict.fromkeys(payload.entry_ids):
            try:
                generated = self.generate_cases(
                    project_id=project_id, capture_id=capture_id, entry_id=entry_id,
                    payload=request, current_user=current_user,
                )
                results.append({"entry_id": entry_id, "ok": True, "result": generated.model_dump(mode="json")})
            except HTTPException as exc:
                self.db.rollback()
                results.append({"entry_id": entry_id, "ok": False, "error": str(exc.detail)})
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                results.append({"entry_id": entry_id, "ok": False, "error": str(exc)})
        return {"results": results, "success_count": sum(item["ok"] for item in results)}

    def analyze_relations(self, *, project_id: int, capture_id: int, payload: AIBrowserCaptureRelationsRequest,
                          current_user: User) -> dict[str, Any]:
        entries = self._selected_entries(
            project_id=project_id, capture_id=capture_id, entry_ids=payload.entry_ids, current_user=current_user
        )
        relations = []
        for producer_index, producer in enumerate(entries):
            response_values = self._scalar_paths(producer.response_data or {})
            for consumer in entries[producer_index + 1:]:
                request_values = self._scalar_paths(consumer.request_data or {})
                for response_path, response_value in response_values.items():
                    if not self._relation_candidate(response_path, response_value):
                        continue
                    for request_path, request_value in request_values.items():
                        if response_value == request_value and self._paths_compatible(
                            response_path, request_path, response_value
                        ):
                            variable = self._variable_name(response_path)
                            relations.append({
                                "producer_entry_id": producer.id,
                                "producer_name": producer.name,
                                "response_path": response_path,
                                "consumer_entry_id": consumer.id,
                                "consumer_name": consumer.name,
                                "request_path": request_path,
                                "variable": variable,
                                "replacement": "{{" + variable + "}}",
                                "confidence": 0.95 if isinstance(response_value, str) else 0.8,
                            })
        return {
            "capture_id": capture_id,
            "entry_ids": [entry.id for entry in entries],
            "relations": relations,
            "warnings": [] if relations else ["未发现可确定的跨接口字段依赖，请人工检查动态值。"],
        }

    def analyze_batch_context(
        self,
        *,
        project_id: int,
        capture_id: int,
        payload: AIBrowserCaptureBatchAnalyzeRequest,
        current_user: User,
    ) -> dict[str, Any]:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.ANALYZE_AI.value
        )
        entries = self._selected_entries(
            project_id=project_id,
            capture_id=capture_id,
            entry_ids=payload.entry_ids,
            current_user=current_user,
        )
        nodes = [self._batch_node(entry) for entry in entries]
        dependencies = self._batch_dependencies(entries)
        self._attach_node_dependencies(nodes, dependencies)
        suggestions = self._binding_suggestions(dependencies) if payload.include_suggestions else []
        warnings = [] if dependencies else ["未发现明确的接口上下文传递依赖，请检查是否缺少响应样本或动态值。"]
        return {
            "capture_id": capture_id,
            "entry_ids": [entry.id for entry in entries],
            "summary": {
                "entry_count": len(entries),
                "dependency_count": len(dependencies),
                "suggestion_count": len(suggestions),
            },
            "nodes": nodes if payload.include_nodes else [],
            "dependencies": dependencies,
            "suggested_bindings": suggestions,
            "warnings": warnings,
        }

    def generate_scenario(self, *, project_id: int, capture_id: int, payload: AIBrowserCaptureScenarioRequest,
                          current_user: User) -> dict[str, Any]:
        analysis = self.analyze_relations(
            project_id=project_id, capture_id=capture_id,
            payload=AIBrowserCaptureRelationsRequest(entry_ids=payload.entry_ids), current_user=current_user,
        )
        entries = self._selected_entries(
            project_id=project_id, capture_id=capture_id, entry_ids=analysis["entry_ids"], current_user=current_user
        )
        relations_by_consumer: dict[int, list[dict[str, Any]]] = {}
        for relation in analysis["relations"]:
            relations_by_consumer.setdefault(relation["consumer_entry_id"], []).append(relation)
        return {
            "name": payload.name or f"浏览器采集场景 #{capture_id}",
            "description": "由 Chrome 插件采集顺序与接口依赖分析生成，导入正式用例后可创建为可执行场景。",
            "capture_id": capture_id,
            "steps": [
                {
                    "order": index,
                    "entry_id": entry.id,
                    "name": entry.name,
                    "kind": "websocket_case" if entry.protocol == "websocket" else "api_case",
                    "method": entry.method,
                    "path": entry.path,
                    "required_relations": relations_by_consumer.get(entry.id, []),
                }
                for index, entry in enumerate(entries, start=1)
            ],
            "relations": analysis["relations"],
            "warnings": analysis["warnings"],
        }

    def diagnose_execution(self, *, project_id: int, payload: AIExecutionDiagnoseRequest, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.ANALYZE_AI.value)
        response = AIService().chat(AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=(
                    "你是接口自动化测试失败诊断助手。只输出合法 JSON，包含 summary、probable_causes、"
                    "evidence、suggestions、risk_level。不要编造未提供的日志、字段或业务规则。"
                )),
                AIChatMessage(role="user", content=json.dumps({
                    "protocol": payload.protocol,
                    "draft": payload.draft_data,
                    "execution": payload.execution_data,
                }, ensure_ascii=False, indent=2)),
            ],
            thinking="disabled", temperature=0.1, max_tokens=2500, response_format="json",
        ))
        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            result = {"summary": response.content, "probable_causes": [], "evidence": [], "suggestions": [],
                      "risk_level": "unknown"}
        result["model"] = response.model
        return result

    def _analyze_payload(
        self,
        *,
        protocol: str,
        draft_data: dict[str, Any],
        analysis_focus: list[str],
        include_examples: bool,
    ) -> dict[str, Any]:
        sanitized = self._bounded_sample(self._sanitize(draft_data))
        analysis_context = self._build_analysis_context(protocol=protocol, draft_data=draft_data)
        safe_context = self._analysis_prompt_context(analysis_context)
        expected_contract = self._analysis_output_contract()
        output_limits = {
            "max_summary_purpose_chars": 120,
            "max_test_points": self.MAX_ANALYSIS_TEST_POINTS,
            "max_risks": self.MAX_ANALYSIS_RISKS,
            "max_fields_per_section": self.MAX_ANALYSIS_FIELDS_PER_SECTION,
            "max_text_chars": 240,
        }
        response = AIService().chat(AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=(
                    "你是接口自动化测试采集分析助手。严格返回一个 JSON object，不要 Markdown、不要解释、不要代码块。"
                    "顶层字段只能是 summary、request、response、test_points、risks、automation、warnings。"
                    "summary 必须是 object；request 和 response 必须是 object；test_points、risks、warnings 必须是 array；"
                    "automation 必须是 object。缺省数组输出 []，缺省字符串输出空字符串，不要输出 null。"
                    "summary.purpose 是前端概览短文本，必须少于 120 个字符，只描述接口用途；"
                    "不要把完整 JSON、请求样本、响应样本、test_points、risks 或 automation 放入 summary.purpose。"
                    "必须按照用户消息中的 expected_output_contract 返回同构结构，不要新增字段名，不要把字段泛化成字符串。"
                    "必须遵守 output_limits：test_points 和 risks 不要超过限制数量；description、meaning、recommendation 必须简洁。"
                    "不要复制原始请求或响应样本，不要返回完整 headers/body，只返回字段结构与自动化要点。"
                    "必须根据 method、URL/path、query 参数、请求头、请求体、响应状态码、响应头和响应 body 结构判断接口用途。"
                    "request.fields 必须列出 query、headers、body 中可见字段；response.fields 必须列出响应状态和 body 字段。"
                    "敏感字段示例只能输出 ***。confidence 必须在 0 到 1；测试点和风险按优先级排序。"
                )),
                AIChatMessage(role="user", content=json.dumps({
                    "protocol": protocol,
                    "analysis_focus": analysis_focus,
                    "include_examples": include_examples,
                    "expected_output_contract": expected_contract,
                    "output_limits": output_limits,
                    "output_rules": [
                        "Return the same object shape as expected_output_contract.",
                        "Do not return summary as a string.",
                        "Do not return request or response as strings.",
                        "Do not include raw capture JSON in summary.purpose.",
                        "Do not copy raw request or response samples into the output.",
                        "Keep test_points and risks within output_limits.",
                        "Use [] for missing arrays and empty strings for missing text.",
                        "CamelCase plugin fields such as sourceUrl/queryParams/bodyType/responseStatus/responseHeaders are authoritative.",
                        "For HTML responses, describe response body as page/text content instead of leaving response.fields empty.",
                    ],
                    "request_context": safe_context["request_context"],
                    "response_schema": safe_context["response_schema"],
                    "automation_hints": safe_context["automation_hints"],
                    "sanitized_capture": sanitized,
                }, ensure_ascii=False, indent=2)),
            ],
            thinking="disabled", temperature=0.1, max_tokens=5000, response_format="json",
        ))
        try:
            raw = json.loads(response.content)
        except json.JSONDecodeError:
            raw = {"summary": {}, "warnings": ["AI 返回内容不是合法 JSON，已降级保存摘要。"]}
        analyzed_at = datetime.now(UTC).isoformat()
        raw = self._normalize_analysis_raw(raw)
        raw = self._enrich_analysis_raw(raw, analysis_context)
        result = AIBrowserCaptureAnalysisResult.model_validate(raw)
        result.model = response.model
        result.analyzed_at = analyzed_at
        return result.model_dump(mode="json")

    def _analysis_prompt_context(self, analysis_context: dict[str, Any]) -> dict[str, Any]:
        sanitized = self._sanitize(analysis_context)
        request_context = dict(self._dict(sanitized.get("request_context")))
        response_schema = dict(self._dict(sanitized.get("response_schema")))
        automation_hints = dict(self._dict(sanitized.get("automation_hints")))
        self._limit_prompt_fields(request_context, "request_fields")
        self._limit_prompt_fields(response_schema, "response_fields")
        return {
            "request_context": self._bounded_sample(request_context),
            "response_schema": self._bounded_sample(response_schema),
            "automation_hints": self._bounded_sample(automation_hints),
        }

    def _limit_prompt_fields(self, payload: dict[str, Any], key: str) -> None:
        fields = payload.get(key)
        if not isinstance(fields, list):
            return
        total = len(fields)
        limit = self.MAX_ANALYSIS_FIELDS_PER_SECTION
        if total <= limit:
            return
        payload[key] = fields[:limit]
        payload[f"{key}_truncated"] = {
            "returned": limit,
            "total": total,
        }

    def _analysis_output_contract(self) -> dict[str, Any]:
        field_contract = {
            "path": "query.companyId | headers.Authorization | body.data.id",
            "type": "string | integer | number | boolean | array | object | null",
            "meaning": "字段业务含义",
            "required": False,
            "constraints": [],
            "sensitive": False,
            "dynamic": False,
            "example": "示例值，敏感值必须为 ***",
        }
        return {
            "summary": {
                "name": "接口名称，少于 80 个字符",
                "purpose": "接口用途短句，少于 120 个字符，不包含 JSON",
                "business_domain": "业务域",
                "operation_type": "query | create | update | delete | business",
                "confidence": 0.0,
            },
            "request": {
                "description": "请求结构说明",
                "fields": [field_contract],
            },
            "response": {
                "description": "响应结构说明",
                "fields": [field_contract],
            },
            "test_points": [
                {
                    "category": "positive | negative | boundary | permission | security | performance",
                    "title": "测试点标题",
                    "description": "测试点说明",
                    "priority": "high | medium | low",
                    "test_data": {},
                    "expected_result": "预期结果",
                }
            ],
            "risks": [
                {
                    "level": "high | medium | low",
                    "title": "风险标题",
                    "description": "风险说明",
                    "recommendation": "处理建议",
                }
            ],
            "automation": {
                "assertions": [],
                "extractors": [],
                "dependencies": [],
                "data_setup": [],
                "cleanup": [],
            },
            "warnings": [],
        }

    def _selected_entries(self, *, project_id: int, capture_id: int, entry_ids: list[int] | None,
                          current_user: User):
        entries = list(reversed(self.capture_service.list_entries(
            project_id=project_id, capture_id=capture_id, current_user=current_user
        )))
        if entry_ids is None:
            return entries
        selected = set(entry_ids)
        result = [entry for entry in entries if entry.id in selected]
        if len(result) != len(selected):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部分采集草稿不存在")
        return result

    def _scalar_paths(self, value: Any, prefix: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {}
        if isinstance(value, dict):
            for key, item in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                result.update(self._scalar_paths(item, path))
        elif isinstance(value, list):
            for index, item in enumerate(value[:10]):
                result.update(self._scalar_paths(item, f"{prefix}.{index}"))
        elif value is not None and not isinstance(value, (dict, list)):
            result[prefix] = value
        return result

    def _relation_candidate(self, path: str, value: Any) -> bool:
        key = path.rsplit(".", 1)[-1].lower()
        return key not in {"status", "status_code", "code", "message", "success"} and (
            isinstance(value, str) and len(value) >= 6
            or isinstance(value, int) and not isinstance(value, bool) and value > 0
        )

    def _paths_compatible(self, response_path: str, request_path: str, value: Any) -> bool:
        if isinstance(value, str):
            return True
        return response_path.rsplit(".", 1)[-1].lower() == request_path.rsplit(".", 1)[-1].lower()

    def _variable_name(self, path: str) -> str:
        raw = path.rsplit(".", 1)[-1].replace("-", "_")
        return "".join(char if char.isalnum() or char == "_" else "_" for char in raw) or "captured_value"

    def _batch_node(self, entry) -> dict[str, Any]:
        return {
            "entry_id": entry.id,
            "name": entry.name,
            "protocol": entry.protocol,
            "method": entry.method,
            "path": entry.path,
            "source_url": entry.source_url,
            "produces": [self._candidate_view(item) for item in self._response_candidates(entry)],
            "consumes": [self._candidate_view(item) for item in self._request_candidates(entry)],
            "depends_on": [],
            "provides_to": [],
        }

    def _batch_dependencies(self, entries) -> list[dict[str, Any]]:
        dependencies: list[dict[str, Any]] = []
        seen: set[tuple[int, int, str, str]] = set()
        for producer_index, producer in enumerate(entries):
            producer_candidates = self._response_candidates(producer)
            for consumer in entries[producer_index + 1:]:
                consumer_candidates = self._request_candidates(consumer)
                for source in producer_candidates:
                    for target in consumer_candidates:
                        match = self._dependency_match(source, target)
                        if match is None:
                            continue
                        key = (producer.id, consumer.id, source["path"], target["path"])
                        if key in seen:
                            continue
                        seen.add(key)
                        variable = self._variable_name(source["path"])
                        dependencies.append({
                            "producer_entry_id": producer.id,
                            "producer_name": producer.name,
                            "producer_path": producer.path,
                            "consumer_entry_id": consumer.id,
                            "consumer_name": consumer.name,
                            "consumer_path": consumer.path,
                            "response_path": source["path"],
                            "request_path": target["path"],
                            "request_target": target["target"],
                            "variable": variable,
                            "replacement": "{{" + variable + "}}",
                            "confidence": match["confidence"],
                            "match_type": match["match_type"],
                            "reason": match["reason"],
                            "value_preview": self._safe_value_preview(source),
                        })
        return sorted(
            dependencies,
            key=lambda item: (
                item["consumer_entry_id"],
                -float(item["confidence"]),
                item["request_path"],
                item["response_path"],
            ),
        )

    def _response_candidates(self, entry) -> list[dict[str, Any]]:
        candidates = []
        for path, value in self._scalar_paths(entry.response_data or {}).items():
            if not self._relation_candidate(path, value):
                continue
            candidates.append({
                "path": path,
                "value": value,
                "key": path.rsplit(".", 1)[-1],
                "target": "response",
                "sensitive": self._is_sensitive_path(path),
            })
        return candidates

    def _request_candidates(self, entry) -> list[dict[str, Any]]:
        request_data = entry.request_data or {}
        candidates = []
        for path, value in self._scalar_paths(request_data).items():
            if path in {"method", "body_type"}:
                continue
            if self._is_sensitive_path(path) and not self._is_auth_header(path.rsplit(".", 1)[-1]):
                continue
            if isinstance(value, str) and not value:
                continue
            if value is None or isinstance(value, bool):
                continue
            candidates.append({
                "path": path,
                "value": value,
                "key": path.rsplit(".", 1)[-1],
                "target": self._request_target(path),
                "sensitive": self._is_sensitive_path(path),
            })
        return candidates

    def _dependency_match(self, source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
        source_value = source["value"]
        target_value = target["value"]
        if source_value == target_value and self._paths_compatible(source["path"], target["path"], source_value):
            return {
                "confidence": 0.96 if isinstance(source_value, str) else 0.86,
                "match_type": "exact_value",
                "reason": "响应字段值与后续请求字段值完全一致",
            }
        if isinstance(source_value, str) and isinstance(target_value, str) and source_value and source_value in target_value:
            return {
                "confidence": 0.9,
                "match_type": "contained_value",
                "reason": "响应字段值出现在后续请求字段值中",
            }
        if self._is_id_like(source["path"]) and source["key"].lower() == target["key"].lower():
            return {
                "confidence": 0.68,
                "match_type": "semantic_name",
                "reason": "响应字段名与后续请求字段名一致，疑似上下文传递",
            }
        return None

    def _request_target(self, path: str) -> str:
        if path.startswith("query_params."):
            return "query"
        if path.startswith("body."):
            return "body"
        if path.startswith("headers."):
            return "headers"
        if path in {"url", "path"} or path.startswith("path"):
            return "path"
        return "request"

    def _candidate_view(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "path": candidate["path"],
            "variable": self._variable_name(candidate["path"]),
            "target": candidate["target"],
            "type": self._value_type(candidate["value"]),
            "sensitive": bool(candidate.get("sensitive")),
            "value_preview": self._safe_value_preview(candidate),
        }

    def _safe_value_preview(self, candidate: dict[str, Any]) -> Any:
        if candidate.get("sensitive"):
            return "***"
        return self._preview(candidate.get("value"))

    def _attach_node_dependencies(self, nodes: list[dict[str, Any]], dependencies: list[dict[str, Any]]) -> None:
        by_id = {node["entry_id"]: node for node in nodes}
        for dependency in dependencies:
            consumer = by_id.get(dependency["consumer_entry_id"])
            producer = by_id.get(dependency["producer_entry_id"])
            if consumer is not None:
                consumer["depends_on"].append({
                    "entry_id": dependency["producer_entry_id"],
                    "variable": dependency["variable"],
                    "request_path": dependency["request_path"],
                    "response_path": dependency["response_path"],
                })
            if producer is not None:
                producer["provides_to"].append({
                    "entry_id": dependency["consumer_entry_id"],
                    "variable": dependency["variable"],
                    "request_path": dependency["request_path"],
                    "response_path": dependency["response_path"],
                })

    def _binding_suggestions(self, dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "consumer_entry_id": item["consumer_entry_id"],
                "consumer_name": item["consumer_name"],
                "request_target": item["request_target"],
                "request_path": item["request_path"],
                "replacement": item["replacement"],
                "source": {
                    "producer_entry_id": item["producer_entry_id"],
                    "producer_name": item["producer_name"],
                    "response_path": item["response_path"],
                },
                "confidence": item["confidence"],
            }
            for item in dependencies
        ]

    def _infer_protocol(self, draft_data: dict[str, Any]) -> str:
        value = str(draft_data.get("protocol") or draft_data.get("url") or draft_data.get("path") or "").lower()
        return "websocket" if value.startswith(("ws://", "wss://")) else "http"

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                if str(key) == "auth_headers" and isinstance(item, list):
                    sanitized[key] = [self._sanitize(value) for value in item]
                elif self._is_sensitive_key(str(key)):
                    sanitized[key] = "***"
                else:
                    sanitized[key] = self._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize(item) for item in value[:50]]
        if isinstance(value, str):
            lowered = value.lower()
            if "bearer " in lowered or "token=" in lowered:
                return "***"
            return value[:2000] + ("...<truncated>" if len(value) > 2000 else "")
        return value

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return any(keyword in normalized for keyword in self.SENSITIVE_KEYWORDS)

    def _is_sensitive_path(self, path: str) -> bool:
        return any(self._is_sensitive_key(part) for part in path.replace("[0]", "").split("."))

    def _bounded_sample(self, value: Any, max_chars: int = 8000) -> Any:
        text = json.dumps(value, ensure_ascii=False)
        if len(text) <= max_chars:
            return value
        return {
            "_truncated": True,
            "preview": text[:max_chars],
            "original_size_chars": len(text),
        }

    def _build_analysis_context(self, *, protocol: str, draft_data: dict[str, Any]) -> dict[str, Any]:
        request_data = self._dict(draft_data.get("request_data") or draft_data.get("request"))
        response_data = self._dict(draft_data.get("response_data") or draft_data.get("response"))
        method = str(draft_data.get("method") or request_data.get("method") or "GET").upper()
        url = self._text(self._first_present(
            draft_data.get("url"),
            draft_data.get("source_url"),
            draft_data.get("sourceUrl"),
            draft_data.get("sourceURL"),
            request_data.get("url"),
            draft_data.get("path"),
            request_data.get("path"),
            "",
        ))
        parsed = urlsplit(url)
        raw_path = self._text(self._first_present(draft_data.get("path"), request_data.get("path"), parsed.path, url, "/"))
        path = self._normalize_request_path(raw_path, parsed_url=parsed)
        query_params = self._merge_mappings(
            self._flatten_query(parse_qs(parsed.query, keep_blank_values=True)),
            self._query_mapping(request_data.get("query_params")),
            self._query_mapping(request_data.get("queryParams")),
            self._query_mapping(request_data.get("query")),
            self._query_mapping(request_data.get("params")),
            self._query_mapping(draft_data.get("query_params")),
            self._query_mapping(draft_data.get("queryParams")),
            self._query_mapping(draft_data.get("queryString")),
            self._query_mapping(draft_data.get("query")),
            self._query_mapping(draft_data.get("params")),
        )
        headers = self._dict(
            draft_data.get("request_headers")
            or draft_data.get("requestHeaders")
            or draft_data.get("headers")
            or request_data.get("request_headers")
            or request_data.get("requestHeaders")
            or request_data.get("headers")
        )
        request_body = self._coerce_json_payload(
            draft_data.get("request_body")
            if "request_body" in draft_data
            else self._first_present(
                draft_data.get("requestBody"),
                request_data.get("body"),
                request_data.get("json"),
                request_data.get("bodyText"),
                request_data.get("body_text"),
                draft_data.get("body"),
            )
        )
        response_status = (
            draft_data.get("response_status")
            if "response_status" in draft_data
            else self._first_present(
                draft_data.get("responseStatus"),
                draft_data.get("status_code"),
                draft_data.get("statusCode"),
                draft_data.get("status"),
                response_data.get("status_code"),
                response_data.get("statusCode"),
                response_data.get("status"),
            )
        )
        response_headers = self._dict(
            draft_data.get("response_headers")
            or draft_data.get("responseHeaders")
            or response_data.get("response_headers")
            or response_data.get("responseHeaders")
            or response_data.get("headers")
        )
        response_body = self._coerce_json_payload(
            draft_data.get("response_body")
            if "response_body" in draft_data
            else self._first_present(
                draft_data.get("responseBody"),
                draft_data.get("responseBodyText"),
                draft_data.get("response_body_text"),
                response_data.get("body"),
                response_data.get("json"),
                response_data.get("responseBody"),
                response_data.get("responseBodyText"),
                response_data.get("bodyText"),
                response_data.get("body_text"),
                response_data.get("text"),
            )
        )
        request_fields = [
            *self._mapping_fields(query_params, prefix="query"),
            *self._mapping_fields(headers, prefix="headers", sensitive_by_key=True),
            *self._schema_fields(request_body, prefix="body"),
        ]
        response_fields = []
        if response_status is not None:
            response_fields.append(self._field(
                path="status_code",
                value=response_status,
                meaning="HTTP 响应状态码",
            ))
        response_fields.extend(self._mapping_fields(response_headers, prefix="headers", sensitive_by_key=True))
        response_fields.extend(self._schema_fields(response_body, prefix="body"))
        if response_body is None:
            body_field = self._response_body_placeholder_field(response_headers)
            if body_field is not None:
                response_fields.append(body_field)
        auth_headers = [name for name in headers if self._is_auth_header(name)]
        business_code = response_body.get("code") if isinstance(response_body, dict) else None
        return {
            "request_context": {
                "protocol": protocol,
                "method": method,
                "url": url,
                "host": parsed.netloc,
                "path": path,
                "path_segments": [segment for segment in path.split("/") if segment],
                "query_params": query_params,
                "request_headers": [
                    {"name": name, "sensitive": self._is_sensitive_key(name)}
                    for name in headers
                ],
                "request_body_type": (
                    draft_data.get("request_body_type")
                    or draft_data.get("bodyType")
                    or request_data.get("body_type")
                    or request_data.get("bodyType")
                ),
                "request_fields": request_fields,
            },
            "response_schema": {
                "status_code": response_status,
                "response_headers": [
                    {"name": name, "value_preview": self._preview(value)}
                    for name, value in response_headers.items()
                ],
                "business_code": business_code,
                "response_fields": response_fields,
            },
            "automation_hints": {
                "auth_headers": auth_headers,
                "query_keys": list(query_params.keys()),
                "status_code": response_status,
                "business_code": business_code,
                "id_like_response_paths": [
                    field["path"] for field in response_fields
                    if self._is_id_like(field["path"])
                ][:10],
            },
        }

    def _enrich_analysis_raw(self, raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        data = dict(raw)
        request_context = context["request_context"]
        response_schema = context["response_schema"]
        automation_hints = context["automation_hints"]
        warnings = self._warning_list(data.get("warnings"))

        summary = self._dict(data.get("summary"))
        summary["name"] = summary.get("name") or self._infer_endpoint_name(request_context)
        summary["business_domain"] = summary.get("business_domain") or self._infer_business_domain(request_context)
        summary["operation_type"] = summary.get("operation_type") or self._infer_operation_type(request_context)
        purpose, purpose_normalized = self._normalize_summary_purpose(summary.get("purpose"), request_context)
        summary["purpose"] = purpose
        if purpose_normalized:
            warnings.append("AI 返回 summary.purpose 内容异常，已使用请求信息归一化")
        if not summary.get("confidence"):
            summary["confidence"] = 0.65
        data["summary"] = summary

        request = self._dict(data.get("request"))
        if not request.get("description"):
            request["description"] = "根据请求 URL、query 参数、请求头和请求体分析得到的请求结构。"
        if not request.get("fields"):
            request["fields"] = request_context["request_fields"]
            warnings.append("后端已根据采集请求补全 request.fields")
        data["request"] = request

        response = self._dict(data.get("response"))
        if not response.get("description"):
            response["description"] = "根据响应状态码、响应头和响应 body 样本分析得到的响应结构。"
        if not response.get("fields"):
            response["fields"] = response_schema["response_fields"]
            warnings.append("后端已根据采集响应补全 response.fields")
        data["response"] = response

        data["test_points"] = [
            self._fill_item_title(item)
            for item in data.get("test_points", [])
        ][:self.MAX_ANALYSIS_TEST_POINTS]
        if not data["test_points"]:
            data["test_points"] = self._default_test_points(request_context, response_schema)
        data["risks"] = [
            self._fill_item_title(item)
            for item in data.get("risks", [])
        ][:self.MAX_ANALYSIS_RISKS]
        if not data["risks"]:
            data["risks"] = self._default_risks(request_context, response_schema)

        automation = self._dict(data.get("automation"))
        automation["assertions"] = self._merge_list(
            automation.get("assertions"),
            self._default_assertions(response_schema),
        )
        automation["dependencies"] = self._merge_list(
            automation.get("dependencies"),
            [f"需要有效 {name} 请求头" for name in automation_hints["auth_headers"]],
        )
        automation["data_setup"] = self._merge_list(
            automation.get("data_setup"),
            self._default_data_setup(automation_hints["query_keys"]),
        )
        automation["extractors"] = self._merge_list(
            automation.get("extractors"),
            [f"如需串联下游接口，可提取 {path}" for path in automation_hints["id_like_response_paths"]],
        )
        automation["cleanup"] = self._warning_list(automation.get("cleanup"))
        data["automation"] = automation

        data["warnings"] = list(dict.fromkeys(warnings))
        return data

    def _normalize_analysis_raw(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {
                "summary": {"purpose": self._text(raw)},
                "warnings": ["AI 返回整体不是 JSON 对象，已归一化"],
            }

        data = dict(raw)
        warnings = self._warning_list(data.get("warnings"))

        def warn(field: str) -> None:
            message = f"AI 返回字段 {field} 类型已归一化"
            if message not in warnings:
                warnings.append(message)

        if not isinstance(data.get("summary"), dict):
            value = data.get("summary")
            data["summary"] = {} if value in (None, "") else {"purpose": self._text(value)}
            warn("summary")

        for field in ("request", "response"):
            value = data.get(field)
            if not isinstance(value, dict):
                data[field] = {} if value in (None, "") else {"description": self._text(value), "fields": []}
                warn(field)
            else:
                if not isinstance(value.get("fields"), list):
                    value["fields"] = []

        data["test_points"] = self._normalize_items(
            data.get("test_points"),
            field="test_points",
            text_key="title",
            default_priority_field="priority",
            warnings=warnings,
            warn=warn,
        )
        data["risks"] = self._normalize_items(
            data.get("risks"),
            field="risks",
            text_key="title",
            default_priority_field="level",
            warnings=warnings,
            warn=warn,
        )

        automation = data.get("automation")
        if not isinstance(automation, dict):
            data["automation"] = {}
            warn("automation")
        else:
            for field in ("assertions", "extractors", "dependencies", "data_setup", "cleanup"):
                if not isinstance(automation.get(field), list):
                    automation[field] = []

        data["warnings"] = warnings
        return data

    def _normalize_items(
        self,
        value: Any,
        *,
        field: str,
        text_key: str,
        default_priority_field: str,
        warnings: list[str],
        warn,
    ) -> list[dict[str, Any]]:
        if value in (None, ""):
            if value is not None:
                warn(field)
            return []
        if isinstance(value, str):
            warn(field)
            return [{text_key: value, default_priority_field: "medium"}]
        if isinstance(value, dict):
            warn(field)
            return [self._normalize_item(value, default_priority_field)]
        if not isinstance(value, list):
            warn(field)
            return [{text_key: self._text(value), default_priority_field: "medium"}]
        normalized = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(self._normalize_item(item, default_priority_field))
            elif item not in (None, ""):
                warnings.append(f"AI 返回字段 {field} 的数组项类型已归一化")
                normalized.append({text_key: self._text(item), default_priority_field: "medium"})
        return normalized

    def _normalize_item(self, item: dict[str, Any], priority_field: str) -> dict[str, Any]:
        normalized = dict(item)
        value = str(normalized.get(priority_field) or "medium").lower()
        aliases = {"p0": "high", "p1": "high", "p2": "medium", "p3": "low"}
        normalized[priority_field] = aliases.get(value, value if value in {"high", "medium", "low"} else "medium")
        return normalized

    def _warning_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [self._text(item) for item in value if item not in (None, "")]
        if value in (None, ""):
            return []
        return [self._text(value)]

    def _text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _first_present(self, *values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    def _merge_mappings(self, *values: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for value in values:
            if isinstance(value, dict):
                merged.update(value)
        return merged

    def _query_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            text = value.strip().lstrip("?")
            if "=" in text:
                return self._flatten_query(parse_qs(text, keep_blank_values=True))
        return {}

    def _normalize_request_path(self, value: str, *, parsed_url) -> str:
        text = str(value or "").strip()
        parsed_path = parsed_url.path if parsed_url is not None else ""
        if text.startswith(("http://", "https://", "ws://", "wss://")):
            parsed = urlsplit(text)
            return parsed.path or "/"
        if text:
            return text if text.startswith("/") else f"/{text}"
        return parsed_path or "/"

    def _coerce_json_payload(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return value
        if text[0] not in "{[":
            return value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value

    def _flatten_query(self, values: dict[str, list[str]]) -> dict[str, Any]:
        return {key: item[0] if len(item) == 1 else item for key, item in values.items()}

    def _content_type(self, response_headers: dict[str, Any]) -> str:
        for key, value in response_headers.items():
            if str(key).lower() == "content-type":
                return str(value or "")
        return ""

    def _response_body_placeholder_field(self, response_headers: dict[str, Any]) -> dict[str, Any] | None:
        content_type = self._content_type(response_headers).lower()
        if "html" in content_type:
            return self._field(path="body", value="", meaning="HTML 文档内容", example=None)
        if content_type.startswith("text/"):
            return self._field(path="body", value="", meaning="文本响应内容", example=None)
        return None

    def _mapping_fields(
        self,
        values: dict[str, Any],
        *,
        prefix: str,
        sensitive_by_key: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            self._field(
                path=f"{prefix}.{key}",
                value=value,
                meaning=self._field_meaning(str(key), prefix=prefix),
                sensitive=sensitive_by_key and self._is_sensitive_key(str(key)),
            )
            for key, value in values.items()
        ]

    def _schema_fields(self, value: Any, *, prefix: str, limit: int = 80) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []

        def walk(item: Any, path: str) -> None:
            if len(fields) >= limit:
                return
            if isinstance(item, dict):
                fields.append(self._field(path=path, value=item, example=None))
                for key, nested in item.items():
                    walk(nested, f"{path}.{key}" if path else str(key))
            elif isinstance(item, list):
                fields.append(self._field(path=path, value=item, example=[] if not item else None))
                if item:
                    walk(item[0], f"{path}[0]")
            else:
                fields.append(self._field(path=path, value=item, sensitive=self._is_sensitive_path(path)))

        if value is not None:
            walk(value, prefix)
        return fields[:limit]

    def _field(
        self,
        *,
        path: str,
        value: Any,
        meaning: str = "",
        sensitive: bool = False,
        example: Any = ...,
    ) -> dict[str, Any]:
        return {
            "path": path,
            "type": self._value_type(value),
            "meaning": meaning or self._field_meaning(path.rsplit(".", 1)[-1], prefix=path.split(".", 1)[0]),
            "required": False,
            "constraints": [],
            "sensitive": sensitive,
            "dynamic": self._is_id_like(path),
            "example": "***" if sensitive else (self._preview(value) if example is ... else example),
        }

    def _value_type(self, value: Any) -> str:
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

    def _preview(self, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return None
        if isinstance(value, str):
            return value[:120] + ("..." if len(value) > 120 else "")
        return value

    def _field_meaning(self, key: str, *, prefix: str) -> str:
        lowered = key.lower().replace("-", "_")
        if prefix == "headers" and self._is_auth_header(key):
            return "请求鉴权头"
        if prefix == "headers" and lowered == "accept":
            return "客户端可接受的响应类型"
        if prefix == "headers" and lowered == "content_type":
            return "响应内容类型"
        if prefix == "headers" and lowered == "x_requested_with":
            return "XHR 请求标识"
        if prefix == "headers" and lowered in {"referer", "referrer", "is_referer"}:
            return "请求来源页面"
        if prefix == "headers" and lowered in {"traceid", "trace_id"}:
            return "链路追踪标识"
        if prefix == "headers" and lowered in {"bdqid"}:
            return "百度请求标识"
        if prefix == "headers" and lowered == "cache_control":
            return "缓存策略"
        if lowered in {"wd", "q", "keyword", "keywords", "query"}:
            return "搜索关键词"
        if lowered == "oq":
            return "原始搜索关键词"
        if lowered in {"ie", "charset", "encoding"}:
            return "字符编码"
        if lowered == "tn":
            return "搜索来源或模板标识"
        if lowered.startswith("rsv_"):
            return "搜索推荐或跟踪参数"
        if lowered in {"is_xhr"}:
            return "是否 XHR 请求"
        if lowered in {"companyid", "entid", "ent_id"}:
            return "企业标识"
        if lowered in {"page", "pageno", "pageindex"}:
            return "分页页码"
        if lowered in {"size", "pagesize", "limit"}:
            return "分页大小"
        if lowered in {"code", "status_code"}:
            return "业务或 HTTP 状态码"
        if lowered in {"records", "list", "items"}:
            return "列表数据"
        if lowered in {"total", "count"}:
            return "总数"
        return ""

    def _is_auth_header(self, key: str) -> bool:
        lowered = key.lower()
        return "auth" in lowered or lowered in {"authorization", "cookie"}

    def _is_id_like(self, path: str) -> bool:
        key = path.rsplit(".", 1)[-1].lower()
        return key == "id" or key.endswith("id") or key.endswith("_id")

    def _infer_endpoint_name(self, request_context: dict[str, Any]) -> str:
        method = request_context.get("method") or "HTTP"
        path = str(request_context.get("path") or "")
        segment = next((item for item in reversed(path.split("/")) if item), path or "接口")
        return f"{method} {segment}"

    def _infer_business_domain(self, request_context: dict[str, Any]) -> str:
        segments = request_context.get("path_segments") or []
        for segment in reversed(segments[:-1]):
            if segment.lower() not in {"api", "v1", "multiscan", "lingxi-bigdata"}:
                return segment
        return str(request_context.get("host") or "")

    def _infer_operation_type(self, request_context: dict[str, Any]) -> str:
        method = str(request_context.get("method") or "").upper()
        path = str(request_context.get("path") or "").lower()
        if method == "GET" or any(keyword in path for keyword in ("get", "query", "search", "list", "page")):
            return "query"
        if method == "POST":
            return "create"
        if method in {"PUT", "PATCH"}:
            return "update"
        if method == "DELETE":
            return "delete"
        return "business"

    def _infer_purpose(self, request_context: dict[str, Any]) -> str:
        method = request_context.get("method", "HTTP")
        path = str(request_context.get("path", ""))
        host = str(request_context.get("host") or "")
        query_params = self._dict(request_context.get("query_params"))
        search_keyword = self._first_present(
            query_params.get("wd"),
            query_params.get("q"),
            query_params.get("keyword"),
            query_params.get("keywords"),
        )
        if method == "GET" and search_keyword not in (None, "") and (
            "baidu.com" in host.lower() or path.lower() in {"/s", "/search"} or "search" in path.lower()
        ):
            engine = "百度搜索" if "baidu.com" in host.lower() else "搜索"
            return f"根据关键词“{self._compact_display_text(str(search_keyword), 40)}”执行{engine}并返回搜索结果。"
        if method == "GET" and search_keyword not in (None, ""):
            return f"根据关键词“{self._compact_display_text(str(search_keyword), 40)}”查询结果列表。"
        return f"{method} {path} 接口。"

    def _normalize_summary_purpose(self, value: Any, request_context: dict[str, Any]) -> tuple[str, bool]:
        fallback = self._infer_purpose(request_context)
        if value in (None, ""):
            return fallback, False
        text = self._text(value).strip()
        if not text:
            return fallback, False
        extracted = self._extract_purpose_from_structured_text(text)
        if extracted:
            return self._compact_display_text(extracted), True
        if self._looks_like_structured_blob(text):
            return fallback, True
        compact = self._compact_display_text(text)
        if self._looks_like_generic_endpoint_purpose(compact):
            return fallback, compact != fallback
        return compact, compact != text

    def _looks_like_generic_endpoint_purpose(self, text: str) -> bool:
        return bool(re.match(r"^(GET|POST|PUT|PATCH|DELETE|HTTP)\s+\S+\s+接口。?$", text.strip(), re.I))

    def _extract_purpose_from_structured_text(self, text: str) -> str | None:
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        candidates = [
            parsed.get("purpose"),
            parsed.get("summary"),
            parsed.get("description"),
        ]
        nested_summary = parsed.get("summary")
        if isinstance(nested_summary, dict):
            candidates.extend([
                nested_summary.get("purpose"),
                nested_summary.get("summary"),
                nested_summary.get("description"),
            ])
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip() and not self._looks_like_structured_blob(candidate):
                return candidate
        return None

    def _looks_like_structured_blob(self, text: str) -> bool:
        stripped = text.strip()
        if stripped.startswith(("{", "[")):
            return True
        markers = ('"request"', '"response"', '"test_points"', '"automation"', '"fields"', "'request'", "'response'")
        return any(marker in stripped for marker in markers)

    def _compact_display_text(self, text: str, max_chars: int = 240) -> str:
        compact = " ".join(str(text).split())
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip() + "..."

    def _fill_item_title(self, item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        if not result.get("title"):
            result["title"] = result.get("description") or result.get("summary") or result.get("category") or "待验证项"
        return result

    def _default_assertions(self, response_schema: dict[str, Any]) -> list[str]:
        assertions = []
        if response_schema.get("status_code") is not None:
            assertions.append(f"断言 HTTP 状态码为 {response_schema['status_code']}")
        if response_schema.get("business_code") is not None:
            assertions.append(f"断言响应 body.code 为 {response_schema['business_code']}")
        content_type = self._content_type_from_schema(response_schema)
        if content_type:
            major_type = content_type.split(";", 1)[0]
            assertions.append(f"断言响应 Content-Type 包含 {major_type}")
        if response_schema.get("response_fields"):
            assertions.append("断言响应结构包含关键字段")
        return assertions

    def _content_type_from_schema(self, response_schema: dict[str, Any]) -> str:
        for item in response_schema.get("response_headers") or []:
            if str(item.get("name") or "").lower() == "content-type":
                return str(item.get("value_preview") or "")
        for field in response_schema.get("response_fields") or []:
            if str(field.get("path") or "").lower() == "headers.content-type":
                return str(field.get("example") or "")
        return ""

    def _default_data_setup(self, query_keys: list[str]) -> list[str]:
        items: list[str] = []
        for key in query_keys:
            lowered = str(key).lower()
            if lowered.endswith("id") or "company" in lowered:
                items.append(f"准备有效 {key} 测试数据")
            elif lowered in {"wd", "q", "keyword", "keywords"}:
                items.append(f"准备有效 {key} 查询关键词")
            elif lowered in {"page", "pageno", "pageindex", "current"}:
                items.append(f"准备有效 {key} 分页页码")
            elif lowered in {"size", "pagesize", "limit"}:
                items.append(f"准备有效 {key} 分页大小")
        return items

    def _default_test_points(
        self,
        request_context: dict[str, Any],
        response_schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        query_params = self._dict(request_context.get("query_params"))
        points: list[dict[str, Any]] = []
        keyword_key = next((key for key in ("wd", "q", "keyword", "keywords") if key in query_params), None)
        if keyword_key:
            points.append({
                "category": "positive",
                "title": "有效关键词查询",
                "description": f"使用有效 {keyword_key} 查询关键词验证接口返回成功结果。",
                "priority": "high",
                "test_data": {keyword_key: query_params.get(keyword_key)},
                "expected_result": "返回 HTTP 成功状态，并包含约定的搜索结果页面或数据片段。",
            })
            points.append({
                "category": "boundary",
                "title": "空关键词查询",
                "description": f"将 {keyword_key} 置为空，验证接口对缺失搜索关键词的处理。",
                "priority": "medium",
                "test_data": {keyword_key: ""},
                "expected_result": "返回约定的提示、空结果或参数错误响应。",
            })
        elif query_params:
            points.append({
                "category": "positive",
                "title": "有效查询参数返回成功",
                "description": "使用采集到的有效 query 参数验证接口可正常返回。",
                "priority": "high",
                "test_data": {key: query_params[key] for key in list(query_params)[:5]},
                "expected_result": "返回 HTTP 成功状态，响应结构符合预期。",
            })
        if response_schema.get("status_code") is not None:
            points.append({
                "category": "positive",
                "title": "响应状态码校验",
                "description": "验证接口返回的 HTTP 状态码符合采集样本。",
                "priority": "medium",
                "test_data": {},
                "expected_result": f"HTTP 状态码为 {response_schema['status_code']}。",
            })
        return points[:self.MAX_ANALYSIS_TEST_POINTS]

    def _default_risks(
        self,
        request_context: dict[str, Any],
        response_schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        query_params = self._dict(request_context.get("query_params"))
        risks: list[dict[str, Any]] = []
        if any(key in query_params for key in ("wd", "q", "keyword", "keywords")):
            risks.append({
                "level": "medium",
                "title": "查询关键词可能包含用户隐私",
                "description": "搜索或查询关键词可能暴露用户输入内容，记录日志和报告时需要脱敏或控制展示范围。",
                "recommendation": "避免在测试报告中长期保存敏感搜索词，必要时使用脱敏测试数据。",
            })
        content_type = self._content_type_from_schema(response_schema).lower()
        if "html" in content_type:
            risks.append({
                "level": "low",
                "title": "HTML 响应不适合做强结构断言",
                "description": "HTML 页面内容容易受页面模板、广告或个性化结果影响。",
                "recommendation": "自动化断言优先校验状态码、Content-Type 和关键文本，不建议依赖完整 HTML。",
            })
        return risks[:self.MAX_ANALYSIS_RISKS]

    def _merge_list(self, existing: Any, defaults: list[str]) -> list[str]:
        items = self._warning_list(existing)
        return list(dict.fromkeys([*items, *defaults]))
