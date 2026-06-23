import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.ai_skills.base import AISkill, SkillPackage
from app.ai_skills.registry import register_ai_skill
from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.schemas.ai import AIChatMessage, AIChatRequest, AIGeneratedTestCaseResponse
from app.schemas.test_case import TestCaseCreateRequest


class HTTPTestCaseSkill(AISkill):
    skill_id = "http-test-case"

    def __init__(self):
        self.package = SkillPackage(Path(__file__).parent / "packages" / self.skill_id)
        self.name = self.package.metadata.name
        self.description = self.package.metadata.description

    def build_chat_request(self, context: dict[str, Any]) -> AIChatRequest:
        mode = context["mode"]
        system_prompt = self.package.read_text(f"prompts/{mode}_system.md")
        user_prompt = self._expand_user_prompt(context) if mode == "expand" else self._generate_user_prompt(context)
        return AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=system_prompt),
                AIChatMessage(role="user", content=user_prompt),
            ],
            thinking="disabled",
            temperature=0.25 if mode == "expand" else 0.2,
            max_tokens=5000 if mode == "expand" else 4000,
            response_format="json",
        )

    def parse_response(self, raw_content: str, context: dict[str, Any]) -> AIGeneratedTestCaseResponse:
        try:
            data = self._loads_model_json(raw_content)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 返回结果不是合法 JSON: {exc}",
            ) from exc

        normalized = self._normalize_generation_data(
            data=data,
            project_id=context["project_id"],
            environment_id=context["environment_id"],
            include_assertions=context["include_assertions"],
            source_case=context.get("source_test_case"),
        )
        try:
            return AIGeneratedTestCaseResponse.model_validate(normalized)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 返回结果结构校验失败: {exc.errors()}",
            ) from exc

    def _generate_user_prompt(self, context: dict[str, Any]) -> str:
        payload = context["payload"]
        data = {
            "project_id": context["project_id"],
            "environment": self._environment_data(context["environment"]),
            "environment_variables": self._variable_data(context["variables"]),
            "generate_count": payload.generate_count,
            "include_assertions": payload.include_assertions,
            "request_method": payload.request_method,
            "extra_requirements": payload.extra_requirements,
            "interface_text": payload.interface_text,
        }
        return (
            "请根据以下上下文生成接口测试用例。必须输出 JSON，且每个用例都必须绑定到当前 project_id 和 environment_id。\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
        )

    def _expand_user_prompt(self, context: dict[str, Any]) -> str:
        payload = context["payload"]
        data = {
            "project_id": context["project_id"],
            "environment": self._environment_data(context["environment"]),
            "environment_variables": self._variable_data(context["variables"]),
            "source_test_case": context["source_test_case"],
            "requirement": payload.requirement,
            "generate_count": payload.generate_count,
            "expansion_types": payload.expansion_types,
            "include_assertions": payload.include_assertions,
        }
        return (
            "请基于 source_test_case 扩写新的接口测试用例。必须输出 JSON，且每个用例都必须绑定当前 project_id 和 environment.id。\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
        )

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

    def _environment_data(self, environment: ProjectEnvironment) -> dict[str, Any]:
        return {
            "id": environment.id,
            "name": environment.name,
            "base_url": environment.base_url,
            "description": environment.description,
        }

    def _variable_data(self, variables: list[ProjectEnvironmentVariable]) -> list[dict[str, Any]]:
        return [
            {
                "name": variable.name,
                "is_secret": variable.is_secret,
                "reference": "{{" + variable.name + "}}",
            }
            for variable in variables
        ]


register_ai_skill(HTTPTestCaseSkill())
