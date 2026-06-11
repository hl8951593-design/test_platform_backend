import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.user import User
from app.schemas.ai import (
    AIChatMessage,
    AIChatRequest,
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
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.EXECUTE_TEST.value
        )
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
