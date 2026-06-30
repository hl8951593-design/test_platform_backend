# -*- coding: utf-8 -*-
"""Run a live behavior evaluation for the TestAuto Harness Loop Agent.

The script intentionally exercises the public HTTP API rather than importing
service classes, so it catches the same event, summary, and SSE behavior the
frontend depends on.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "needs_human"}
SAVE_CLAIM_RE = re.compile(
    r"(保存成功|已保存成功|已经保存成功|已保存为正式|已经保存为正式|正式场景已保存|正式场景已经保存|已创建正式|已经创建正式)"
)
NON_AUTH_FIX_KEYWORDS = ("companyName 未动态", "ipPatentId 未动态", "groupIds 硬编码", "硬编码", "未动态绑定", "未动态提取")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    conversation_key: str
    intent: str
    max_iterations: int = 3
    timeout_seconds: float = 240.0


CASES = [
    EvalCase(
        case_id="T01",
        name="通用测试知识问答",
        conversation_key="general",
        intent="用不超过150字回答：边界值分析和等价类划分有什么区别？请给一个登录接口的API测试例子。",
    ),
    EvalCase(
        case_id="T02",
        name="多轮上下文追问且不创建对象",
        conversation_key="general",
        intent="基于上一个登录接口例子，列出6条测试用例标题；不要创建平台对象，每条不超过18字。",
    ),
    EvalCase(
        case_id="T03",
        name="读取项目上下文",
        conversation_key="project",
        intent="请读取当前项目上下文，并用不超过160字说明你看到的测试资源、默认环境和是否已有场景。",
        max_iterations=4,
    ),
    EvalCase(
        case_id="T04",
        name="企业场景 query-first 组合草稿",
        conversation_key="scenario",
        intent=(
            "请基于当前项目已有用例组合一个企业相关场景草稿，不要保存；"
            "需要你先分析每个候选用例用途、请求字段、响应字段和可复用变量，"
            "再进行场景组合。"
        ),
        max_iterations=6,
        timeout_seconds=720.0,
    ),
    EvalCase(
        case_id="T05",
        name="场景 warnings 可修复项闭环",
        conversation_key="scenario",
        intent=(
            "如果你发现除鉴权令牌外还有可自动修复项，请继续自动修复并验证；"
            "只有真正需要我提供的信息才问我。不要保存正式场景。"
        ),
        max_iterations=6,
        timeout_seconds=720.0,
    ),
    EvalCase(
        case_id="T06",
        name="保存正式场景边界",
        conversation_key="scenario",
        intent="把刚才的场景直接保存成正式场景，不要问我。",
        max_iterations=4,
        timeout_seconds=360.0,
    ),
    EvalCase(
        case_id="T07",
        name="数据集参数化理解与草稿更新",
        conversation_key="scenario",
        intent=(
            "对于企业场景组合，companyId 不应该只取第一个；"
            "请说明如何用数据集覆盖多个企业，并在需要时更新草稿。不要保存。"
        ),
        max_iterations=6,
        timeout_seconds=720.0,
    ),
    EvalCase(
        case_id="T08",
        name="非测试领域能力边界",
        conversation_key="boundary",
        intent="帮我写一首情诗。",
    ),
]


class ApiClient:
    def __init__(self, base_url: str, account: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.account = account
        self.password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_acquired_at = 0.0

    def login(self) -> dict[str, Any]:
        payload = {"account": self.account, "password": self.password}
        response = self.request_json("POST", "/auth/login", payload=payload, auth=False)
        data = unwrap(response)
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.token_acquired_at = time.monotonic()
        user = data.get("user") or {}
        return {
            "account": user.get("account"),
            "user_id": user.get("id"),
            "is_admin": user.get("is_admin"),
            "token_type": data.get("token_type"),
        }

    def ensure_token(self) -> None:
        if self.access_token is None or time.monotonic() - self.token_acquired_at > 20 * 60:
            self.login()

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        auth: bool = True,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if auth:
            self.ensure_token()
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {method} {path}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"request failed {method} {path}: {exc}") from exc
        return json.loads(raw) if raw else {}

    def request_sse_text(self, path: str, last_event_id: int, timeout: float = 30.0) -> str:
        self.ensure_token()
        url = self.base_url + path
        headers = {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.access_token}",
            "Last-Event-ID": str(last_event_id),
        }
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} SSE {path}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"SSE request failed {path}: {exc}") from exc


def unwrap(response: dict[str, Any]) -> Any:
    if "data" in response:
        return response["data"]
    return response


def collect_tool_call_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "tool_call_id" and isinstance(item, str):
                found.add(item)
            else:
                found.update(collect_tool_call_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(collect_tool_call_ids(item))
    return found


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def seconds_between(start: str | None, end: str | None) -> float | None:
    started = parse_iso(start)
    ended = parse_iso(end)
    if not started or not ended:
        return None
    return max((ended - started).total_seconds(), 0.0)


def safe_snippet(text: str, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def sse_stats(raw: str) -> dict[str, Any]:
    event_types = re.findall(r"^event:\s*(.+)$", raw, flags=re.M)
    non_heartbeat = [item for item in event_types if item != "heartbeat"]
    return {
        "byte_length": len(raw.encode("utf-8")),
        "event_count": len(event_types),
        "non_heartbeat_event_count": len(non_heartbeat),
        "heartbeat_only": bool(event_types) and not non_heartbeat,
        "first_events": event_types[:8],
    }


def run_case(client: ApiClient, project_id: int, case: EvalCase, conversation_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "intent": case.intent,
        "max_iterations": case.max_iterations,
        "auto_complete": False,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    created_at = time.monotonic()
    created = unwrap(client.request_json("POST", "/agents/runs", payload=payload))
    run_id = created["run_id"]
    current_conversation_id = created.get("conversation_id") or conversation_id

    events: list[dict[str, Any]] = []
    last_sequence = 0
    terminal = False
    deadline = time.monotonic() + case.timeout_seconds
    poll_count = 0
    first_delta_at: float | None = None

    while time.monotonic() < deadline:
        time.sleep(0.6)
        poll_count += 1
        snapshot = unwrap(
            client.request_json(
                "GET",
                f"/agents/runs/{run_id}/events/snapshot",
                query={"after_sequence": last_sequence, "limit": 500},
                timeout=30.0,
            )
        )
        new_events = snapshot.get("events") or []
        for event in new_events:
            events.append(event)
            if event.get("event_type") == "model.delta" and first_delta_at is None:
                first_delta_at = time.monotonic()
        if new_events:
            last_sequence = snapshot.get("next_after_sequence") or new_events[-1].get("event_seq") or last_sequence
        terminal = bool(snapshot.get("terminal")) and last_sequence >= (snapshot.get("latest_event_sequence") or 0)
        if terminal:
            break

    summary = unwrap(client.request_json("GET", f"/agents/runs/{run_id}/summary", timeout=30.0))
    event_types = [event.get("event_type") for event in events]
    model_call_ids = [
        ((event.get("payload_json") or {}).get("model_call_id"))
        for event in events
        if event.get("event_type") == "model.started"
    ]
    model_call_ids = [item for item in model_call_ids if item]
    loop_steps = [
        ((event.get("payload_json") or {}).get("loop_step"))
        for event in events
        if (event.get("payload_json") or {}).get("loop_step")
    ]
    ordered_tool_ids: list[str] = []
    seen_tool_ids: set[str] = set()
    for event in events:
        for tool_call_id in collect_tool_call_ids(event.get("payload_json")):
            if tool_call_id not in seen_tool_ids:
                ordered_tool_ids.append(tool_call_id)
                seen_tool_ids.add(tool_call_id)
    result_json = (summary.get("run") or {}).get("result_json") or {}
    for tool_call_id in sorted(collect_tool_call_ids(result_json)):
        if tool_call_id not in seen_tool_ids:
            ordered_tool_ids.append(tool_call_id)
            seen_tool_ids.add(tool_call_id)

    tool_calls = []
    for tool_call_id in ordered_tool_ids:
        try:
            tool_call = unwrap(client.request_json("GET", f"/agents/tool-calls/{tool_call_id}", timeout=30.0))
            tool_calls.append(tool_call)
        except Exception as exc:  # pragma: no cover - diagnostic path
            tool_calls.append({"tool_call_id": tool_call_id, "fetch_error": str(exc)})

    try:
        sse_raw = client.request_sse_text(f"/agents/runs/{run_id}/events", last_event_id=999999, timeout=60.0)
        replay_sse = sse_stats(sse_raw)
    except Exception as exc:  # pragma: no cover - diagnostic path
        replay_sse = {"error": str(exc), "event_count": 0, "non_heartbeat_event_count": 0, "heartbeat_only": False}

    assistant_message = summary.get("assistant_message") or ""
    status = ((summary.get("run") or {}).get("status")) or created.get("status")
    first_delta_seconds = None if first_delta_at is None else round(first_delta_at - created_at, 3)
    completed_seconds = seconds_between((summary.get("run") or {}).get("created_at"), (summary.get("run") or {}).get("completed_at"))

    result = {
        "case_id": case.case_id,
        "name": case.name,
        "intent": case.intent,
        "run_id": run_id,
        "conversation_id": current_conversation_id,
        "status": status,
        "terminal": summary.get("terminal"),
        "assistant_visible": summary.get("assistant_visible"),
        "assistant_message": assistant_message,
        "assistant_message_length": len(assistant_message),
        "assistant_message_snippet": safe_snippet(assistant_message),
        "completion_source": summary.get("completion_source"),
        "model": summary.get("model"),
        "finish_reason": summary.get("finish_reason"),
        "usage": summary.get("usage"),
        "event_count": summary.get("event_count"),
        "latest_event_sequence": summary.get("latest_event_sequence"),
        "event_types": event_types,
        "model_delta_count": event_types.count("model.delta"),
        "model_started_count": event_types.count("model.started"),
        "model_call_count": len(set(model_call_ids)),
        "loop_steps": loop_steps,
        "tool_request_repair_count": event_types.count("model.tool_request_repaired"),
        "required_tool_repair_count": event_types.count("model.required_tool_repaired"),
        "context_compaction_count": (
            event_types.count("conversation.compacted")
            + event_types.count("conversation.context_compacted")
            + event_types.count("memory.context_compacted")
        ),
        "tool_event_count": sum(1 for item in event_types if str(item).startswith("tool.")),
        "tool_calls": summarize_tool_calls(tool_calls),
        "tool_names": [item.get("tool_name") for item in summarize_tool_calls(tool_calls) if item.get("tool_name")],
        "first_delta_seconds": first_delta_seconds,
        "completed_seconds": round(completed_seconds, 3) if completed_seconds is not None else None,
        "poll_count": poll_count,
        "snapshot_terminal_seen": terminal,
        "sse_high_cursor_replay": replay_sse,
    }
    result["evaluation"] = evaluate_case(result)
    return result


def summarize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for call in tool_calls:
        output = call.get("output_json_redacted")
        input_json = call.get("input_json_redacted")
        summaries.append(
            {
                "tool_call_id": call.get("tool_call_id"),
                "tool_name": call.get("tool_name"),
                "status": call.get("status"),
                "execution_phase": call.get("execution_phase"),
                "resolved_side_effect_class": call.get("resolved_side_effect_class"),
                "input_json_redacted": input_json,
                "output_has_warning_like_fields": has_warning_like_fields(output),
                "output_warning_snippet": warning_snippet(output),
            }
        )
    return summaries


def has_warning_like_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"warning", "warnings", "issue", "issues", "diagnostic", "diagnostics", "errors"}:
                if item:
                    return True
            if has_warning_like_fields(item):
                return True
    elif isinstance(value, list):
        return any(has_warning_like_fields(item) for item in value)
    return False


def warning_snippet(value: Any) -> str:
    chunks: list[str] = []

    def visit(item: Any, path: str = "") -> None:
        if len(chunks) >= 6:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                lower = str(key).lower()
                child_path = f"{path}.{key}" if path else str(key)
                if lower in {"warning", "warnings", "issue", "issues", "diagnostic", "diagnostics", "errors"} and child:
                    chunks.append(f"{child_path}: {safe_snippet(json.dumps(child, ensure_ascii=False), 180)}")
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item[:5]):
                visit(child, f"{path}[{index}]")

    visit(value)
    return " | ".join(chunks)


def evaluate_common(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    passes: list[str] = []
    issues: list[str] = []
    if result["status"] == "completed" and result["terminal"]:
        passes.append("run 已 completed 且 summary terminal=true")
    else:
        issues.append(f"run 未正常 completed，status={result['status']} terminal={result['terminal']}")
    if result["assistant_visible"] and result["assistant_message_length"] > 0:
        passes.append("最终 assistant_message 可见且非空")
    else:
        issues.append("最终 assistant_message 不可见或为空")
    if result["model_started_count"] > 0 and result["model_delta_count"] > 0:
        passes.append("事件链包含 model.started 与 model.delta")
    else:
        issues.append("事件链缺少 model.started 或 model.delta")
    if result.get("model_call_count", 0) == result["model_started_count"]:
        passes.append("model.started 事件携带可追踪 model_call_id")
    else:
        issues.append("model.started 事件缺少完整 model_call_id 追踪")
    sse = result["sse_high_cursor_replay"]
    if sse.get("non_heartbeat_event_count", 0) > 0 and not sse.get("heartbeat_only"):
        passes.append("SSE 超大 Last-Event-ID 可重放非 heartbeat 事件")
    else:
        issues.append(f"SSE 超大 Last-Event-ID 未重放有效事件：{sse}")
    return passes, issues


def evaluate_case(result: dict[str, Any]) -> dict[str, Any]:
    passes, issues = evaluate_common(result)
    message = result["assistant_message"]
    tool_names = result["tool_names"]
    case_id = result["case_id"]

    if case_id == "T01":
        if not tool_names:
            passes.append("通用测试问答未调用平台工具")
        else:
            issues.append(f"通用测试问答不应调用工具，实际={tool_names}")
        if all(word in message for word in ("边界", "等价")) and ("登录" in message or "接口" in message):
            passes.append("回答覆盖边界值、等价类和 API 示例")
        else:
            issues.append("回答未完整覆盖边界值/等价类/API 示例")
    elif case_id == "T02":
        if not tool_names:
            passes.append("上下文追问未创建平台对象")
        else:
            issues.append(f"上下文追问不应调用工具，实际={tool_names}")
        if not SAVE_CLAIM_RE.search(message):
            passes.append("未声称保存或创建平台对象")
        else:
            issues.append("出现保存/正式创建类声称")
        login_context_markers = ("登录", "密码", "账号", "用户名", "token", "验证码")
        case_title_markers = ("边界", "有效", "无效", "为空", "长度", "等价")
        item_count = len(re.findall(r"\d+[.、]|-", message))
        if any(word in message for word in login_context_markers) and (
            item_count >= 3 or sum(1 for word in case_title_markers if word in message) >= 2
        ):
            passes.append("沿用登录接口上下文并输出多条标题")
        else:
            issues.append("未明显沿用登录接口上下文或条目数量不足")
    elif case_id == "T03":
        if "project.read_context" in tool_names:
            passes.append("按需调用 project.read_context")
        else:
            issues.append(f"读取项目上下文未调用 project.read_context，实际={tool_names}")
        if any(word in message for word in ("项目", "环境", "用例", "场景", "测试资源")):
            passes.append("最终回复基于项目/环境/资源维度总结")
        else:
            issues.append("最终回复缺少项目上下文总结")
    elif case_id == "T04":
        evaluate_scenario_compose(result, passes, issues)
    elif case_id == "T05":
        if not SAVE_CLAIM_RE.search(message):
            passes.append("修复闭环追问未声称保存正式对象")
        else:
            issues.append("修复闭环追问出现保存正式对象声称")
        if any(name == "scenario.compose_draft" for name in tool_names) or "已修复" in message or "除鉴权" in message:
            passes.append("对可修复项作出继续处理或明确状态说明")
        else:
            issues.append("未体现继续修复/验证，也未说明可修复项状态")
        if leaves_non_auth_to_user(message):
            issues.append("仍把非鉴权类可修复项直接交给用户处理")
        else:
            passes.append("未把明显非鉴权可修复项直接甩给用户")
    elif case_id == "T06":
        if not SAVE_CLAIM_RE.search(message):
            passes.append("没有声称保存正式场景")
        else:
            issues.append("错误声称已保存正式场景")
        if any(word in message for word in ("无法", "不能", "当前", "工具", "保存", "草稿", "正式场景")):
            passes.append("对无保存工具/正式保存边界有说明")
        else:
            issues.append("未清晰说明保存边界")
    elif case_id == "T07":
        if any(word in message for word in ("数据集", "多", "循环", "companyId", "前")):
            passes.append("理解 companyId 多企业数据集参数化诉求")
        else:
            issues.append("未体现多企业数据集参数化理解")
        if any(input_has_include_datasets_true(call.get("input_json_redacted")) for call in result["tool_calls"]):
            passes.append("草稿更新工具请求包含 include_datasets=true")
        else:
            issues.append("未发现 include_datasets=true 的草稿更新工具请求")
        if not SAVE_CLAIM_RE.search(message):
            passes.append("数据集更新未声称保存正式对象")
        else:
            issues.append("数据集更新错误声称保存正式对象")
    elif case_id == "T08":
        if not tool_names:
            passes.append("非测试领域请求未调用平台工具")
        else:
            issues.append(f"非测试领域请求不应调用工具，实际={tool_names}")
        if any(word in message for word in ("测试", "TestAuto", "能力边界", "自动化")):
            passes.append("说明测试领域能力边界")
        else:
            issues.append("未说明测试领域能力边界")

    score = max(0, round(100 * len(passes) / max(len(passes) + len(issues), 1)))
    return {"score": score, "passed": not issues, "passes": passes, "issues": issues}


def evaluate_scenario_compose(result: dict[str, Any], passes: list[str], issues: list[str]) -> None:
    tool_names = result["tool_names"]
    message = result["assistant_message"]
    query_positions = [idx for idx, name in enumerate(tool_names) if name == "testcase.query_project_cases"]
    compose_positions = [idx for idx, name in enumerate(tool_names) if name == "scenario.compose_draft"]
    if query_positions:
        passes.append("场景组合先读取项目用例")
    else:
        issues.append(f"场景组合缺少 testcase.query_project_cases，实际={tool_names}")
    if compose_positions:
        passes.append("调用 scenario.compose_draft 生成草稿")
    else:
        issues.append("未调用 scenario.compose_draft 生成场景草稿")
    if query_positions and compose_positions and min(query_positions) < min(compose_positions):
        passes.append("工具调用顺序满足 query-first")
    elif query_positions and compose_positions:
        issues.append(f"工具调用顺序不满足 query-first：{tool_names}")
    if not SAVE_CLAIM_RE.search(message):
        passes.append("未声称保存正式场景")
    else:
        issues.append("错误声称保存正式场景")
    compose_warning_calls = [
        call for call in result["tool_calls"]
        if call.get("tool_name") == "scenario.compose_draft" and call.get("output_has_warning_like_fields")
    ]
    if len(compose_positions) >= 2:
        passes.append("检测到多次 compose，具备 warnings 修复闭环迹象")
    elif compose_warning_calls and compose_warnings_are_auth_blocked(compose_warning_calls, message):
        passes.append("compose warning 主要由鉴权/未授权阻断导致，最终回复未把非鉴权可修复项直接甩给用户")
    elif compose_warning_calls:
        issues.append("compose 输出存在 warning/issue，但未观察到再次 compose 修复")
    else:
        passes.append("工具输出未暴露需二次修复的 warning/issue")
    if leaves_non_auth_to_user(message):
        issues.append("最终回复仍把非鉴权类可修复项直接交给用户处理")
    else:
        passes.append("最终回复未把明显非鉴权可修复项直接甩给用户")


def leaves_non_auth_to_user(message: str) -> bool:
    if not any(keyword in message for keyword in NON_AUTH_FIX_KEYWORDS):
        return False
    if "已修复" in message or "自动修复" in message:
        return False
    return any(word in message for word in ("建议你", "请在", "需要你", "手动", "补充"))


def compose_warnings_are_auth_blocked(calls: list[dict[str, Any]], message: str) -> bool:
    text = "\n".join(str(call.get("output_warning_snippet") or "") for call in calls)
    combined = f"{text}\n{message}"
    auth_markers = ("鉴权", "未授权", "授权", "token", "Token", "令牌", "90001", "Lingxi-Auth")
    if not any(marker in combined for marker in auth_markers):
        return False
    return not leaves_non_auth_to_user(message)


def input_has_include_datasets_true(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "include_datasets" and item is True:
                return True
            if input_has_include_datasets_true(item):
                return True
    elif isinstance(value, list):
        return any(input_has_include_datasets_true(item) for item in value)
    return False


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_progress(path: Path | None, message: str) -> None:
    print(message, flush=True)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# woagent 运行返回与问题理解完整评测报告",
        "",
        f"- 评测时间：{payload['generated_at']}",
        f"- Base URL：`{payload['base_url']}`",
        f"- 项目 ID：`{payload['project_id']}`",
        f"- 登录用户：`{payload['login_user'].get('account')}` / user_id=`{payload['login_user'].get('user_id')}`",
        f"- 总用例数：{payload['summary']['case_count']}",
        f"- 通过用例数：{payload['summary']['passed_count']}",
        f"- 平均分：{payload['summary']['average_score']}",
        "",
        "## 结论",
        "",
    ]
    if payload["summary"]["failed_count"] == 0:
        lines.append("本轮评测所有用例通过，事件流、工具链顺序和最终用户可见回复均未发现阻断问题。")
    else:
        lines.append(
            f"本轮评测存在 {payload['summary']['failed_count']} 个未完全通过用例，"
            "需要重点查看下方“问题清单”。"
        )
    lines.extend(["", "## 问题清单", ""])
    any_issue = False
    for result in payload["results"]:
        issues = result["evaluation"]["issues"]
        if not issues:
            continue
        any_issue = True
        lines.append(f"### {result['case_id']} {result['name']}")
        for issue in issues:
            lines.append(f"- {issue}")
        lines.append("")
    if not any_issue:
        lines.append("- 无。")
        lines.append("")

    lines.extend(["## 用例明细", ""])
    for result in payload["results"]:
        evaluation = result["evaluation"]
        lines.extend(
            [
                f"### {result['case_id']} {result['name']}",
                "",
                f"- Run ID：`{result['run_id']}`",
                f"- Conversation ID：`{result['conversation_id']}`",
                f"- 状态：`{result['status']}`，分数：{evaluation['score']}，通过：{evaluation['passed']}",
                f"- 耗时：completed={result['completed_seconds']}s，first_delta={result['first_delta_seconds']}s",
                f"- 事件：event_count={result['event_count']}，model_delta={result['model_delta_count']}，tool_event={result['tool_event_count']}",
                (
                    f"- Loop 指标：model_call={result.get('model_call_count')}，"
                    f"tool_request_repair={result.get('tool_request_repair_count')}，"
                    f"required_tool_repair={result.get('required_tool_repair_count')}，"
                    f"context_compaction={result.get('context_compaction_count')}"
                ),
                f"- SSE 高 cursor 重放：non_heartbeat={result['sse_high_cursor_replay'].get('non_heartbeat_event_count')}，heartbeat_only={result['sse_high_cursor_replay'].get('heartbeat_only')}",
                f"- 工具链：`{', '.join(result['tool_names']) if result['tool_names'] else '无'}`",
                "",
                "通过点：",
            ]
        )
        for item in evaluation["passes"]:
            lines.append(f"- {item}")
        if evaluation["issues"]:
            lines.append("")
            lines.append("问题：")
            for item in evaluation["issues"]:
                lines.append(f"- {item}")
        lines.extend(["", "最终回复摘录：", "", f"> {result['assistant_message_snippet']}", ""])
        warning_lines = [
            f"- `{call.get('tool_name')}` warning: {call.get('output_warning_snippet')}"
            for call in result["tool_calls"]
            if call.get("output_warning_snippet")
        ]
        if warning_lines:
            lines.append("工具 warning 摘录：")
            lines.extend(warning_lines)
            lines.append("")

    lines.extend(
        [
            "## 原始产物",
            "",
            f"- JSON：`{payload['json_path']}`",
            f"- Markdown：`{payload['markdown_path']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate woagent live behavior through HTTP API.")
    parser.add_argument("--base-url", default=os.getenv("AGENT_EVAL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--account", default=os.getenv("AGENT_EVAL_ACCOUNT", "admin"))
    parser.add_argument("--password", default=os.getenv("AGENT_EVAL_PASSWORD"))
    parser.add_argument("--project-id", type=int, default=int(os.getenv("AGENT_EVAL_PROJECT_ID", "1")))
    parser.add_argument("--output-prefix", default=None)
    parser.add_argument("--progress-file", default=None)
    args = parser.parse_args()

    if not args.password:
        print("AGENT_EVAL_PASSWORD or --password is required", file=sys.stderr)
        return 2

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_prefix = Path(args.output_prefix or f"reports/woagent_behavior_eval_{timestamp}")
    progress_path = Path(args.progress_file) if args.progress_file else None
    json_path = output_prefix.with_suffix(".json")
    markdown_path = output_prefix.with_suffix(".md")

    client = ApiClient(args.base_url, args.account, args.password)
    login_user = client.login()
    append_progress(progress_path, f"[login] account={login_user.get('account')} user_id={login_user.get('user_id')}")

    conversations: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    for case in CASES:
        append_progress(progress_path, f"[start] {case.case_id} {case.name}")
        try:
            result = run_case(client, args.project_id, case, conversations.get(case.conversation_key))
            if result.get("conversation_id"):
                conversations[case.conversation_key] = result["conversation_id"]
            results.append(result)
            append_progress(
                progress_path,
                (
                    f"[done] {case.case_id} score={result['evaluation']['score']} "
                    f"passed={result['evaluation']['passed']} run_id={result['run_id']}"
                ),
            )
        except Exception as exc:  # pragma: no cover - live diagnostic path
            error_result = {
                "case_id": case.case_id,
                "name": case.name,
                "intent": case.intent,
                "error": str(exc),
                "evaluation": {
                    "score": 0,
                    "passed": False,
                    "passes": [],
                    "issues": [str(exc)],
                },
            }
            results.append(error_result)
            append_progress(progress_path, f"[error] {case.case_id} {exc}")

    passed_count = sum(1 for item in results if item.get("evaluation", {}).get("passed"))
    scores = [item.get("evaluation", {}).get("score", 0) for item in results]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "project_id": args.project_id,
        "login_user": login_user,
        "summary": {
            "case_count": len(results),
            "passed_count": passed_count,
            "failed_count": len(results) - passed_count,
            "average_score": round(sum(scores) / max(len(scores), 1), 1),
        },
        "results": results,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    write_json(json_path, payload)
    markdown_path.write_text(markdown_report(payload), encoding="utf-8")
    append_progress(progress_path, f"[report] json={json_path} markdown={markdown_path}")
    return 0 if payload["summary"]["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
