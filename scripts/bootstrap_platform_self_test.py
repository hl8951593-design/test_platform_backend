r"""Build a maintainable TestAuto self-test suite from the running OpenAPI contract.

The script intentionally keeps credentials out of source control.  It creates
route-contract cases for every non-Agent operation, groups them into domain
scenarios, and creates one serial regression plan.  Mutating route probes use
invalid resource IDs or invalid request bodies so rebuilding the suite is safe.

Example (PowerShell):

    $env:TESTAUTO_SELF_TEST_ACCOUNT = "selftest_account"
    $env:TESTAUTO_SELF_TEST_PASSWORD = "..."
    .\.venv\Scripts\python.exe scripts\bootstrap_platform_self_test.py \
        --project-id 10 --environment-id 13 --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
GENERATED_CASE_PREFIX = "COV-"
GENERATED_SCENARIO_PREFIX = "【契约覆盖】"
BUSINESS_CASE_PREFIX = "BIZ-"
BUSINESS_SCENARIO_PREFIX = "【业务闭环】"
MEGA_SCENARIO_PREFIX = "【超大流程】"
MEGA_SCENARIO_NAME = f"{MEGA_SCENARIO_PREFIX}TestAuto 非 Agent 全接口与业务闭环"
MASTER_PLAN_NAME = "【总回归】TestAuto 非 Agent 全接口与业务逻辑"
PROJECT_NAME = "【平台全量自测】TestAuto 非 Agent 回归工程"
MISSING_ID = 2_147_483_000


@dataclass(slots=True)
class Probe:
    tag: str
    method: str
    openapi_path: str
    case_path: str
    query: dict[str, Any]
    body: dict[str, Any] | None
    expected_status: int
    summary: str


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any = None,
        timeout: float = 15,
        absolute: bool = False,
    ) -> tuple[int, Any, dict[str, str]]:
        url = path if absolute else f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return response.status, self._decode(raw, response.headers.get("Content-Type")), dict(response.headers)
        except HTTPError as exc:
            raw = exc.read()
            return exc.code, self._decode(raw, exc.headers.get("Content-Type")), dict(exc.headers)

    @staticmethod
    def _decode(raw: bytes, content_type: str | None) -> Any:
        if not raw:
            return None
        if content_type and "json" in content_type.lower():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"binary_bytes": len(raw)}


def response_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def require_success(status: int, payload: Any, action: str) -> Any:
    if not 200 <= status < 300:
        detail = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        raise RuntimeError(f"{action} failed with HTTP {status}: {detail[:1000]}")
    return response_data(payload)


def login(client: ApiClient, account: str, password: str) -> str:
    status, payload, _ = client.request(
        "POST",
        "/auth/login",
        body={"account": account, "password": password},
    )
    data = require_success(status, payload, "login")
    return str(data["access_token"])


def is_agent_operation(path: str, operation: dict[str, Any]) -> bool:
    if path.startswith("/api/v1/agents"):
        return True
    return any("agent" in str(tag).lower() for tag in operation.get("tags") or [])


def parameter_value(name: str, schema: dict[str, Any], *, method: str, path: str, project_id: int, environment_id: int) -> Any:
    enum = schema.get("enum")
    if enum:
        return enum[0]
    if name == "project_id":
        if method == "DELETE" and path == "/api/v1/test-plan-runs":
            return MISSING_ID
        if method == "DELETE" and path == "/api/v1/projects/{project_id}":
            return MISSING_ID
        return project_id
    if name == "environment_id":
        return environment_id if method == "GET" else MISSING_ID
    if name == "scenario_id":
        return 48 if method == "GET" and not path.endswith("/events") else MISSING_ID
    if name == "run_id":
        return MISSING_ID
    if name == "test_case_id":
        return MISSING_ID
    if name == "execution_type":
        return "scenario"
    if name == "execution_id":
        return MISSING_ID
    if name == "source_type":
        return "plan"
    if name == "source_id":
        return MISSING_ID
    if name == "insight_type":
        return "risk-interfaces"
    if name == "event":
        return "self-test"
    if name == "user_id":
        return MISSING_ID
    if name == "skill_id":
        return "missing-self-test-skill"
    if name.endswith("_id") or name in {"id", "item_id"}:
        return MISSING_ID
    schema_type = schema.get("type")
    if schema_type == "integer":
        return 1
    if schema_type == "boolean":
        return False
    return "self-test"


def all_parameters(path_item: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        if "$ref" in item:
            continue
        merged[(str(item.get("in")), str(item.get("name")))] = item
    return list(merged.values())


def build_probe_request(
    *,
    method: str,
    path: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    project_id: int,
    environment_id: int,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    resolved_path = path
    query: dict[str, Any] = {}
    for parameter in all_parameters(path_item, operation):
        location = parameter.get("in")
        name = str(parameter.get("name"))
        schema = parameter.get("schema") or {}
        if location == "path":
            value = parameter_value(
                name,
                schema,
                method=method,
                path=path,
                project_id=project_id,
                environment_id=environment_id,
            )
            resolved_path = resolved_path.replace("{" + name + "}", str(value))
        elif location == "query" and (parameter.get("required") or name in {"project_id", "environment_id"}):
            query[name] = parameter_value(
                name,
                schema,
                method=method,
                path=path,
                project_id=project_id,
                environment_id=environment_id,
            )

    # These list endpoints are deliberately small while still exercising the real query path.
    if method == "GET":
        query.setdefault("page", 1) if any(p.get("name") == "page" for p in all_parameters(path_item, operation)) else None
        query.setdefault("page_size", 1) if any(p.get("name") == "page_size" for p in all_parameters(path_item, operation)) else None

    body = {} if method in {"POST", "PUT", "PATCH"} else None
    return resolved_path, query, body


def load_openapi(root_client: ApiClient) -> dict[str, Any]:
    status, payload, _ = root_client.request("GET", "/openapi.json")
    return require_success(status, payload, "load OpenAPI")


def build_probes(
    *,
    spec: dict[str, Any],
    root_client: ApiClient,
    project_id: int,
    environment_id: int,
) -> list[Probe]:
    probes: list[Probe] = []
    for path, path_item in sorted(spec["paths"].items()):
        for method_key, operation in sorted(path_item.items()):
            if method_key not in HTTP_METHODS or is_agent_operation(path, operation):
                continue
            method = method_key.upper()
            resolved_path, query, body = build_probe_request(
                method=method,
                path=path,
                path_item=path_item,
                operation=operation,
                project_id=project_id,
                environment_id=environment_id,
            )
            status, payload, _ = root_client.request(
                method,
                resolved_path,
                query=query,
                body=body,
                timeout=20,
            )
            if status >= 500:
                detail = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
                raise RuntimeError(f"unsafe probe exposed HTTP {status}: {method} {resolved_path}: {detail[:800]}")
            tags = operation.get("tags") or ["基础路由"]
            case_path = "http://127.0.0.1:8000/" if path == "/" else resolved_path.removeprefix("/api/v1")
            probes.append(
                Probe(
                    tag=str(tags[0]),
                    method=method,
                    openapi_path=path,
                    case_path=case_path,
                    query=query,
                    body=body,
                    expected_status=status,
                    summary=str(operation.get("summary") or operation.get("operationId") or ""),
                )
            )
    return probes


def list_items(client: ApiClient, path: str) -> list[dict[str, Any]]:
    status, payload, _ = client.request("GET", path)
    data = require_success(status, payload, f"list {path}")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return list(data["items"])
    if isinstance(data, list):
        return data
    raise RuntimeError(f"unexpected list response from {path}")


def delete_generated_assets(client: ApiClient, project_id: int) -> None:
    plans = list_items(client, f"/test-plans?project_id={project_id}&page_size=200")
    for plan in plans:
        if plan.get("name") == MASTER_PLAN_NAME:
            status, payload, _ = client.request("DELETE", f"/test-plans/{plan['id']}?project_id={project_id}")
            require_success(status, payload, f"delete plan {plan['id']}")

    scenarios = list_items(client, f"/scenarios?project_id={project_id}&page_size=200")
    for scenario in scenarios:
        if str(scenario.get("name", "")).startswith(
            (GENERATED_SCENARIO_PREFIX, BUSINESS_SCENARIO_PREFIX, MEGA_SCENARIO_PREFIX)
        ):
            status, payload, _ = client.request("DELETE", f"/scenarios/{scenario['id']}?project_id={project_id}")
            require_success(status, payload, f"delete scenario {scenario['id']}")

    # The project can contain more than one API page after a full rebuild.  Always
    # delete from page one so records shifting after physical deletion are not skipped.
    while True:
        cases = list_items(client, f"/test-cases?project_id={project_id}&page_size=200")
        generated = [
            case for case in cases
            if str(case.get("name", "")).startswith((GENERATED_CASE_PREFIX, BUSINESS_CASE_PREFIX))
        ]
        if not generated:
            break
        for case in generated:
            status, payload, _ = client.request("DELETE", f"/test-cases/{case['id']}?project_id={project_id}")
            require_success(status, payload, f"delete case {case['id']}")


def create_case(client: ApiClient, project_id: int, environment_id: int, index: int, probe: Probe) -> dict[str, Any]:
    body_type = "json" if probe.body is not None else "none"
    payload = {
        "name": f"{GENERATED_CASE_PREFIX}{index:03d} [{probe.tag}] {probe.method} {probe.openapi_path}"[:128],
        "description": (
            f"OpenAPI 全接口契约覆盖。业务域={probe.tag}；说明={probe.summary}；"
            f"安全探测预期 HTTP {probe.expected_status}。正向业务语义由同项目生命周期场景补充。"
        ),
        "environment_id": environment_id,
        "environment_ids": [environment_id],
        "method": probe.method,
        "path": probe.case_path,
        "headers": {"Authorization": "Bearer {{sut_access_token}}"},
        "query_params": probe.query or None,
        "body_type": body_type,
        "body": probe.body,
        "assertions": [{"type": "status_code", "expected": probe.expected_status}],
        "extractors": [],
    }
    status, response, _ = client.request("POST", f"/test-cases?project_id={project_id}", body=payload)
    return require_success(status, response, f"create case {index}")


def scenario_node(case: dict[str, Any], node_index: int, *, login: bool = False) -> dict[str, Any]:
    suffix = "LOGIN" if login else f"{node_index:03d}"
    extractions = [
        {
            "id": f"VAR-{suffix}-{item['name']}",
            "name": item["name"],
            "path": item["path"],
            "masked": any(marker in str(item["name"]).lower() for marker in ("token", "password", "secret", "cookie", "key")),
        }
        for item in (case.get("extractors") or [])
        if isinstance(item, dict) and item.get("name") and item.get("path")
    ]
    return {
        "id": f"NODE-{suffix}",
        "name": "建立被测系统身份" if login else str(case["name"]),
        "before_actions": [],
        "test_case": {
            "id": f"STEP-{suffix}",
            "kind": "api_case",
            "reference_id": int(case["id"]),
            "name": str(case["name"]),
            "method": str(case.get("method") or ""),
            "path": str(case.get("path") or ""),
            "config": {"_scenario_context": {"bindings": [], "extractions": extractions}},
            "continue_on_failure": False if login else True,
        },
        "after_actions": [],
    }


def create_contract_scenarios(
    client: ApiClient,
    *,
    project_id: int,
    environment_id: int,
    login_case: dict[str, Any],
    cases_by_tag: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for tag in sorted(cases_by_tag):
        nodes = [scenario_node(login_case, 0, login=True)]
        nodes.extend(scenario_node(case, index) for index, case in enumerate(cases_by_tag[tag], start=1))
        payload = {
            "name": f"{GENERATED_SCENARIO_PREFIX}{tag}"[:128],
            "description": f"覆盖 {tag} 业务域的全部 OpenAPI 操作；每个步骤使用无副作用安全探测并校验明确状态码。",
            "environment_id": environment_id,
            "tags": ["platform-self-test", "non-agent", "openapi-contract", tag],
            "nodes": nodes,
            "datasets": [],
        }
        status, response, _ = client.request("POST", f"/scenarios?project_id={project_id}", body=payload)
        scenarios.append(require_success(status, response, f"create scenario {tag}"))
    return scenarios


def create_mega_full_scenario(
    client: ApiClient,
    *,
    project_id: int,
    environment_id: int,
    login_case: dict[str, Any],
    cases_by_tag: dict[str, list[dict[str, Any]]],
    business_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_cases = [
        case
        for tag in sorted(cases_by_tag)
        for case in cases_by_tag[tag]
    ]
    nodes = [scenario_node(login_case, 0, login=True)]
    for index, case in enumerate([*business_cases, *contract_cases], start=1):
        node = scenario_node(case, index)
        node["before_actions"] = case.get("_before_actions", [])
        node["after_actions"] = case.get("_after_actions", [])
        nodes.append(node)
    payload = {
        "name": MEGA_SCENARIO_NAME,
        "description": (
            f"单条流程先执行 {len(business_cases)} 个正向业务生命周期用例，再执行"
            f" {len(contract_cases)} 个非 Agent OpenAPI 契约用例；用于验证百级节点的"
            "搭建、维护、运行、诊断与历史查询能力。"
        ),
        "environment_id": environment_id,
        "tags": [
            "platform-self-test",
            "mega-flow",
            "100-plus-cases",
            "non-agent",
            "openapi-contract",
            "business-lifecycle",
        ],
        "nodes": nodes,
        "datasets": [],
    }
    status, response, _ = client.request(
        "POST",
        f"/scenarios?project_id={project_id}",
        body=payload,
        timeout=60,
    )
    return require_success(status, response, "create 100-plus-case scenario")


def create_business_case(
    client: ApiClient,
    *,
    project_id: int,
    environment_id: int,
    definition: dict[str, Any],
) -> dict[str, Any]:
    body = definition.get("body")
    payload = {
        "name": f"{BUSINESS_CASE_PREFIX}{definition['code']} {definition['name']}"[:128],
        "description": definition.get("description") or "平台自测正向业务生命周期步骤。",
        "environment_id": environment_id,
        "environment_ids": [environment_id],
        "method": definition["method"],
        "path": definition["path"],
        "headers": {"Authorization": "Bearer {{sut_access_token}}"},
        "query_params": definition.get("query"),
        "body_type": "json" if body is not None else "none",
        "body": body,
        "assertions": [
            {"type": "status_code", "expected": definition.get("status", 200)},
            *definition.get("assertions", []),
        ],
        "extractors": definition.get("extractors", []),
    }
    if definition.get("retry_policy") is not None:
        payload["retry_policy"] = definition["retry_policy"]
    status, response, _ = client.request("POST", f"/test-cases?project_id={project_id}", body=payload)
    created = require_success(status, response, f"create business case {definition['code']}")
    created["_before_actions"] = definition.get("before_actions", [])
    created["_after_actions"] = definition.get("after_actions", [])
    return created


def create_business_scenario(
    client: ApiClient,
    *,
    project_id: int,
    environment_id: int,
    login_case: dict[str, Any],
    code: str,
    name: str,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes = [scenario_node(login_case, 0, login=True)]
    for index, case in enumerate(cases, start=1):
        node = scenario_node(case, index)
        node["before_actions"] = case.get("_before_actions", [])
        node["after_actions"] = case.get("_after_actions", [])
        nodes.append(node)
    payload = {
        "name": f"{BUSINESS_SCENARIO_PREFIX}{code} {name}"[:128],
        "description": f"{name}的可重复正向生命周期，包含创建、查询、更新、执行/状态推进和清理。",
        "environment_id": environment_id,
        "tags": ["platform-self-test", "business-lifecycle", "non-agent", code.lower()],
        "nodes": nodes,
        "datasets": [],
    }
    status, response, _ = client.request("POST", f"/scenarios?project_id={project_id}", body=payload)
    return require_success(status, response, f"create business scenario {code}")


def random_suffix_action(code: str) -> list[dict[str, Any]]:
    return [{
        "id": f"ACTION-{code}-SUFFIX",
        "kind": "random",
        "name": "生成隔离数据后缀",
        "config": {"type": "string", "length": 10, "output": "run_suffix"},
        "continue_on_failure": False,
    }]


def delay_action(code: str, duration_ms: int) -> list[dict[str, Any]]:
    return [{
        "id": f"ACTION-{code}-WAIT",
        "kind": "delay",
        "name": "等待异步执行落库",
        "config": {"duration_ms": duration_ms},
        "continue_on_failure": True,
    }]


def fixed_value_action(code: str, *, output: str, value: Any, name: str) -> dict[str, Any]:
    return {
        "id": f"ACTION-{code}",
        "kind": "fixed_value",
        "name": name,
        "config": {"output": output, "value": value},
        "continue_on_failure": False,
    }


def condition_action(code: str, *, expression: str, name: str) -> dict[str, Any]:
    return {
        "id": f"ACTION-{code}",
        "kind": "condition",
        "name": name,
        "config": {"expression": expression},
        "continue_on_failure": False,
    }


def script_action(
    code: str,
    *,
    inputs: list[str],
    outputs: list[str],
    source: str,
    name: str,
) -> dict[str, Any]:
    return {
        "id": f"ACTION-{code}",
        "kind": "script",
        "name": name,
        "config": {
            "language": "python",
            "inputs": inputs,
            "outputs": outputs,
            "code": source,
            "timeout_ms": 5000,
        },
        "continue_on_failure": False,
    }


def polling_retry_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "max_attempts": 10,
        "base_delay_ms": 300,
        "max_delay_ms": 1000,
        "jitter": "none",
        "respect_retry_after": True,
        "retry_network_errors": True,
        "retry_timeouts": True,
        "status_codes": [408, 429, 500, 502, 503, 504],
        "retry_unsafe_methods": False,
    }


def e2e_dynamic_case_payload(environment_id: int, *, expected_status: int) -> dict[str, Any]:
    return {
        "name": "{{e2e_case_name}}",
        "description": "端到端故障发现与修复闭环的动态被测用例",
        "environment_id": environment_id,
        "environment_ids": [environment_id],
        "method": "GET",
        "path": "http://127.0.0.1:8000/",
        "headers": {},
        "query_params": None,
        "body_type": "none",
        "body": None,
        "assertions": [{"type": "status_code", "expected": expected_status}],
        "extractors": [],
    }


def e2e_dynamic_scenario_payload(environment_id: int, *, version: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "{{e2e_scenario_name}}",
        "description": "动态绑定用例，验证失败后置动作、版本快照和修复重跑",
        "environment_id": environment_id,
        "tags": ["e2e-business", "failure-repair", "dynamic-binding"],
        "nodes": [{
            "id": "NODE-E2E-DYNAMIC",
            "name": "动态根路由验证",
            "before_actions": [{
                "id": "ACTION-CHILD-EXPECTED-STATUS",
                "kind": "fixed_value",
                "name": "设置根路由期望状态",
                "config": {"output": "expected_root_status", "value": 200},
                "continue_on_failure": False,
            }],
            "test_case": {
                "id": "STEP-E2E-DYNAMIC",
                "kind": "api_case",
                "reference_id": "{{e2e_case_id}}",
                "name": "{{e2e_case_name}}",
                "method": "GET",
                "path": "http://127.0.0.1:8000/",
                "config": {},
                "continue_on_failure": False,
            },
            "after_actions": [{
                "id": "ACTION-CHILD-AFTER-MAIN",
                "kind": "script",
                "name": "记录主用例后的业务校验",
                "config": {
                    "language": "python",
                    "inputs": ["expected_root_status"],
                    "outputs": ["child_after_ran"],
                    "code": "child_after_ran = expected_root_status == 200",
                    "timeout_ms": 5000,
                },
                "continue_on_failure": False,
            }],
        }],
        "datasets": [],
    }
    if version is not None:
        payload["version"] = version
    return payload


def end_to_end_lifecycle_definitions(project_id: int, environment_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    name_builder = script_action(
        "E2E-BUILD-NAMES",
        inputs=["e2e_suffix"],
        outputs=[
            "e2e_case_name",
            "e2e_scenario_name",
            "e2e_plan_name",
            "e2e_defect_title",
            "e2e_idempotency_key",
        ],
        source=(
            'e2e_case_name = "AUTO-E2E-CASE-" + e2e_suffix\n'
            'e2e_scenario_name = "AUTO-E2E-SCENARIO-" + e2e_suffix\n'
            'e2e_plan_name = "AUTO-E2E-PLAN-" + e2e_suffix\n'
            'e2e_defect_title = "AUTO-E2E-DEFECT-" + e2e_suffix\n'
            'e2e_idempotency_key = "auto-e2e-" + e2e_suffix'
        ),
        name="脚本生成跨资源业务名称",
    )
    first_before = [{
        "id": "ACTION-E2E-SUFFIX",
        "kind": "random",
        "name": "生成端到端隔离后缀",
        "config": {"type": "string", "length": 10, "output": "e2e_suffix"},
        "continue_on_failure": False,
    }, fixed_value_action(
        "E2E-DEFECT-URGENCY",
        output="e2e_defect_urgency",
        value="high",
        name="设置缺陷严重级别",
    ), name_builder, condition_action(
        "E2E-NAMES-READY",
        expression='variables["e2e_case_name"] != "" and variables["e2e_plan_name"] != ""',
        name="校验跨资源名称已生成",
    )]
    case_created_after = [script_action(
        "E2E-CASE-CREATED",
        inputs=["e2e_case_id"],
        outputs=["e2e_case_created"],
        source="e2e_case_created = e2e_case_id > 0",
        name="脚本确认动态用例已创建",
    ), condition_action(
        "E2E-CASE-CREATED-GATE",
        expression='variables["e2e_case_created"] == true',
        name="后置校验动态用例创建结果",
    )]
    child_scenario = e2e_dynamic_scenario_payload(environment_id)
    child_scenario_update = e2e_dynamic_scenario_payload(environment_id, version=1)
    repaired_case = e2e_dynamic_case_payload(environment_id, expected_status=200)
    plan_payload = {
        "name": "{{e2e_plan_name}}",
        "description": "动态场景修复后的计划、报告与缺陷关闭闭环",
        "enabled": False,
        "trigger_type": "manual",
        "schedule_timezone": "Asia/Shanghai",
        "environment_ids": [environment_id],
        "targets": [{
            "reference_id": "{{e2e_scenario_id}}",
            "kind": "scenario",
            "sort_order": 1,
            "scenario_version": 2,
        }],
        "execution_mode": "serial",
        "failure_policy": "stop",
        "retry_count": 0,
        "timeout_minutes": 10,
        "notification_emails": [],
        "tags": ["e2e-business", "failure-repair"],
    }
    return [
        {
            "code": "E2E-01", "name": "创建预期失败的动态 HTTP 用例", "method": "POST", "path": "/test-cases", "query": q,
            "body": e2e_dynamic_case_payload(environment_id, expected_status=201), "status": 201,
            "extractors": [{"name": "e2e_case_id", "path": "data.id"}],
            "before_actions": first_before, "after_actions": case_created_after,
        },
        {
            "code": "E2E-02", "name": "验证动态 HTTP 用例已保存", "method": "GET", "path": "/test-cases",
            "query": {**q, "keyword": "{{e2e_case_name}}", "page": 1, "page_size": 20},
            "assertions": [
                {"type": "json_equals", "path": "data.total", "expected": 1},
                {"type": "json_equals", "path": "data.items.0.name", "expected": "{{e2e_case_name}}"},
            ],
        },
        {
            "code": "E2E-03", "name": "将动态用例绑定到业务场景", "method": "POST", "path": "/scenarios", "query": q,
            "body": child_scenario, "status": 201,
            "extractors": [{"name": "e2e_scenario_id", "path": "data.id"}],
            "before_actions": [condition_action(
                "E2E-CREATE-SCENARIO-GATE", expression='variables["e2e_case_created"] == true', name="确认动态用例可用于场景绑定"
            )],
        },
        {
            "code": "E2E-04", "name": "验证场景前置与后置依赖结构", "method": "GET", "path": "/scenarios/{{e2e_scenario_id}}", "query": q,
            "assertions": [
                {"type": "json_equals", "path": "data.current_version", "expected": 1},
                {"type": "json_equals", "path": "data.nodes.0.before_actions.0.kind", "expected": "fixed_value"},
                {"type": "json_equals", "path": "data.nodes.0.after_actions.0.kind", "expected": "script"},
            ],
        },
        {
            "code": "E2E-05", "name": "执行预期失败的动态场景", "method": "POST", "path": "/scenarios/{{e2e_scenario_id}}/execute", "query": q,
            "body": {"environment_id": environment_id, "idempotency_key": "{{e2e_idempotency_key}}-failed"}, "status": 202,
            "extractors": [{"name": "e2e_failed_run_id", "path": "data.runs.0.run_id"}],
            "before_actions": [condition_action(
                "E2E-FAILED-RUN-GATE", expression='variables["e2e_scenario_id"] > 0', name="确认场景已保存后再执行"
            )],
        },
        {
            "code": "E2E-06", "name": "确认失败且后置脚本仍被执行", "method": "GET", "path": "/scenario-runs/{{e2e_failed_run_id}}", "query": q,
            "assertions": [
                {"type": "json_equals", "path": "data.status", "expected": "failed", "retry_on_failure": True},
                {"type": "json_equals", "path": "data.step_results.1.status", "expected": "failed", "retry_on_failure": True},
                {"type": "json_equals", "path": "data.step_results.2.status", "expected": "passed", "retry_on_failure": True},
            ],
            "extractors": [{"name": "e2e_failed_status", "path": "data.status"}],
            "retry_policy": polling_retry_policy(),
            "before_actions": delay_action("E2E-FAILED-RUN", 800),
            "after_actions": [script_action(
                "E2E-FAILURE-CONFIRMED",
                inputs=["e2e_failed_status"], outputs=["e2e_failure_confirmed"],
                source='e2e_failure_confirmed = e2e_failed_status == "failed"', name="脚本确认故障证据"
            ), condition_action(
                "E2E-FAILURE-CONFIRMED-GATE", expression='variables["e2e_failure_confirmed"] == true', name="后置校验故障已确认"
            )],
        },
        {
            "code": "E2E-07", "name": "依据失败运行创建缺陷", "method": "POST", "path": "/defects", "query": q,
            "body": {
                "title": "{{e2e_defect_title}}", "assignee": "self-test", "bug_type": "functional",
                "urgency": "{{e2e_defect_urgency}}", "status": "new",
                "content_html": "<p>动态用例 {{e2e_case_id}} 在场景运行 {{e2e_failed_run_id}} 中失败，进入修复闭环。</p>",
                "media_ids": [],
            },
            "status": 201, "extractors": [{"name": "e2e_defect_id", "path": "data.id"}],
            "before_actions": [condition_action(
                "E2E-CREATE-DEFECT-GATE", expression='variables["e2e_failure_confirmed"] == true', name="仅在故障证据确认后创建缺陷"
            )],
        },
        {
            "code": "E2E-08", "name": "验证缺陷关联失败上下文", "method": "GET", "path": "/defects/{{e2e_defect_id}}", "query": q,
            "assertions": [
                {"type": "json_equals", "path": "data.title", "expected": "{{e2e_defect_title}}"},
                {"type": "json_equals", "path": "data.status", "expected": "new"},
            ],
        },
        {
            "code": "E2E-09", "name": "确认缺陷进入处理队列", "method": "PUT", "path": "/defects/{{e2e_defect_id}}/status", "query": q,
            "body": {"status": "confirmed"},
            "assertions": [{"type": "json_equals", "path": "data.status", "expected": "confirmed"}],
        },
        {
            "code": "E2E-10", "name": "修复动态用例断言", "method": "PUT", "path": "/test-cases/{{e2e_case_id}}", "query": q,
            "body": repaired_case,
            "extractors": [{"name": "e2e_repaired_case_id", "path": "data.id"}],
            "before_actions": [condition_action(
                "E2E-REPAIR-CASE-GATE", expression='variables["e2e_defect_id"] > 0', name="缺陷创建后才允许修复用例"
            )],
            "after_actions": [script_action(
                "E2E-CASE-REPAIRED",
                inputs=["e2e_case_id", "e2e_repaired_case_id"], outputs=["e2e_case_repaired"],
                source="e2e_case_repaired = e2e_case_id == e2e_repaired_case_id", name="脚本校验修复对象身份"
            ), condition_action(
                "E2E-CASE-REPAIRED-GATE", expression='variables["e2e_case_repaired"] == true', name="后置校验用例修复已保存"
            )],
        },
        {
            "code": "E2E-11", "name": "升级场景版本以刷新用例快照", "method": "PUT", "path": "/scenarios/{{e2e_scenario_id}}", "query": q,
            "body": child_scenario_update,
            "assertions": [{"type": "json_equals", "path": "data.current_version", "expected": 2}],
            "extractors": [{"name": "e2e_scenario_version", "path": "data.current_version"}],
            "before_actions": [condition_action(
                "E2E-UPDATE-SCENARIO-GATE", expression='variables["e2e_case_repaired"] == true', name="用例修复后才升级场景版本"
            )],
        },
        {
            "code": "E2E-12", "name": "执行修复后的场景版本", "method": "POST", "path": "/scenarios/{{e2e_scenario_id}}/execute", "query": q,
            "body": {"environment_id": environment_id, "idempotency_key": "{{e2e_idempotency_key}}-repaired"}, "status": 202,
            "extractors": [{"name": "e2e_repaired_run_id", "path": "data.runs.0.run_id"}],
            "before_actions": [condition_action(
                "E2E-REPAIRED-RUN-GATE", expression='variables["e2e_scenario_version"] == 2', name="确认场景版本已升级"
            )],
        },
        {
            "code": "E2E-13", "name": "确认修复运行及前后置动作全部通过", "method": "GET", "path": "/scenario-runs/{{e2e_repaired_run_id}}", "query": q,
            "assertions": [
                {"type": "json_equals", "path": "data.status", "expected": "passed", "retry_on_failure": True},
                {"type": "json_equals", "path": "data.step_results.0.status", "expected": "passed", "retry_on_failure": True},
                {"type": "json_equals", "path": "data.step_results.1.status", "expected": "passed", "retry_on_failure": True},
                {"type": "json_equals", "path": "data.step_results.2.status", "expected": "passed", "retry_on_failure": True},
            ],
            "extractors": [{"name": "e2e_repaired_status", "path": "data.status"}],
            "retry_policy": polling_retry_policy(),
            "before_actions": delay_action("E2E-REPAIRED-RUN", 800),
            "after_actions": [script_action(
                "E2E-REPAIR-CONFIRMED",
                inputs=["e2e_repaired_status"], outputs=["e2e_repair_confirmed"],
                source='e2e_repair_confirmed = e2e_repaired_status == "passed"', name="脚本确认修复运行通过"
            ), condition_action(
                "E2E-REPAIR-CONFIRMED-GATE", expression='variables["e2e_repair_confirmed"] == true', name="后置校验修复结果"
            )],
        },
        {
            "code": "E2E-14", "name": "绑定修复场景创建测试计划", "method": "POST", "path": "/test-plans", "query": q,
            "body": plan_payload, "status": 201,
            "extractors": [{"name": "e2e_plan_id", "path": "data.id"}],
            "before_actions": [condition_action(
                "E2E-CREATE-PLAN-GATE", expression='variables["e2e_repair_confirmed"] == true', name="修复验证通过后才创建计划"
            )],
        },
        {
            "code": "E2E-15", "name": "执行动态测试计划", "method": "POST", "path": "/test-plans/{{e2e_plan_id}}/execute", "query": q,
            "body": {"environment_id": environment_id, "idempotency_key": "{{e2e_idempotency_key}}-plan"}, "status": 202,
            "extractors": [{"name": "e2e_plan_run_id", "path": "data.id"}],
            "before_actions": [condition_action(
                "E2E-EXECUTE-PLAN-GATE", expression='variables["e2e_plan_id"] > 0', name="确认计划已保存后再执行"
            )],
        },
        {
            "code": "E2E-16", "name": "确认测试计划运行通过", "method": "GET", "path": "/test-plan-runs/{{e2e_plan_run_id}}", "query": q,
            "assertions": [{"type": "json_equals", "path": "data.status", "expected": "passed", "retry_on_failure": True}],
            "extractors": [{"name": "e2e_plan_status", "path": "data.status"}],
            "retry_policy": polling_retry_policy(),
            "before_actions": delay_action("E2E-PLAN-RUN", 1500),
            "after_actions": [script_action(
                "E2E-PLAN-CONFIRMED",
                inputs=["e2e_plan_status"], outputs=["e2e_plan_confirmed"],
                source='e2e_plan_confirmed = e2e_plan_status == "passed"', name="脚本确认计划运行通过"
            ), condition_action(
                "E2E-PLAN-CONFIRMED-GATE", expression='variables["e2e_plan_confirmed"] == true', name="后置校验计划终态"
            )],
        },
        {
            "code": "E2E-17", "name": "读取计划结构化报告", "method": "GET", "path": "/reports/plan/{{e2e_plan_run_id}}", "query": q,
            "assertions": [{"type": "json_equals", "path": "data.items.0.status", "expected": "passed"}],
            "extractors": [{"name": "e2e_report_item_id", "path": "data.items.0.id"}],
            "before_actions": [condition_action(
                "E2E-REPORT-GATE", expression='variables["e2e_plan_confirmed"] == true', name="计划通过后才读取报告"
            )],
        },
        {
            "code": "E2E-18", "name": "钻取报告单条执行证据", "method": "GET", "path": "/reports/plan/{{e2e_plan_run_id}}/items/{{e2e_report_item_id}}", "query": q,
            "assertions": [{"type": "json_equals", "path": "data.item.status", "expected": "passed"}],
            "before_actions": [condition_action(
                "E2E-REPORT-ITEM-GATE", expression='variables["e2e_report_item_id"] != null', name="确认报告条目已提取"
            )],
        },
        {
            "code": "E2E-19", "name": "生成计划 HTML 报告", "method": "GET", "path": "/reports/plan/{{e2e_plan_run_id}}/html", "query": q,
            "assertions": [{"type": "body_contains", "expected": "<html"}],
        },
        {
            "code": "E2E-20", "name": "依据通过报告标记缺陷已修复", "method": "PUT", "path": "/defects/{{e2e_defect_id}}/status", "query": q,
            "body": {"status": "fixed"},
            "assertions": [{"type": "json_equals", "path": "data.status", "expected": "fixed"}],
            "before_actions": [condition_action(
                "E2E-FIX-DEFECT-GATE", expression='variables["e2e_plan_confirmed"] == true', name="通过报告后才标记缺陷修复"
            )],
        },
        {
            "code": "E2E-21", "name": "验证缺陷修复结果", "method": "PUT", "path": "/defects/{{e2e_defect_id}}/status", "query": q,
            "body": {"status": "verified"},
            "assertions": [{"type": "json_equals", "path": "data.status", "expected": "verified"}],
        },
        {
            "code": "E2E-22", "name": "关闭已验证缺陷", "method": "PUT", "path": "/defects/{{e2e_defect_id}}/status", "query": q,
            "body": {"status": "closed"},
            "assertions": [{"type": "json_equals", "path": "data.status", "expected": "closed"}],
        },
        {
            "code": "E2E-23", "name": "确认缺陷闭环终态", "method": "GET", "path": "/defects/{{e2e_defect_id}}", "query": q,
            "assertions": [{"type": "json_equals", "path": "data.status", "expected": "closed"}],
        },
        {"code": "E2E-24", "name": "清理动态计划运行", "method": "DELETE", "path": "/test-plan-runs/{{e2e_plan_run_id}}", "query": q},
        {"code": "E2E-25", "name": "清理动态测试计划", "method": "DELETE", "path": "/test-plans/{{e2e_plan_id}}", "query": q},
        {"code": "E2E-26", "name": "清理预期失败场景运行", "method": "DELETE", "path": "/scenario-runs/{{e2e_failed_run_id}}", "query": q},
        {"code": "E2E-27", "name": "清理修复通过场景运行", "method": "DELETE", "path": "/scenario-runs/{{e2e_repaired_run_id}}", "query": q},
        {"code": "E2E-28", "name": "清理动态业务场景", "method": "DELETE", "path": "/scenarios/{{e2e_scenario_id}}", "query": q},
        {"code": "E2E-29", "name": "清理动态 HTTP 用例", "method": "DELETE", "path": "/test-cases/{{e2e_case_id}}", "query": q},
        {"code": "E2E-30", "name": "清理动态缺陷", "method": "DELETE", "path": "/defects/{{e2e_defect_id}}", "query": q},
        {
            "code": "E2E-31", "name": "验证动态用例已清理", "method": "GET", "path": "/test-cases",
            "query": {**q, "keyword": "{{e2e_case_name}}", "page": 1, "page_size": 20},
            "status": 200,
            "assertions": [{"type": "json_equals", "path": "data.total", "expected": 0}],
        },
        {"code": "E2E-32", "name": "验证动态场景已清理", "method": "GET", "path": "/scenarios/{{e2e_scenario_id}}", "query": q, "status": 404},
        {
            "code": "E2E-33", "name": "验证动态缺陷已清理", "method": "GET", "path": "/defects/{{e2e_defect_id}}", "query": q, "status": 404,
            "after_actions": [script_action(
                "E2E-CLEANUP-COMPLETE", inputs=[], outputs=["e2e_cleanup_complete"],
                source="e2e_cleanup_complete = True", name="脚本记录资源清理完成"
            ), condition_action(
                "E2E-CLEANUP-COMPLETE-GATE", expression='variables["e2e_cleanup_complete"] == true', name="后置校验清理结果"
            )],
        },
    ]


def environment_lifecycle_definitions(project_id: int, environment_id: int, bind_case_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    return [
        {"code": "ENV-01", "name": "创建隔离环境", "method": "POST", "path": "/environment-configs", "query": q,
         "body": {"name": "AUTO-ENV-{{run_suffix}}", "base_url": "http://127.0.0.1:8000/api/v1", "description": "自动化生命周期临时环境", "is_default": False},
         "status": 201, "extractors": [{"name": "biz_env_id", "path": "data.id"}], "before_actions": random_suffix_action("ENV")},
        {"code": "ENV-02", "name": "查询环境列表", "method": "GET", "path": "/environment-configs", "query": q},
        {"code": "ENV-03", "name": "查询环境详情", "method": "GET", "path": "/environment-configs/{{biz_env_id}}", "query": q},
        {"code": "ENV-04", "name": "更新环境", "method": "PUT", "path": "/environment-configs/{{biz_env_id}}", "query": q,
         "body": {"name": "AUTO-ENV-U-{{run_suffix}}", "base_url": "http://127.0.0.1:8000/api/v1", "description": "已完成更新校验", "is_default": False}},
        {"code": "ENV-05", "name": "写入环境变量", "method": "POST", "path": "/environment-configs/{{biz_env_id}}/variables", "query": q,
         "body": {"name": "lifecycle_marker", "value": "{{run_suffix}}", "is_secret": False}, "extractors": [{"name": "biz_var_id", "path": "data.id"}]},
        {"code": "ENV-06", "name": "查询环境变量", "method": "GET", "path": "/environment-configs/{{biz_env_id}}/variables", "query": q},
        {"code": "ENV-07", "name": "绑定用例到临时环境", "method": "PUT", "path": f"/environment-configs/test-cases/{bind_case_id}/environment", "query": q,
         "body": {"environment_id": "{{biz_env_id}}"}},
        {"code": "ENV-08", "name": "查询环境绑定用例", "method": "GET", "path": "/environment-configs/{{biz_env_id}}/test-cases", "query": q},
        {"code": "ENV-09", "name": "恢复用例环境绑定", "method": "PUT", "path": f"/environment-configs/test-cases/{bind_case_id}/environment", "query": q,
         "body": {"environment_id": environment_id}},
        {"code": "ENV-10", "name": "删除环境变量", "method": "DELETE", "path": "/environment-configs/{{biz_env_id}}/variables/{{biz_var_id}}", "query": q},
        {"code": "ENV-11", "name": "删除隔离环境", "method": "DELETE", "path": "/environment-configs/{{biz_env_id}}", "query": q},
    ]


def http_lifecycle_definitions(project_id: int, environment_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    case_payload = {
        "name": "AUTO-HTTP-{{run_suffix}}",
        "description": "自动化生命周期临时 HTTP 用例",
        "environment_id": environment_id,
        "environment_ids": [environment_id],
        "method": "GET",
        "path": "http://127.0.0.1:8000/",
        "headers": {},
        "query_params": None,
        "body_type": "none",
        "body": None,
        "assertions": [{"type": "status_code", "expected": 200}],
        "extractors": [],
    }
    updated = dict(case_payload, name="AUTO-HTTP-U-{{run_suffix}}", description="已更新并等待执行")
    unsaved = {key: value for key, value in case_payload.items() if key not in {"name", "description"}}
    return [
        {"code": "HTTP-01", "name": "创建 HTTP 用例", "method": "POST", "path": "/test-cases", "query": q, "body": case_payload,
         "status": 201, "extractors": [{"name": "biz_http_id", "path": "data.id"}], "before_actions": random_suffix_action("HTTP")},
        {"code": "HTTP-02", "name": "查询 HTTP 用例列表", "method": "GET", "path": "/test-cases", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "HTTP-03", "name": "更新 HTTP 用例", "method": "PUT", "path": "/test-cases/{{biz_http_id}}", "query": q, "body": updated},
        {"code": "HTTP-04", "name": "执行未保存 HTTP 用例", "method": "POST", "path": "/test-cases/execute-unsaved", "query": q, "body": unsaved,
         "extractors": [{"name": "biz_http_execution_id", "path": "data.id"}]},
        {"code": "HTTP-05", "name": "异步执行已保存 HTTP 用例", "method": "POST", "path": "/test-cases/{{biz_http_id}}/execute", "query": {**q, "environment_id": environment_id},
         "body": None, "status": 202},
        {"code": "HTTP-06", "name": "批量执行 HTTP 用例", "method": "POST", "path": "/test-cases/batch-execute", "query": q,
         "body": {"test_case_ids": ["{{biz_http_id}}"], "environment_id": environment_id}, "status": 202},
        {"code": "HTTP-07", "name": "删除 HTTP 用例", "method": "DELETE", "path": "/test-cases/{{biz_http_id}}", "query": q},
    ]


def system_case_lifecycle_definitions(project_id: int, relation_case_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    return [
        {"code": "SYS-01", "name": "创建系统测试用例", "method": "POST", "path": f"/projects/{project_id}/system-test-cases",
         "body": {"title": "AUTO-SYS-{{run_suffix}}", "businessModule": "平台自测", "testObjective": "验证系统用例完整生命周期", "priority": "P0", "status": "draft", "tags": ["self-test"]},
         "status": 201, "extractors": [{"name": "biz_system_id", "path": "data.id"}], "before_actions": random_suffix_action("SYS")},
        {"code": "SYS-02", "name": "查询系统用例列表", "method": "GET", "path": f"/projects/{project_id}/system-test-cases", "query": {"page": 1, "page_size": 20}},
        {"code": "SYS-03", "name": "查询 API 关联候选", "method": "GET", "path": f"/projects/{project_id}/system-test-cases/api-candidates", "query": {"page": 1, "page_size": 20}},
        {"code": "SYS-04", "name": "查询系统用例统计", "method": "GET", "path": f"/projects/{project_id}/system-test-cases/statistics"},
        {"code": "SYS-05", "name": "查询系统用例详情", "method": "GET", "path": "/system-test-cases/{{biz_system_id}}", "query": q},
        {"code": "SYS-06", "name": "更新系统测试用例", "method": "PUT", "path": "/system-test-cases/{{biz_system_id}}", "query": q,
         "body": {"title": "AUTO-SYS-U-{{run_suffix}}", "priority": "P1", "status": "enabled", "tags": ["self-test", "updated"]}},
        {"code": "SYS-07", "name": "保存系统用例 API 关系", "method": "PUT", "path": "/system-test-cases/{{biz_system_id}}/relations", "query": q,
         "body": {"relations": [{"apiCaseId": str(relation_case_id), "relationType": "manual", "confidence": 1.0, "sortOrder": 1}]}},
        {"code": "SYS-08", "name": "查询系统用例 API 关系", "method": "GET", "path": "/system-test-cases/{{biz_system_id}}/relations", "query": q},
        {"code": "SYS-09", "name": "复制系统测试用例", "method": "POST", "path": "/system-test-cases/{{biz_system_id}}/duplicate", "query": q, "body": None,
         "status": 200, "extractors": [{"name": "biz_system_copy_id", "path": "data.id"}]},
        {"code": "SYS-10", "name": "批量删除复制用例", "method": "POST", "path": f"/projects/{project_id}/system-test-cases/batch-delete",
         "body": {"ids": ["{{biz_system_copy_id}}"]}},
        {"code": "SYS-11", "name": "删除系统测试用例", "method": "DELETE", "path": "/system-test-cases/{{biz_system_id}}", "query": q},
    ]


def defect_lifecycle_definitions(project_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    return [
        {"code": "DEF-01", "name": "创建缺陷", "method": "POST", "path": "/defects", "query": q,
         "body": {"title": "AUTO-DEF-{{run_suffix}}", "assignee": "self-test", "bug_type": "functional", "urgency": "high", "status": "new", "content_html": "<p>自动化缺陷生命周期</p><script>blocked()</script>", "media_ids": []},
         "status": 201, "extractors": [{"name": "biz_defect_id", "path": "data.id"}], "before_actions": random_suffix_action("DEF")},
        {"code": "DEF-02", "name": "查询缺陷列表", "method": "GET", "path": "/defects", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "DEF-03", "name": "查询缺陷详情", "method": "GET", "path": "/defects/{{biz_defect_id}}", "query": q},
        {"code": "DEF-04", "name": "更新缺陷", "method": "PUT", "path": "/defects/{{biz_defect_id}}", "query": q,
         "body": {"title": "AUTO-DEF-U-{{run_suffix}}", "assignee": "self-test", "bug_type": "functional", "urgency": "medium", "status": "new", "content_html": "<p>已完成更新</p>", "media_ids": []}},
        {"code": "DEF-05", "name": "推进缺陷状态", "method": "PUT", "path": "/defects/{{biz_defect_id}}/status", "query": q, "body": {"status": "confirmed"}},
        {"code": "DEF-06", "name": "删除缺陷", "method": "DELETE", "path": "/defects/{{biz_defect_id}}", "query": q},
    ]


def capture_lifecycle_definitions(project_id: int, environment_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    return [
        {"code": "CAP-01", "name": "创建浏览器采集批次", "method": "POST", "path": "/browser-captures", "query": q,
         "body": {"environment_id": environment_id, "name": "AUTO-CAP-{{run_suffix}}", "source_url": "http://127.0.0.1:5174"},
         "status": 201, "extractors": [{"name": "biz_capture_id", "path": "data.id"}], "before_actions": random_suffix_action("CAP")},
        {"code": "CAP-02", "name": "查询采集批次", "method": "GET", "path": "/browser-captures", "query": q},
        {"code": "CAP-03", "name": "批量同步采集条目", "method": "POST", "path": "/browser-captures/{{biz_capture_id}}/entries/batch", "query": q,
         "body": {"entries": [{"client_entry_id": "entry-{{run_suffix}}", "protocol": "http", "fingerprint": "fp-{{run_suffix}}", "name": "GET 平台根路由", "method": "GET", "path": "/", "source_url": "http://127.0.0.1:8000/", "request_data": {"headers": {}}, "response_data": {"status_code": 200, "body": {"message": "TestAuto API"}}, "draft_data": {}, "status": "captured", "captured_at": "2026-07-15T10:00:00+08:00"}]},
         "extractors": [{"name": "biz_capture_entry_id", "path": "data.0.id"}]},
        {"code": "CAP-04", "name": "查询采集条目", "method": "GET", "path": "/browser-captures/{{biz_capture_id}}/entries", "query": q},
        {"code": "CAP-05", "name": "更新采集条目", "method": "PUT", "path": "/browser-captures/{{biz_capture_id}}/entries/{{biz_capture_entry_id}}", "query": q,
         "body": {"name": "平台根路由（已审阅）", "status": "approved"}},
        {"code": "CAP-06", "name": "更新采集批次", "method": "PUT", "path": "/browser-captures/{{biz_capture_id}}", "query": q,
         "body": {"name": "AUTO-CAP-U-{{run_suffix}}", "status": "reviewing"}},
        {"code": "CAP-07", "name": "导入采集条目为正式用例", "method": "POST", "path": "/browser-captures/{{biz_capture_id}}/import", "query": q,
         "body": {"entry_ids": ["{{biz_capture_entry_id}}"], "environment_id": environment_id, "create_environment_variables": False, "create_scenario": False},
         "extractors": [{"name": "biz_imported_case_id", "path": "data.results.0.asset_id"}]},
        {"code": "CAP-08", "name": "删除导入的临时用例", "method": "DELETE", "path": "/test-cases/{{biz_imported_case_id}}", "query": q},
        {"code": "CAP-09", "name": "删除采集批次", "method": "DELETE", "path": "/browser-captures/{{biz_capture_id}}", "query": q},
    ]


def websocket_lifecycle_definitions(project_id: int, environment_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    ws_config = {"environment_id": environment_id, "environment_ids": [environment_id], "path": "ws://127.0.0.1:8000/ws-self-test-missing", "headers": {}, "subprotocols": [], "messages": [], "receive_count": 0, "connect_timeout_ms": 500, "receive_timeout_ms": 500, "assertions": [], "extractors": []}
    return [
        {"code": "WS-01", "name": "创建 WebSocket 用例", "method": "POST", "path": "/websocket-test-cases", "query": q,
         "body": {**ws_config, "name": "AUTO-WS-{{run_suffix}}", "description": "验证无服务端时的受控失败与执行记录"}, "status": 201,
         "extractors": [{"name": "biz_ws_id", "path": "data.id"}], "before_actions": random_suffix_action("WS")},
        {"code": "WS-02", "name": "查询 WebSocket 用例", "method": "GET", "path": "/websocket-test-cases", "query": q},
        {"code": "WS-03", "name": "更新 WebSocket 用例", "method": "PUT", "path": "/websocket-test-cases/{{biz_ws_id}}", "query": q,
         "body": {**ws_config, "name": "AUTO-WS-U-{{run_suffix}}", "description": "已更新"}},
        {"code": "WS-04", "name": "执行未保存 WebSocket 用例", "method": "POST", "path": "/websocket-test-cases/execute-unsaved", "query": q, "body": ws_config},
        {"code": "WS-05", "name": "异步执行已保存 WebSocket 用例", "method": "POST", "path": "/websocket-test-cases/{{biz_ws_id}}/execute", "query": {**q, "environment_id": environment_id}, "body": None, "status": 202},
        {"code": "WS-06", "name": "批量执行 WebSocket 用例", "method": "POST", "path": "/websocket-test-cases/batch-execute", "query": q,
         "body": {"websocket_test_case_ids": ["{{biz_ws_id}}"], "environment_id": environment_id}, "status": 202},
        {"code": "WS-07", "name": "删除 WebSocket 用例", "method": "DELETE", "path": "/websocket-test-cases/{{biz_ws_id}}", "query": q},
    ]


def scenario_lifecycle_definitions(project_id: int, environment_id: int, reference_case_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    node = {
        "id": "NODE-ROOT",
        "name": "平台根路由",
        "before_actions": [],
        "test_case": {"id": "STEP-ROOT", "kind": "api_case", "reference_id": reference_case_id, "name": "平台根路由", "method": "GET", "path": "http://127.0.0.1:8000/", "config": {}, "continue_on_failure": False},
        "after_actions": [],
    }
    create_payload = {"name": "AUTO-SCENE-{{run_suffix}}", "description": "场景管理生命周期", "environment_id": environment_id, "tags": ["self-test"], "nodes": [node], "datasets": []}
    update_payload = {**create_payload, "name": "AUTO-SCENE-U-{{run_suffix}}", "version": 1}
    return [
        {"code": "SCN-01", "name": "创建场景", "method": "POST", "path": "/scenarios", "query": q, "body": create_payload,
         "status": 201, "extractors": [{"name": "biz_scenario_id", "path": "data.id"}], "before_actions": random_suffix_action("SCN")},
        {"code": "SCN-02", "name": "查询场景列表", "method": "GET", "path": "/scenarios", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "SCN-03", "name": "查询场景详情", "method": "GET", "path": "/scenarios/{{biz_scenario_id}}", "query": q},
        {"code": "SCN-04", "name": "更新场景", "method": "PUT", "path": "/scenarios/{{biz_scenario_id}}", "query": q, "body": update_payload},
        {"code": "SCN-05", "name": "执行场景", "method": "POST", "path": "/scenarios/{{biz_scenario_id}}/execute", "query": q,
         "body": {"environment_id": environment_id, "idempotency_key": "scene-{{run_suffix}}"}, "status": 202,
         "extractors": [{"name": "biz_scenario_run_id", "path": "data.runs.0.run_id"}]},
        {"code": "SCN-06", "name": "查询场景运行列表", "method": "GET", "path": "/scenario-runs", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "SCN-07", "name": "查询场景运行详情", "method": "GET", "path": "/scenario-runs/{{biz_scenario_run_id}}", "query": q,
         "before_actions": delay_action("SCN", 1500)},
        {"code": "SCN-08", "name": "删除场景运行记录", "method": "DELETE", "path": "/scenario-runs/{{biz_scenario_run_id}}", "query": q},
        {"code": "SCN-09", "name": "删除场景", "method": "DELETE", "path": "/scenarios/{{biz_scenario_id}}", "query": q},
        {"code": "SCN-10", "name": "执行脚本动作", "method": "POST", "path": "/scenario-actions/script/execute-unsaved", "query": q,
         "body": {"environment_id": environment_id, "language": "python", "code": "result = value * 2", "inputs": ["value"], "outputs": ["result"], "timeout_ms": 5000, "input_values": {"value": 21}},
         "assertions": [{"type": "json_equals", "path": "data.outputs.result", "expected": 42}]},
    ]


def plan_report_lifecycle_definitions(project_id: int, environment_id: int, target_scenario_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    base = {
        "name": "AUTO-PLAN-{{run_suffix}}", "description": "计划、运行与报告生命周期", "enabled": False,
        "trigger_type": "manual", "schedule_timezone": "Asia/Shanghai", "environment_ids": [environment_id],
        "targets": [{"reference_id": target_scenario_id, "kind": "scenario", "sort_order": 1, "scenario_version": 1}],
        "execution_mode": "serial", "failure_policy": "continue", "retry_count": 0, "timeout_minutes": 10,
        "notification_emails": [], "tags": ["self-test"],
    }
    return [
        {"code": "PLAN-01", "name": "创建测试计划", "method": "POST", "path": "/test-plans", "query": q, "body": base,
         "status": 201, "extractors": [{"name": "biz_plan_id", "path": "data.id"}], "before_actions": random_suffix_action("PLAN")},
        {"code": "PLAN-02", "name": "查询测试计划列表", "method": "GET", "path": "/test-plans", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "PLAN-03", "name": "查询测试计划详情", "method": "GET", "path": "/test-plans/{{biz_plan_id}}", "query": q},
        {"code": "PLAN-04", "name": "更新测试计划", "method": "PUT", "path": "/test-plans/{{biz_plan_id}}", "query": q,
         "body": {**base, "name": "AUTO-PLAN-U-{{run_suffix}}", "version": 1}},
        {"code": "PLAN-05", "name": "启用测试计划", "method": "PUT", "path": "/test-plans/{{biz_plan_id}}/enabled", "query": q,
         "body": {"enabled": True, "version": 2}},
        {"code": "PLAN-06", "name": "查询调度实例", "method": "GET", "path": "/test-plans/schedule", "query": q},
        {"code": "PLAN-07", "name": "导出测试计划", "method": "GET", "path": "/test-plans/export", "query": q},
        {"code": "PLAN-08", "name": "执行测试计划", "method": "POST", "path": "/test-plans/{{biz_plan_id}}/execute", "query": q,
         "body": {"environment_id": environment_id, "idempotency_key": "plan-{{run_suffix}}"}, "status": 202,
         "extractors": [{"name": "biz_plan_run_id", "path": "data.id"}]},
        {"code": "PLAN-09", "name": "查询测试计划运行列表", "method": "GET", "path": "/test-plan-runs", "query": {**q, "page": 1, "page_size": 20},
         "before_actions": delay_action("PLAN", 2500)},
        {"code": "PLAN-10", "name": "查询测试计划运行详情", "method": "GET", "path": "/test-plan-runs/{{biz_plan_run_id}}", "query": q},
        {"code": "RPT-01", "name": "查询报告列表", "method": "GET", "path": "/reports", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "RPT-02", "name": "查询报告趋势", "method": "GET", "path": "/reports/trends", "query": q},
        {"code": "RPT-03", "name": "查询报告智能总览", "method": "GET", "path": "/reports/intelligence-overview", "query": q},
        {"code": "RPT-04", "name": "查询结构化报告", "method": "GET", "path": "/reports/plan/{{biz_plan_run_id}}", "query": q,
         "extractors": [{"name": "biz_report_item_id", "path": "data.items.0.id"}]},
        {"code": "RPT-05", "name": "查询报告单条明细", "method": "GET", "path": "/reports/plan/{{biz_plan_run_id}}/items/{{biz_report_item_id}}", "query": q},
        {"code": "RPT-06", "name": "生成补充用例草稿", "method": "POST", "path": "/reports/plan/{{biz_plan_run_id}}/supplement-case-drafts",
         "body": {"project_id": project_id, "environment_id": environment_id, "scope": "all", "target_case_type": "system_case", "item_ids": [], "prompt": "平台自测补充"}},
        {"code": "RPT-07", "name": "生成报告 HTML", "method": "GET", "path": "/reports/plan/{{biz_plan_run_id}}/html", "query": q},
        {"code": "RPT-08", "name": "创建一次性报告导出", "method": "POST", "path": "/reports/plan/{{biz_plan_run_id}}/exports",
         "body": {"project_id": project_id, "format": "html"}, "extractors": [{"name": "biz_report_download_url", "path": "data.download_url"}]},
        {"code": "RPT-09", "name": "下载一次性报告", "method": "GET", "path": "http://127.0.0.1:8000{{biz_report_download_url}}", "body": None},
        {"code": "PLAN-11", "name": "删除测试计划运行", "method": "DELETE", "path": "/test-plan-runs/{{biz_plan_run_id}}", "query": q},
        {"code": "PLAN-12", "name": "删除测试计划", "method": "DELETE", "path": "/test-plans/{{biz_plan_id}}", "query": q},
    ]


def flow_lifecycle_definitions(project_id: int, environment_id: int, reference_case_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    definition = {
        "schemaVersion": "1.0", "projectId": project_id, "environmentId": environment_id,
        "name": "AUTO-FLOW-{{run_suffix}}", "description": "可视化流程生命周期",
        "nodes": [
            {"id": "start", "kind": "start", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "root", "kind": "api_case", "name": "平台根路由", "referenceId": reference_case_id, "method": "GET", "path": "http://127.0.0.1:8000/", "position": {"x": 220, "y": 0}, "config": {}},
            {"id": "end", "kind": "end", "name": "结束", "position": {"x": 440, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "edge-1", "source": "start", "target": "root", "route": "always"},
            {"id": "edge-2", "source": "root", "target": "end", "route": "always"},
        ],
        "viewport": {"zoom": 1},
    }
    return [
        {"code": "FLOW-01", "name": "创建可视化流程", "method": "POST", "path": "/flows", "query": q,
         "body": {"name": "AUTO-FLOW-{{run_suffix}}", "description": "可视化流程生命周期", "definition": definition}, "status": 201,
         "extractors": [{"name": "biz_flow_id", "path": "data.id"}], "before_actions": random_suffix_action("FLOW")},
        {"code": "FLOW-02", "name": "查询可视化流程列表", "method": "GET", "path": "/flows", "query": q},
        {"code": "FLOW-03", "name": "查询可视化流程详情", "method": "GET", "path": "/flows/{{biz_flow_id}}", "query": q},
        {"code": "FLOW-04", "name": "更新可视化流程", "method": "PUT", "path": "/flows/{{biz_flow_id}}", "query": q,
         "body": {"name": "AUTO-FLOW-U-{{run_suffix}}", "description": "已更新", "definition": {**definition, "name": "AUTO-FLOW-U-{{run_suffix}}"}, "expectedVersion": 1}},
        {"code": "FLOW-05", "name": "执行已保存可视化流程", "method": "POST", "path": "/flows/{{biz_flow_id}}/execute", "query": {**q, "environment_id": environment_id},
         "body": None, "status": 202, "extractors": [{"name": "biz_flow_execution_id", "path": "data.execution_id"}]},
        {"code": "FLOW-06", "name": "执行未保存可视化流程", "method": "POST", "path": "/flows/execute-unsaved", "query": q,
         "body": {"definition": definition}, "before_actions": delay_action("FLOW", 1200)},
        {"code": "FLOW-07", "name": "查询 Flow 结构化报告", "method": "GET", "path": "/reports/flow/{{biz_flow_execution_id}}", "query": q},
        {"code": "FLOW-08", "name": "删除可视化流程", "method": "DELETE", "path": "/flows/{{biz_flow_id}}", "query": q},
    ]


def observability_lifecycle_definitions(project_id: int, environment_id: int, target_scenario_id: int) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    return [
        {"code": "OBS-01", "name": "查询工作台质量总览", "method": "GET", "path": "/dashboard/quality-overview", "query": {**q, "environment_id": environment_id, "range": "7d"}},
        {"code": "OBS-02", "name": "查询项目资产趋势", "method": "GET", "path": "/dashboard/project-asset-trends", "query": {**q, "environment_id": environment_id, "range": "30d"}},
        {"code": "OBS-03", "name": "查询工作台活动明细", "method": "GET", "path": "/dashboard/activity-feed", "query": {**q, "environment_id": environment_id, "page": 1, "page_size": 20}},
        {"code": "OBS-04", "name": "查询工作台风险洞察", "method": "GET", "path": "/dashboard/insights/risk-analysis", "query": {**q, "environment_id": environment_id, "range": "7d", "page": 1, "page_size": 20}},
        {"code": "OBS-05", "name": "发起统一回归任务", "method": "POST", "path": "/dashboard/regression-runs",
         "body": {"project_id": project_id, "environment_id": environment_id, "scope_type": "scenario", "scope_ids": [target_scenario_id], "strategy": "full", "include_http": True, "include_websocket": False, "include_system_cases": False, "trigger_source": "dashboard"},
         "status": 202, "extractors": [{"name": "biz_dashboard_run_id", "path": "data.run_id"}]},
        {"code": "OBS-06", "name": "查询统一回归任务", "method": "GET", "path": "/dashboard/regression-runs/{{biz_dashboard_run_id}}",
         "before_actions": delay_action("OBS", 1800)},
        {"code": "OBS-07", "name": "查询执行中心总览", "method": "GET", "path": "/execution-center/overview", "query": q},
        {"code": "OBS-08", "name": "查询执行队列", "method": "GET", "path": "/execution-center/queue", "query": q},
        {"code": "OBS-09", "name": "查询 Worker 状态", "method": "GET", "path": "/execution-center/workers", "query": q},
        {"code": "OBS-10", "name": "查询执行日志", "method": "GET", "path": "/execution-center/logs", "query": q},
        {"code": "OBS-11", "name": "查询失败诊断", "method": "GET", "path": "/execution-center/failure-diagnosis", "query": q},
        {"code": "OBS-12", "name": "查询执行重试池", "method": "GET", "path": "/execution-center/retries", "query": q},
        {"code": "OBS-13", "name": "查询统一执行记录", "method": "GET", "path": "/execution-records", "query": {**q, "page": 1, "page_size": 20}},
        {"code": "OBS-14", "name": "查询统一执行详情", "method": "GET", "path": "/execution-records/scenario/235", "query": q},
        {"code": "OBS-15", "name": "查询通知中心", "method": "GET", "path": "/notifications", "query": {"page": 1, "page_size": 20}},
        {"code": "OBS-16", "name": "标记全部通知已读", "method": "POST", "path": "/notifications/read-all", "body": None},
    ]


def create_business_lifecycle_scenarios(
    client: ApiClient,
    *,
    project_id: int,
    environment_id: int,
    login_case: dict[str, Any],
    reference_case_id: int,
    target_scenario_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = [
        (
            "E2E",
            "用例、场景、执行、报告与缺陷修复闭环",
            end_to_end_lifecycle_definitions(project_id, environment_id),
        ),
        ("ENV", "环境与变量配置", environment_lifecycle_definitions(project_id, environment_id, reference_case_id)),
        ("HTTP", "HTTP 用例管理与执行", http_lifecycle_definitions(project_id, environment_id)),
        ("SYS", "系统测试用例与 API 关系", system_case_lifecycle_definitions(project_id, reference_case_id)),
        ("DEF", "缺陷状态与富文本安全", defect_lifecycle_definitions(project_id)),
        ("CAP", "浏览器采集、审阅与导入", capture_lifecycle_definitions(project_id, environment_id)),
        ("WS", "WebSocket 用例与受控失败", websocket_lifecycle_definitions(project_id, environment_id)),
        ("SCN", "场景编排、脚本与运行历史", scenario_lifecycle_definitions(project_id, environment_id, reference_case_id)),
        ("PLAN", "测试计划、运行与报告", plan_report_lifecycle_definitions(project_id, environment_id, target_scenario_id)),
        ("FLOW", "可视化流程、执行与报告", flow_lifecycle_definitions(project_id, environment_id, reference_case_id)),
        ("OBS", "工作台、执行中心与通知", observability_lifecycle_definitions(project_id, environment_id, target_scenario_id)),
    ]
    scenarios: list[dict[str, Any]] = []
    business_cases: list[dict[str, Any]] = []
    for code, name, definitions in groups:
        cases = [
            create_business_case(
                client,
                project_id=project_id,
                environment_id=environment_id,
                definition=definition,
            )
            for definition in definitions
        ]
        business_cases.extend(cases)
        scenarios.append(create_business_scenario(
            client,
            project_id=project_id,
            environment_id=environment_id,
            login_case=login_case,
            code=code,
            name=name,
            cases=cases,
        ))
        print(f"created_business_scenario={code} cases={len(cases)}")
    return scenarios, business_cases


def create_master_plan(
    client: ApiClient,
    *,
    project_id: int,
    environment_id: int,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    targets = [
        {
            "reference_id": int(item["id"]),
            "kind": "scenario",
            "sort_order": index,
            "scenario_version": int(item.get("current_version") or 1),
        }
        for index, item in enumerate(scenarios, start=1)
    ]
    payload = {
        "name": MASTER_PLAN_NAME,
        "description": "平台自身作为被测系统：正向业务生命周期 + 全量非 Agent OpenAPI 契约 + 统一运行与报告入口。",
        "enabled": True,
        "trigger_type": "manual",
        "schedule_timezone": "Asia/Shanghai",
        "environment_ids": [environment_id],
        "targets": targets,
        "execution_mode": "serial",
        "failure_policy": "continue",
        "retry_count": 0,
        "timeout_minutes": 30,
        "notification_emails": [],
        "tags": ["platform-self-test", "full-regression", "non-agent", "openapi"],
    }
    status, response, _ = client.request("POST", f"/test-plans?project_id={project_id}", body=payload)
    return require_success(status, response, "create master plan")


def find_login_case(client: ApiClient, project_id: int) -> dict[str, Any]:
    for case in list_items(client, f"/test-cases?project_id={project_id}&page_size=200"):
        if case.get("name") == "SUT-01 登录并提取访问令牌":
            return case
    raise RuntimeError("missing bootstrap login case: SUT-01 登录并提取访问令牌")


def existing_business_scenarios(client: ApiClient, project_id: int) -> list[dict[str, Any]]:
    return [
        item
        for item in list_items(client, f"/scenarios?project_id={project_id}&page_size=200")
        if not str(item.get("name", "")).startswith(
            (GENERATED_SCENARIO_PREFIX, BUSINESS_SCENARIO_PREFIX, MEGA_SCENARIO_PREFIX)
        )
    ]


def update_project_name(client: ApiClient, project_id: int) -> None:
    status, current, _ = client.request("GET", f"/projects/{project_id}")
    project = require_success(status, current, "read project")
    payload = {
        "name": PROJECT_NAME,
        "description": (
            "TestAuto 自举式全量回归工程：覆盖全部非 Agent 接口、核心业务生命周期、"
            "异步执行、报告与维护入口；所有临时业务数据均使用隔离命名或安全探测。"
        ),
    }
    status, response, _ = client.request("PUT", f"/projects/{project_id}", body=payload)
    require_success(status, response, "update project")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--environment-id", type=int, required=True)
    parser.add_argument("--account", default=os.getenv("TESTAUTO_SELF_TEST_ACCOUNT"))
    parser.add_argument("--password", default=os.getenv("TESTAUTO_SELF_TEST_PASSWORD"))
    parser.add_argument("--apply", action="store_true", help="Create or rebuild platform assets")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.account or not args.password:
        raise SystemExit("set TESTAUTO_SELF_TEST_ACCOUNT and TESTAUTO_SELF_TEST_PASSWORD (or pass --account/--password)")

    root_client = ApiClient(args.base_url)
    api_client = ApiClient(f"{args.base_url.rstrip('/')}/api/v1")
    token = login(api_client, args.account, args.password)
    api_client.token = token
    root_client.token = token

    spec = load_openapi(root_client)
    probes = build_probes(
        spec=spec,
        root_client=root_client,
        project_id=args.project_id,
        environment_id=args.environment_id,
    )
    counts: dict[str, int] = defaultdict(int)
    for probe in probes:
        counts[probe.tag] += 1
    print(json.dumps({"non_agent_operations": len(probes), "domains": dict(sorted(counts.items()))}, ensure_ascii=False))
    if not args.apply:
        return 0

    update_project_name(api_client, args.project_id)
    login_case = find_login_case(api_client, args.project_id)
    delete_generated_assets(api_client, args.project_id)

    cases_by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, probe in enumerate(probes, start=1):
        case = create_case(api_client, args.project_id, args.environment_id, index, probe)
        cases_by_tag[probe.tag].append(case)
        if index % 25 == 0:
            print(f"created_cases={index}")

    contract_scenarios = create_contract_scenarios(
        api_client,
        project_id=args.project_id,
        environment_id=args.environment_id,
        login_case=login_case,
        cases_by_tag=cases_by_tag,
    )
    reference_case = cases_by_tag["基础路由"][0]
    target_scenario = next(
        item for item in contract_scenarios
        if item["name"] == f"{GENERATED_SCENARIO_PREFIX}基础路由"
    )
    lifecycle_scenarios, business_cases = create_business_lifecycle_scenarios(
        api_client,
        project_id=args.project_id,
        environment_id=args.environment_id,
        login_case=login_case,
        reference_case_id=int(reference_case["id"]),
        target_scenario_id=int(target_scenario["id"]),
    )
    mega_scenario = create_mega_full_scenario(
        api_client,
        project_id=args.project_id,
        environment_id=args.environment_id,
        login_case=login_case,
        cases_by_tag=cases_by_tag,
        business_cases=business_cases,
    )
    legacy_scenarios = existing_business_scenarios(api_client, args.project_id)
    plan = create_master_plan(
        api_client,
        project_id=args.project_id,
        environment_id=args.environment_id,
        scenarios=[*legacy_scenarios, *lifecycle_scenarios, *contract_scenarios],
    )
    print(
        json.dumps(
            {
                "project_id": args.project_id,
                "created_cases": len(probes),
                "created_contract_scenarios": len(contract_scenarios),
                "mega_scenario_id": mega_scenario["id"],
                "mega_scenario_nodes": 1 + len(probes) + len(business_cases),
                "created_business_scenarios": len(lifecycle_scenarios),
                "legacy_scenarios": len(legacy_scenarios),
                "master_plan_id": plan["id"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
