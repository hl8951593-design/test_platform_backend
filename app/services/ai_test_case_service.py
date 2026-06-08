import json
import re
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.schemas.ai import (
    AIChatMessage,
    AIChatRequest,
    AIGeneratedTestCaseResponse,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
)
from app.schemas.test_case import TestCaseCreateRequest
from app.services.ai_service import AIService
from app.services.permission_service import PermissionService


class AITestCaseService:
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
    ) -> AIGeneratedTestCaseResponse:
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

        variables = self.project_repository.list_environment_variables(environment_id=environment_id)
        ai_response = self.ai_service.chat(
            AIChatRequest(
                messages=[
                    AIChatMessage(role="system", content=self._system_prompt()),
                    AIChatMessage(
                        role="user",
                        content=self._user_prompt(
                            project_id=project_id,
                            environment=environment,
                            variables=variables,
                            payload=payload,
                        ),
                    ),
                ],
                thinking="disabled",
                temperature=0.2,
                max_tokens=4000,
                response_format="json",
            )
        )

        return self._parse_generation_result(
            raw_content=ai_response.content,
            project_id=project_id,
            environment_id=environment_id,
            include_assertions=payload.include_assertions,
        )

    def expand_test_cases(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        payload: AITestCaseExpandRequest,
        current_user: User,
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

        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=selected_environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

        variables = self.project_repository.list_environment_variables(environment_id=selected_environment_id)
        ai_response = self.ai_service.chat(
            AIChatRequest(
                messages=[
                    AIChatMessage(role="system", content=self._expand_system_prompt()),
                    AIChatMessage(
                        role="user",
                        content=self._expand_user_prompt(
                            project_id=project_id,
                            environment=environment,
                            variables=variables,
                            payload=payload,
                            source_case=self._source_case_to_dict(source_case),
                        ),
                    ),
                ],
                thinking="disabled",
                temperature=0.25,
                max_tokens=5000,
                response_format="json",
            )
        )

        source_case_data = self._source_case_to_dict(source_case)
        return self._parse_generation_result(
            raw_content=ai_response.content,
            project_id=project_id,
            environment_id=selected_environment_id,
            include_assertions=payload.include_assertions,
            source_case=source_case_data,
        )

    def _system_prompt(self) -> str:
        return """
你是自动化测试平台的接口测试用例生成助手。
你的任务是根据用户粘贴的接口文档、curl、URL、请求参数、响应示例或业务说明，生成可直接保存到平台的接口测试用例草稿。

必须遵守：
1. 只输出合法 JSON，不要输出 Markdown，不要输出解释性文字。
2. 根对象必须包含 source_summary、cases、warnings 三个字段。
3. cases 必须是数组，数组长度等于用户要求的生成数量，除非输入信息不足。
4. 每个用例必须严格符合固定结构：
{
  "name": "用例名称",
  "description": "用例说明",
  "environment_id": 1,
  "environment_ids": [1],
  "method": "GET",
  "path": "/api/path",
  "headers": {},
  "query_params": {},
  "body_type": "none",
  "body": null,
  "assertions": [],
  "extractors": []
}
5. method 只能是 GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS。
6. body_type 只能是 none、json、form_urlencoded、multipart、raw_text、raw_json。
7. path 优先使用相对路径，不要拼接 base_url；如果用户只提供完整 URL，提取其中 path 和 query。
8. headers、query_params 必须是 JSON 对象；没有则返回 {}。
9. body_type=none 时 body 必须为 null。
10. 不要编造认证 token、cookie、密码、手机号、邮箱等敏感真实值；需要变量时使用 {{变量名}}。
11. 如果用户粘贴 curl，要尽量识别 method、URL、headers、query、body。
12. 如果生成断言，优先生成 status_code 断言；只有用户提供响应 JSON 示例时才生成 json_equals。
13. assertions 只允许：
    {"type":"status_code","expected":200}
    {"type":"body_contains","expected":"文本"}
    {"type":"json_equals","path":"data.id","expected":1}
14. extractors 只允许：
    {"name":"变量名","path":"data.token"}
15. 不确定的信息写入 warnings，不要为了凑字段编造。
""".strip()

    def _user_prompt(
        self,
        *,
        project_id: int,
        environment: ProjectEnvironment,
        variables: list[ProjectEnvironmentVariable],
        payload: AITestCaseGenerateRequest,
    ) -> str:
        variable_names = [
            {
                "name": variable.name,
                "is_secret": variable.is_secret,
                "reference": "{{" + variable.name + "}}",
            }
            for variable in variables
        ]
        context = {
            "project_id": project_id,
            "environment": {
                "id": environment.id,
                "name": environment.name,
                "base_url": environment.base_url,
                "description": environment.description,
            },
            "environment_variables": variable_names,
            "generate_count": payload.generate_count,
            "include_assertions": payload.include_assertions,
            "request_method": payload.request_method,
            "extra_requirements": payload.extra_requirements,
            "interface_text": payload.interface_text,
        }
        return (
            "请根据以下上下文生成接口测试用例。必须输出 JSON，且每个用例都必须绑定到当前 project_id 和 environment_id。\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )

    def _expand_system_prompt(self) -> str:
        return """
你是自动化测试平台的接口测试用例扩写助手。
你的任务是基于一个已存在的源测试用例，根据用户的自然语言需求，扩写生成多个新的接口测试用例草稿。

必须遵守：
1. 只输出合法 JSON，不要输出 Markdown，不要输出解释性文字。
2. 根对象必须包含 source_summary、cases、warnings 三个字段。
3. cases 必须是数组，数组长度尽量等于用户要求的 generate_count。
4. 每个扩写用例必须严格符合固定结构：
{
  "name": "用例名称",
  "description": "用例说明",
  "environment_id": 1,
  "environment_ids": [1],
  "method": "GET",
  "path": "/api/path",
  "headers": {},
  "query_params": {},
  "body_type": "none",
  "body": null,
  "assertions": [],
  "extractors": []
}
5. 扩写用例必须沿用源用例的 method、path、headers、body_type、extractors，除非用户需求明确要求改变。
6. 主要变化应该体现在 query_params、body、assertions、name、description。
7. 扩写方向必须围绕源用例已有字段做健壮性测试，优先覆盖：字段 key 存在但 value 为空、字段类型错误、请求参数增加、请求参数减少、字段长度超限、字段格式错误。
8. 不要编造真实 token、cookie、密码、手机号、邮箱等敏感真实值；需要变量时使用 {{变量名}}。
9. 如果源用例使用了环境变量，扩写用例也应该继续使用变量引用。
10. path 必须使用相对路径，不要拼接 base_url。
11. body_type=none 时 body 必须为 null。
12. assertions 只允许 status_code、body_contains、json_equals。
13. extractors 只允许 name 和 path。负向或异常用例通常不需要 extractors。
14. 禁止生成“完全不传参”“删除全部 body”“删除全部 query_params”这类过粗用例，除非用户明确要求。
15. missing_param 只能删除单个关键字段或少量字段，必须保留源用例主体结构。
16. extra_param 只能增加少量无关字段，不能改变源接口路径和请求方法。
17. empty_value 必须保留字段 key，只把 value 改成 ""、null、[] 或 {}。
18. invalid_type 必须保留字段 key，只把 value 改成错误类型，例如数字改字符串、字符串改对象、布尔改字符串。
19. length_overflow 必须针对已有字符串字段生成超长值，并在 description 中说明长度超限。
20. 如果信息不足，在 warnings 中说明，不要为了凑字段编造不存在的业务规则。
""".strip()

    def _expand_user_prompt(
        self,
        *,
        project_id: int,
        environment: ProjectEnvironment,
        variables: list[ProjectEnvironmentVariable],
        payload: AITestCaseExpandRequest,
        source_case: dict[str, Any],
    ) -> str:
        variable_names = [
            {
                "name": variable.name,
                "is_secret": variable.is_secret,
                "reference": "{{" + variable.name + "}}",
            }
            for variable in variables
        ]
        context = {
            "project_id": project_id,
            "environment": {
                "id": environment.id,
                "name": environment.name,
                "base_url": environment.base_url,
                "description": environment.description,
            },
            "environment_variables": variable_names,
            "source_test_case": source_case,
            "requirement": payload.requirement,
            "generate_count": payload.generate_count,
            "expansion_types": payload.expansion_types,
            "include_assertions": payload.include_assertions,
        }
        return (
            "请基于 source_test_case 扩写新的接口测试用例。必须输出 JSON，且每个用例都必须绑定当前 project_id 和 environment.id。\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )

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

    def _parse_generation_result(
        self,
        *,
        raw_content: str,
        project_id: int,
        environment_id: int,
        include_assertions: bool = True,
        source_case: dict[str, Any] | None = None,
    ) -> AIGeneratedTestCaseResponse:
        try:
            data = self._loads_model_json(raw_content)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 返回结果不是合法 JSON: {exc}",
            ) from exc

        normalized = self._normalize_generation_data(
            data=data,
            project_id=project_id,
            environment_id=environment_id,
            include_assertions=include_assertions,
            source_case=source_case,
        )
        try:
            return AIGeneratedTestCaseResponse.model_validate(normalized)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 返回结果结构校验失败: {exc.errors()}",
            ) from exc

    def _loads_model_json(self, raw_content: str) -> dict[str, Any]:
        text = (raw_content or "").strip()
        if not text:
            raise ValueError("empty content")
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("no JSON object found") from None
            data = json.loads(text[start : end + 1])

        if isinstance(data, list):
            return {"source_summary": "", "cases": data, "warnings": []}
        if not isinstance(data, dict):
            raise ValueError("root is not object")
        return data

    def _normalize_generation_data(
        self,
        *,
        data: dict[str, Any],
        project_id: int,
        environment_id: int,
        include_assertions: bool,
        source_case: dict[str, Any] | None,
    ) -> dict[str, Any]:
        warnings = self._as_string_list(data.get("warnings"))
        cases_value = data.get("cases") or data.get("test_cases") or data.get("data")
        if isinstance(cases_value, dict):
            cases_value = [cases_value]
        if not isinstance(cases_value, list):
            cases_value = []
            warnings.append("AI 未返回 cases 数组")

        cases: list[dict[str, Any]] = []
        for index, raw_case in enumerate(cases_value, start=1):
            if not isinstance(raw_case, dict):
                warnings.append(f"第 {index} 个用例不是对象，已忽略")
                continue
            try:
                normalized_case = self._normalize_case(
                    raw_case,
                    environment_id,
                    include_assertions=include_assertions,
                )
                if source_case and self._removed_all_parameters(source_case, normalized_case):
                    warnings.append(f"第 {index} 个用例疑似删除了全部请求参数，请前端确认是否保留")
                cases.append(normalized_case)
            except ValueError as exc:
                warnings.append(f"第 {index} 个用例已忽略: {exc}")

        return {
            "project_id": project_id,
            "environment_id": environment_id,
            "environment_ids": [environment_id],
            "source_summary": str(data.get("source_summary") or data.get("summary") or ""),
            "cases": cases,
            "warnings": warnings,
        }

    def _normalize_case(
        self,
        data: dict[str, Any],
        environment_id: int,
        *,
        include_assertions: bool,
    ) -> dict[str, Any]:
        method = str(data.get("method") or "GET").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            method = "GET"

        body_type = str(data.get("body_type") or "none")
        if body_type not in {"none", "json", "form_urlencoded", "multipart", "raw_text", "raw_json"}:
            body_type = "none"

        body = data.get("body")
        if body_type == "none":
            body = None

        path = str(data.get("path") or "").strip()
        if not path:
            raise ValueError("path 为空")
        path, query_from_path = self._split_path_and_query(path)
        query_params = data.get("query_params") if isinstance(data.get("query_params"), dict) else {}
        query_params = {**query_from_path, **query_params}

        normalized = {
            "name": str(data.get("name") or "AI 生成接口测试用例")[:128],
            "description": str(data.get("description") or ""),
            "environment_id": environment_id,
            "environment_ids": [environment_id],
            "method": method,
            "path": path,
            "headers": data.get("headers") if isinstance(data.get("headers"), dict) else {},
            "query_params": query_params,
            "body_type": body_type,
            "body": body,
            "assertions": self._normalize_assertions(data.get("assertions")) if include_assertions else [],
            "extractors": self._normalize_extractors(data.get("extractors")),
        }
        TestCaseCreateRequest.model_validate(normalized)
        return normalized

    def _split_path_and_query(self, path: str) -> tuple[str, dict[str, str]]:
        from urllib.parse import parse_qsl, urlsplit

        parsed = urlsplit(path)
        if parsed.scheme and parsed.netloc:
            normalized_path = parsed.path or "/"
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            return normalized_path, query
        if "?" in path:
            normalized_path, raw_query = path.split("?", 1)
            return normalized_path or "/", dict(parse_qsl(raw_query, keep_blank_values=True))
        return path, {}

    def _normalize_assertions(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        allowed = {"status_code", "body_contains", "json_equals"}
        results: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict) or item.get("type") not in allowed:
                continue
            assertion = {"type": item["type"], "expected": item.get("expected")}
            if item["type"] == "json_equals":
                assertion["path"] = item.get("path") or ""
            results.append(assertion)
        return results

    def _normalize_extractors(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        results: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, dict) and item.get("name") and item.get("path"):
                results.append({"name": str(item["name"]), "path": str(item["path"])})
        return results

    def _as_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]

    def _removed_all_parameters(self, source_case: dict[str, Any], generated_case: dict[str, Any]) -> bool:
        source_has_body = source_case.get("body") not in (None, {}, [], "")
        source_has_query = bool(source_case.get("query_params"))
        if not source_has_body and not source_has_query:
            return False

        generated_body_empty = generated_case.get("body") in (None, {}, [], "")
        generated_query_empty = not bool(generated_case.get("query_params"))
        return generated_body_empty and generated_query_empty
