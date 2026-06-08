import json
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.websocket_test_case_repository import WebSocketTestCaseRepository
from app.schemas.ai import (
    AIChatMessage,
    AIChatRequest,
    AIGeneratedWebSocketTestCaseResponse,
    AIWebSocketTestCaseExpandRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.schemas.websocket_test_case import WebSocketTestCaseCreateRequest
from app.services.ai_service import AIService
from app.services.permission_service import PermissionService


class AIWebSocketTestCaseService:
    def __init__(self, db: Session):
        self.project_repository = ProjectRepository(db)
        self.test_case_repository = WebSocketTestCaseRepository(db)
        self.permission_service = PermissionService(db)
        self.ai_service = AIService()

    def generate_test_cases(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: AIWebSocketTestCaseGenerateRequest,
        current_user: User,
    ) -> AIGeneratedWebSocketTestCaseResponse:
        environment, variables = self._context(project_id, environment_id, current_user)
        response = self.ai_service.chat(AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=self._generate_system_prompt()),
                AIChatMessage(role="user", content=self._generation_context(
                    project_id, environment, variables, payload
                )),
            ],
            thinking="disabled",
            temperature=0.2,
            max_tokens=5000,
            response_format="json",
        ))
        return self._parse_result(response.content, project_id, environment_id, payload.include_assertions)

    def expand_test_cases(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        payload: AIWebSocketTestCaseExpandRequest,
        current_user: User,
    ) -> AIGeneratedWebSocketTestCaseResponse:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        source = self.test_case_repository.get_by_id(project_id=project_id, test_case_id=test_case_id)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebSocket 测试用例不存在")
        selected_environment_id = environment_id or source.environment_id or (source.environment_ids[0] if source.environment_ids else None)
        if selected_environment_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WebSocket 测试用例未绑定环境")
        environment, variables = self._context(project_id, selected_environment_id, current_user)
        response = self.ai_service.chat(AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=self._expand_system_prompt()),
                AIChatMessage(role="user", content=json.dumps({
                    "project_id": project_id,
                    "environment": self._environment_data(environment),
                    "environment_variables": self._variable_data(variables),
                    "source_websocket_test_case": self._source_case(source),
                    "requirement": payload.requirement,
                    "generate_count": payload.generate_count,
                    "expansion_types": payload.expansion_types,
                    "include_assertions": payload.include_assertions,
                }, ensure_ascii=False, indent=2)),
            ],
            thinking="disabled",
            temperature=0.25,
            max_tokens=6000,
            response_format="json",
        ))
        return self._parse_result(response.content, project_id, selected_environment_id, payload.include_assertions)

    def _context(self, project_id: int, environment_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        environment = self.project_repository.get_environment(project_id=project_id, environment_id=environment_id)
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        return environment, self.project_repository.list_environment_variables(environment_id=environment_id)

    def _generation_context(self, project_id, environment, variables, payload):
        return json.dumps({
            "project_id": project_id,
            "environment": self._environment_data(environment),
            "environment_variables": self._variable_data(variables),
            "generate_count": payload.generate_count,
            "include_assertions": payload.include_assertions,
            "extra_requirements": payload.extra_requirements,
            "websocket_text": payload.websocket_text,
        }, ensure_ascii=False, indent=2)

    def _generate_system_prompt(self) -> str:
        return """
你是自动化测试平台的 WebSocket 测试用例生成助手。只生成 WebSocket 会话用例，不生成 HTTP 接口用例。
必须只输出合法 JSON，根对象必须包含 source_summary、cases、warnings。
每条用例严格使用以下结构：
{"name":"","description":"","environment_id":1,"environment_ids":[1],"path":"/ws/path","headers":{},"subprotocols":[],"messages":[{"type":"json","data":{}}],"receive_count":1,"connect_timeout_ms":10000,"receive_timeout_ms":10000,"assertions":[],"extractors":[]}
WebSocket 规则：
1. 围绕连接握手、鉴权 headers、subprotocol 协商、客户端消息顺序、服务端推送数量、消息内容、超时和关闭行为设计。
2. 禁止输出 method、query_params、body_type、body、status_code 等 HTTP 用例字段。
3. path 优先使用相对 WebSocket 路径；不要拼接环境 base_url。
4. messages.type 只能是 text 或 json。需要发送非法 JSON 时，必须使用 text 类型保存原始字符串。
5. assertions 只能是 message_count、message_contains、message_json_equals；消息断言必须给出 message_index。
6. extractors 只能包含 name、message_index、path，并从接收消息 JSON 中提取。
7. receive_count 必须覆盖断言和提取器引用的最大 message_index。
8. 不编造真实 token 或密钥，使用 {{变量名}}。不确定信息写入 warnings。
""".strip()

    def _expand_system_prompt(self) -> str:
        return self._generate_system_prompt() + """

你正在基于一个已有 WebSocket 用例扩写变体。扩写必须遵循 WebSocket 长连接特点：
- handshake_auth：缺失、错误或过期鉴权 header。
- subprotocol：缺失、不支持或协商不匹配。
- message_sequence：消息乱序、重复、缺少前置消息或多阶段会话。
- missing_message_field / invalid_message_value：只改变消息 payload 的少量字段。
- malformed_message：使用 text 类型发送格式错误的 JSON 或协议文本。
- receive_count / timeout：验证推送数量、无消息、延迟和超时。
- connection_close：验证服务端主动关闭、异常关闭或发送后关闭。
默认保留源用例 path、连接配置和主体消息流程，只做针对性变化。禁止套用 HTTP 状态码、请求方法和请求体概念。
""".strip()

    def _parse_result(self, raw_content: str, project_id: int, environment_id: int, include_assertions: bool):
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
                cases.append(self._normalize_case(raw_case, environment_id, include_assertions))
            except (ValueError, ValidationError) as exc:
                warnings.append(f"第 {index} 个用例已忽略: {exc}")
        return AIGeneratedWebSocketTestCaseResponse.model_validate({
            "project_id": project_id,
            "environment_id": environment_id,
            "environment_ids": [environment_id],
            "source_summary": str(data.get("source_summary") or data.get("summary") or ""),
            "cases": cases,
            "warnings": warnings,
        })

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
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw_content or "").strip(), flags=re.IGNORECASE)
        if not text:
            raise ValueError("empty content")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("no JSON object found") from None
            data = json.loads(text[start:end + 1])
        if isinstance(data, list):
            return {"source_summary": "", "cases": data, "warnings": []}
        if not isinstance(data, dict):
            raise ValueError("root is not object")
        return data

    def _source_case(self, source):
        return {
            "id": source.id, "name": source.name, "description": source.description,
            "environment_id": source.environment_id, "environment_ids": source.environment_ids,
            "path": source.path, "headers": source.headers or {}, "subprotocols": source.subprotocols or [],
            "messages": source.messages or [], "receive_count": source.receive_count,
            "connect_timeout_ms": source.connect_timeout_ms, "receive_timeout_ms": source.receive_timeout_ms,
            "assertions": source.assertions or [], "extractors": source.extractors or [],
        }

    def _environment_data(self, environment: ProjectEnvironment):
        return {"id": environment.id, "name": environment.name, "base_url": environment.base_url, "description": environment.description}

    def _variable_data(self, variables: list[ProjectEnvironmentVariable]):
        return [{"name": item.name, "is_secret": item.is_secret, "reference": "{{" + item.name + "}}"} for item in variables]
