import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, status

from app.ai_skills.base import AISkill, SkillPackage, load_model_json
from app.ai_skills.registry import register_ai_skill
from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.schemas.ai import AIChatMessage, AIChatRequest, AIGeneratedWebSocketTestCaseResponse
from app.schemas.websocket_test_case import WebSocketTestCaseCreateRequest


class WebSocketTestCaseSkill(AISkill):
    skill_id = "websocket-test-case"

    def __init__(self):
        self.package = SkillPackage(Path(__file__).parent / "packages" / self.skill_id)
        self.name = self.package.metadata.name
        self.description = self.package.metadata.description

    def build_chat_request(self, context: dict[str, Any]) -> AIChatRequest:
        mode = context["mode"]
        return AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=self.package.read_text(f"prompts/{mode}_system.md")),
                AIChatMessage(role="user", content=self._expand_context(context) if mode == "expand" else self._generation_context(context)),
            ],
            thinking="disabled",
            temperature=0.25 if mode == "expand" else 0.2,
            max_tokens=6000 if mode == "expand" else 5000,
            response_format="json",
        )

    def parse_response(self, raw_content: str, context: dict[str, Any]) -> AIGeneratedWebSocketTestCaseResponse:
        try:
            data = self._loads_json(raw_content)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI 返回结果不是合法 JSON: {exc}") from exc
        warnings = [str(item) for item in data.get("warnings", [])] if isinstance(data.get("warnings"), list) else []
        raw_cases = data.get("cases") or data.get("websocket_test_cases") or data.get("data") or []
        if isinstance(raw_cases, dict):
            raw_cases = [raw_cases]
        cases = []
        for index, raw_case in enumerate(raw_cases if isinstance(raw_cases, list) else [], start=1):
            if not isinstance(raw_case, dict):
                warnings.append(f"第 {index} 个用例不是对象，已忽略")
                continue
            try:
                cases.append(self._normalize_case(raw_case, context["environment_id"], context["include_assertions"]))
            except (ValueError, TypeError) as exc:
                warnings.append(f"第 {index} 个用例已忽略: {exc}")
        return AIGeneratedWebSocketTestCaseResponse.model_validate({
            "project_id": context["project_id"],
            "environment_id": context["environment_id"],
            "environment_ids": [context["environment_id"]],
            "source_summary": str(data.get("source_summary") or data.get("summary") or ""),
            "cases": cases,
            "warnings": warnings,
        })

    def _generation_context(self, context: dict[str, Any]) -> str:
        payload = context["payload"]
        return json.dumps({
            "project_id": context["project_id"],
            "environment": self._environment_data(context["environment"]),
            "environment_variables": self._variable_data(context["variables"]),
            "generate_count": payload.generate_count,
            "include_assertions": payload.include_assertions,
            "extra_requirements": payload.extra_requirements,
            "websocket_text": payload.websocket_text,
        }, ensure_ascii=False, indent=2)

    def _expand_context(self, context: dict[str, Any]) -> str:
        payload = context["payload"]
        return json.dumps({
            "project_id": context["project_id"],
            "environment": self._environment_data(context["environment"]),
            "environment_variables": self._variable_data(context["variables"]),
            "source_websocket_test_case": context["source_websocket_test_case"],
            "requirement": payload.requirement,
            "generate_count": payload.generate_count,
            "expansion_types": payload.expansion_types,
            "include_assertions": payload.include_assertions,
        }, ensure_ascii=False, indent=2)

    def _normalize_case(self, data: dict[str, Any], environment_id: int, include_assertions: bool):
        path = str(data.get("path") or "").strip()
        if not path:
            raise ValueError("path 为空")
        parsed = urlsplit(path)
        if parsed.scheme in {"ws", "wss", "http", "https"} and parsed.netloc:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
        messages = []
        for item in data.get("messages", []) if isinstance(data.get("messages"), list) else []:
            if not isinstance(item, dict):
                continue
            message_type = item.get("type") if item.get("type") in {"text", "json"} else "text"
            messages.append({"type": message_type, "data": item.get("data")})
        assertions = self._normalize_assertions(data.get("assertions")) if include_assertions else []
        extractors = self._normalize_extractors(data.get("extractors"))
        max_index = max(
            [item.get("message_index", 0) for item in assertions if item["type"] != "message_count"]
            + [item["message_index"] for item in extractors],
            default=-1,
        )
        expected_message_count = max(
            [
                item["expected"]
                for item in assertions
                if item["type"] == "message_count" and isinstance(item["expected"], int)
            ],
            default=0,
        )
        normalized = {
            "name": str(data.get("name") or "AI 生成 WebSocket 测试用例")[:128],
            "description": str(data.get("description") or ""),
            "environment_id": environment_id,
            "environment_ids": [environment_id],
            "path": path,
            "headers": data.get("headers") if isinstance(data.get("headers"), dict) else {},
            "subprotocols": [str(item) for item in data.get("subprotocols", [])] if isinstance(data.get("subprotocols"), list) else [],
            "messages": messages,
            "receive_count": min(100, max(int(data.get("receive_count") or 0), max_index + 1, expected_message_count)),
            "connect_timeout_ms": min(120000, max(1, int(data.get("connect_timeout_ms") or 10000))),
            "receive_timeout_ms": min(120000, max(1, int(data.get("receive_timeout_ms") or 10000))),
            "assertions": assertions,
            "extractors": extractors,
        }
        WebSocketTestCaseCreateRequest.model_validate(normalized)
        return normalized

    def _normalize_assertions(self, value):
        allowed = {"message_count", "message_contains", "message_json_equals"}
        results = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict) or item.get("type") not in allowed:
                continue
            assertion = {"type": item["type"], "expected": item.get("expected"), "message_index": max(0, int(item.get("message_index") or 0))}
            if item["type"] == "message_json_equals":
                assertion["path"] = str(item.get("path") or "")
            results.append(assertion)
        return results

    def _normalize_extractors(self, value):
        if not isinstance(value, list):
            return []
        return [
            {"name": str(item["name"]), "message_index": max(0, int(item.get("message_index") or 0)), "path": str(item["path"])}
            for item in value if isinstance(item, dict) and item.get("name") and item.get("path")
        ]

    def _loads_json(self, raw_content: str):
        data = load_model_json(raw_content, allow_list=True)
        if isinstance(data, list):
            return {"source_summary": "", "cases": data, "warnings": []}
        return data

    def _environment_data(self, environment: ProjectEnvironment):
        return {"id": environment.id, "name": environment.name, "base_url": environment.base_url, "description": environment.description}

    def _variable_data(self, variables: list[ProjectEnvironmentVariable]):
        return [{"name": item.name, "is_secret": item.is_secret, "reference": "{{" + item.name + "}}"} for item in variables]


register_ai_skill(WebSocketTestCaseSkill())
