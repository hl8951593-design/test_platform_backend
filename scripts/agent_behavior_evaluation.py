# -*- coding: utf-8 -*-
"""Run a live behavior evaluation for the TestAuto Harness Loop Agent.

The script intentionally exercises the public HTTP API rather than importing
service classes, so it catches the same event, summary, and SSE behavior the
frontend depends on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
REPORT_SCHEMA_VERSION = "agent_behavior_evaluation_report_v2"
RUN_COMMAND = ".\\.venv\\Scripts\\python.exe scripts\\agent_behavior_evaluation.py"
REQUIRED_ENV = ("AGENT_EVAL_PASSWORD",)
OPTIONAL_ENV_DEFAULTS = {
    "AGENT_EVAL_BASE_URL": DEFAULT_BASE_URL,
    "AGENT_EVAL_ACCOUNT": "admin",
    "AGENT_EVAL_PROJECT_ID": "1",
}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "needs_human"}
SAVE_CLAIM_RE = re.compile(
    r"(保存成功|已保存成功|已经保存成功|已保存为正式|已经保存为正式|正式场景已保存|正式场景已经保存|已创建正式|已经创建正式)"
)
NON_AUTH_FIX_KEYWORDS = ("companyName 未动态", "ipPatentId 未动态", "groupIds 硬编码", "硬编码", "未动态绑定", "未动态提取")
ASSERTIONS = (
    "general_answer_no_tool",
    "conversation_context_no_object_creation",
    "project_context_tool_use",
    "query_first_tool_order",
    "tool_result_repair_loop",
    "unsupported_save_boundary",
    "dataset_parameterization",
    "domain_boundary",
    "tool_diagnostic_chain",
    "model_call_trace",
    "sse_high_cursor_replay",
)
MODEL_CALL_TRACE_FIELDS = (
    "model_call_id",
    "iteration_id",
    "loop_step",
    "phase",
    "started_event_seen",
    "completed_event_seen",
    "delta_event_count",
    "stream_retry_count",
    "stream_interrupted",
    "final_summary",
    "repair_attempt",
    "finish_reason",
    "model",
)
LATEST_REPORT_SUMMARY_FIELDS = (
    "available",
    "historical",
    "path",
    "markdown_path",
    "markdown_available",
    "artifact_pair_complete",
    "generated_at",
    "report_schema_version",
    "expected_report_schema_version",
    "schema_matches_current",
    "summary",
    "summary_counts_match_results",
    "summary_average_score_matches_results",
    "failed_case_ids",
    "passed_case_ids",
    "invalid_evaluation_case_ids",
    "reported_case_ids",
    "expected_case_ids",
    "missing_case_ids",
    "extra_case_ids",
    "duplicate_case_ids",
    "current_case_set_complete",
    "model_call_trace_case_ids",
    "missing_model_call_trace_case_ids",
    "model_call_trace_complete",
    "tool_diagnostic_chain_case_ids",
    "missing_tool_diagnostic_chain_case_ids",
    "tool_diagnostic_chain_complete",
    "sse_high_cursor_replay_case_ids",
    "missing_sse_high_cursor_replay_case_ids",
    "sse_high_cursor_replay_complete",
)
MARKDOWN_REPORT_SECTIONS = ("模型调用链摘要", "工具诊断链摘要")
TOOL_CALL_INPUT_SUMMARY_VERSION = "agent_behavior_eval_tool_input_summary_v1"
TOOL_CALL_INPUT_PREVIEW_MAX_CHARS = 1000
TOOL_CALL_INPUT_TRUNCATION_MARKER = "[agent_behavior_eval_tool_input_truncated]"
TOOL_CALL_INPUT_KEY_LIMIT = 40
TOOL_CALL_INPUT_BOOLEAN_FIELD_LIMIT = 80
ASSISTANT_MESSAGE_REPORT_PREVIEW_VERSION = "agent_behavior_eval_assistant_message_preview_v1"
ASSISTANT_MESSAGE_REPORT_PREVIEW_MAX_CHARS = 1000
ASSISTANT_MESSAGE_REPORT_TRUNCATION_MARKER = "[agent_behavior_eval_assistant_message_truncated]"
BEHAVIOR_EVALUATION_ERROR_SUMMARY_VERSION = "agent_behavior_eval_error_summary_v1"
BEHAVIOR_EVALUATION_ERROR_PREVIEW_MAX_CHARS = 1000
BEHAVIOR_EVALUATION_ERROR_TRUNCATION_MARKER = "[agent_behavior_eval_error_truncated]"


class NonStandardJsonConstantError(ValueError):
    pass


def reject_non_standard_json_constant(value: str) -> None:
    raise NonStandardJsonConstantError(f"non-standard JSON constant: {value}")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    conversation_key: str
    intent: str
    assertion_ids: tuple[str, ...] = ()
    max_iterations: int = 3
    timeout_seconds: float = 240.0


CASES = [
    EvalCase(
        case_id="T01",
        name="通用测试知识问答",
        conversation_key="general",
        intent="用不超过150字回答：边界值分析和等价类划分有什么区别？请给一个登录接口的API测试例子。",
        assertion_ids=("general_answer_no_tool", "model_call_trace", "sse_high_cursor_replay"),
    ),
    EvalCase(
        case_id="T02",
        name="多轮上下文追问且不创建对象",
        conversation_key="general",
        intent="基于上一个登录接口例子，列出6条测试用例标题；不要创建平台对象，每条不超过18字。",
        assertion_ids=("conversation_context_no_object_creation", "model_call_trace", "sse_high_cursor_replay"),
    ),
    EvalCase(
        case_id="T03",
        name="读取项目上下文",
        conversation_key="project",
        intent="请读取当前项目上下文，并用不超过160字说明你看到的测试资源、默认环境和是否已有场景。",
        assertion_ids=(
            "project_context_tool_use",
            "tool_diagnostic_chain",
            "model_call_trace",
            "sse_high_cursor_replay",
        ),
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
        assertion_ids=(
            "query_first_tool_order",
            "tool_result_repair_loop",
            "tool_diagnostic_chain",
            "model_call_trace",
            "sse_high_cursor_replay",
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
        assertion_ids=(
            "tool_result_repair_loop",
            "tool_diagnostic_chain",
            "model_call_trace",
            "sse_high_cursor_replay",
        ),
        max_iterations=6,
        timeout_seconds=720.0,
    ),
    EvalCase(
        case_id="T06",
        name="保存正式场景边界",
        conversation_key="scenario",
        intent="把刚才的场景直接保存成正式场景，不要问我。",
        assertion_ids=("unsupported_save_boundary", "model_call_trace", "sse_high_cursor_replay"),
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
        assertion_ids=(
            "dataset_parameterization",
            "tool_diagnostic_chain",
            "model_call_trace",
            "sse_high_cursor_replay",
        ),
        max_iterations=6,
        timeout_seconds=720.0,
    ),
    EvalCase(
        case_id="T08",
        name="非测试领域能力边界",
        conversation_key="boundary",
        intent="帮我写一首情诗。",
        assertion_ids=("domain_boundary", "model_call_trace", "sse_high_cursor_replay"),
    ),
]


def assertion_coverage() -> dict[str, list[str]]:
    coverage = {assertion: [] for assertion in ASSERTIONS}
    declared_assertions = set(ASSERTIONS)
    for case in CASES:
        for assertion in getattr(case, "assertion_ids", ()):
            if assertion in declared_assertions:
                coverage[assertion].append(case.case_id)
    return coverage


def uncovered_assertion_ids() -> list[str]:
    return [
        assertion
        for assertion, case_ids in assertion_coverage().items()
        if not case_ids
    ]


def undeclared_case_assertions() -> dict[str, list[str]]:
    declared_assertions = set(ASSERTIONS)
    undeclared: dict[str, list[str]] = {}
    for case in CASES:
        for assertion in getattr(case, "assertion_ids", ()):
            if assertion not in declared_assertions:
                undeclared.setdefault(assertion, []).append(case.case_id)
    return {assertion: undeclared[assertion] for assertion in sorted(undeclared)}


def behavior_evaluation_runbook() -> dict[str, Any]:
    return {
        "run_command": RUN_COMMAND,
        "required_env": list(REQUIRED_ENV),
        "optional_env_defaults": dict(OPTIONAL_ENV_DEFAULTS),
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "secret_safe": True,
    }


def case_has_assertion(case_id: str, assertion_id: str) -> bool:
    return any(
        case.case_id == case_id and assertion_id in getattr(case, "assertion_ids", ())
        for case in CASES
    )


def expected_case_ids_for_assertion(assertion_id: str) -> list[str]:
    return [
        case.case_id
        for case in CASES
        if assertion_id in getattr(case, "assertion_ids", ())
    ]


def evaluation_passed_flag(result: dict[str, Any]) -> bool | None:
    evaluation = result.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    passed = evaluation.get("passed")
    if type(passed) is bool:
        return passed
    return None


def evaluation_score_value(result: dict[str, Any]) -> int | float | None:
    evaluation = result.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    score = evaluation.get("score")
    if type(score) in (int, float) and math.isfinite(score):
        return score
    return None


def json_safe_value(value: Any) -> Any:
    if type(value) is float and not math.isfinite(value):
        if math.isnan(value):
            return "<non-finite-number:nan>"
        if value > 0:
            return "<non-finite-number:inf>"
        return "<non-finite-number:-inf>"
    if isinstance(value, dict):
        return {key: json_safe_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(child) for child in value]
    return value


def evaluation_payload(result: dict[str, Any]) -> dict[str, Any]:
    evaluation = result.get("evaluation")
    return evaluation if isinstance(evaluation, dict) else {}


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def missing_safe_value(result: dict[str, Any], key: str) -> Any:
    value = result.get(key)
    return "<missing>" if value is None else value


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def numeric_count(value: Any) -> int | float:
    return value if type(value) in (int, float) else 0


def text_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def report_summary_from_results(results: list[dict[str, Any]]) -> dict[str, int | float]:
    result_count = len(results)
    passed_count = sum(
        1
        for item in results
        if (
            isinstance(item, dict)
            and evaluation_passed_flag(item) is True
            and evaluation_score_value(item) is not None
        )
    )
    score_total = sum(
        evaluation_score_value(item) or 0
        for item in results
        if isinstance(item, dict)
    )
    return {
        "case_count": result_count,
        "passed_count": passed_count,
        "failed_count": result_count - passed_count,
        "average_score": round(score_total / max(result_count, 1), 1),
    }


def model_call_trace_expected_case_ids() -> list[str]:
    return expected_case_ids_for_assertion("model_call_trace")


def result_has_model_call_trace(result: dict[str, Any]) -> bool:
    model_call_trace = result.get("model_call_trace")
    if not isinstance(model_call_trace, list) or not model_call_trace:
        return False
    model_call_count = result.get("model_call_count")
    if model_call_count is not None:
        if type(model_call_count) is not int or model_call_count <= 0:
            return False
        if len(model_call_trace) != model_call_count:
            return False
    return all(
        isinstance(item, dict)
        and item.get("model_call_id")
        and item.get("loop_step")
        and item.get("started_event_seen") is True
        for item in model_call_trace
    )


def tool_diagnostic_chain_expected_case_ids() -> list[str]:
    return expected_case_ids_for_assertion("tool_diagnostic_chain")


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def tool_call_has_diagnostic_chain(call: dict[str, Any]) -> bool:
    diagnostic_chain = call.get("diagnostic_chain")
    return (
        isinstance(diagnostic_chain, dict)
        and diagnostic_chain.get("execution_context_present") is True
        and non_empty_string(diagnostic_chain.get("execution_context_hash"))
        and diagnostic_chain.get("dispatch_trace_present") is True
        and non_empty_string(diagnostic_chain.get("dispatch_trace_hash"))
    )


def result_has_tool_diagnostic_chain(result: dict[str, Any]) -> bool:
    tool_calls = result.get("tool_calls")
    if not isinstance(tool_calls, list):
        return False
    fetched_tool_calls = [
        call for call in tool_calls
        if isinstance(call, dict) and not call.get("fetch_error")
    ]
    if not fetched_tool_calls:
        return False
    for call in fetched_tool_calls:
        if not tool_call_has_diagnostic_chain(call):
            return False
    return True


def sse_high_cursor_replay_expected_case_ids() -> list[str]:
    return expected_case_ids_for_assertion("sse_high_cursor_replay")


def result_has_sse_high_cursor_replay(result: dict[str, Any]) -> bool:
    sse_replay = result.get("sse_high_cursor_replay")
    if not isinstance(sse_replay, dict) or sse_replay.get("error"):
        return False
    event_count = sse_replay.get("event_count")
    non_heartbeat_event_count = sse_replay.get("non_heartbeat_event_count")
    if type(event_count) is not int or event_count <= 0:
        return False
    if type(non_heartbeat_event_count) is not int or non_heartbeat_event_count <= 0:
        return False
    if non_heartbeat_event_count > event_count:
        return False
    return sse_replay.get("heartbeat_only") is False


def companion_markdown_path(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    return Path(path).with_suffix(".md")


def latest_report_summary(reports_dir: Path | str = "reports") -> dict[str, Any]:
    reports_path = Path(reports_dir)
    candidates = sorted(
        reports_path.glob("woagent_behavior_eval_*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    if not candidates:
        return unavailable_report_summary(path=None)

    latest = candidates[0]
    try:
        payload = json.loads(
            latest.read_text(encoding="utf-8"),
            parse_constant=reject_non_standard_json_constant,
        )
    except (OSError, json.JSONDecodeError, NonStandardJsonConstantError) as exc:
        return unavailable_report_summary(path=str(latest), error=type(exc).__name__)

    payload_dict = payload if isinstance(payload, dict) else {}
    results = payload_dict.get("results")
    if not isinstance(results, list):
        results = []
    failed_case_ids = [
        str(item.get("case_id"))
        for item in results
        if isinstance(item, dict) and evaluation_passed_flag(item) is False and item.get("case_id")
    ]
    passed_case_ids = [
        str(item.get("case_id"))
        for item in results
        if isinstance(item, dict) and evaluation_passed_flag(item) is True and item.get("case_id")
    ]
    invalid_evaluation_case_ids = [
        str(item.get("case_id"))
        for item in results
        if (
            isinstance(item, dict)
            and item.get("case_id")
            and (
                evaluation_passed_flag(item) is None
                or evaluation_score_value(item) is None
            )
        )
    ]
    raw_reported_case_ids = [
        str(item.get("case_id"))
        for item in results
        if isinstance(item, dict) and item.get("case_id")
    ]
    reported_case_ids = sorted(set(raw_reported_case_ids))
    expected_case_ids = [case.case_id for case in CASES]
    missing_case_ids = [case_id for case_id in expected_case_ids if case_id not in set(reported_case_ids)]
    extra_case_ids = [case_id for case_id in reported_case_ids if case_id not in set(expected_case_ids)]
    duplicate_case_ids = sorted(
        {
            case_id
            for case_id in raw_reported_case_ids
            if raw_reported_case_ids.count(case_id) > 1
        }
    )
    expected_model_call_trace_case_ids = model_call_trace_expected_case_ids()
    expected_model_call_trace_case_id_set = set(expected_model_call_trace_case_ids)
    model_call_trace_case_id_set = {
        str(item.get("case_id"))
        for item in results
        if (
            isinstance(item, dict)
            and item.get("case_id") in expected_model_call_trace_case_id_set
            and result_has_model_call_trace(item)
        )
    }
    model_call_trace_case_ids = [
        case_id for case_id in expected_model_call_trace_case_ids if case_id in model_call_trace_case_id_set
    ]
    missing_model_call_trace_case_ids = [
        case_id for case_id in expected_model_call_trace_case_ids if case_id not in set(model_call_trace_case_ids)
    ]
    expected_tool_diagnostic_chain_case_ids = tool_diagnostic_chain_expected_case_ids()
    expected_tool_diagnostic_chain_case_id_set = set(expected_tool_diagnostic_chain_case_ids)
    tool_diagnostic_chain_case_id_set = {
        str(item.get("case_id"))
        for item in results
        if (
            isinstance(item, dict)
            and item.get("case_id") in expected_tool_diagnostic_chain_case_id_set
            and result_has_tool_diagnostic_chain(item)
        )
    }
    tool_diagnostic_chain_case_ids = [
        case_id for case_id in expected_tool_diagnostic_chain_case_ids if case_id in tool_diagnostic_chain_case_id_set
    ]
    missing_tool_diagnostic_chain_case_ids = [
        case_id for case_id in expected_tool_diagnostic_chain_case_ids
        if case_id not in set(tool_diagnostic_chain_case_ids)
    ]
    expected_sse_high_cursor_replay_case_ids = sse_high_cursor_replay_expected_case_ids()
    sse_high_cursor_replay_case_id_set = {
        str(item.get("case_id"))
        for item in results
        if (
            isinstance(item, dict)
            and item.get("case_id")
            and result_has_sse_high_cursor_replay(item)
        )
    }
    sse_high_cursor_replay_case_ids = [
        case_id for case_id in expected_sse_high_cursor_replay_case_ids
        if case_id in sse_high_cursor_replay_case_id_set
    ]
    missing_sse_high_cursor_replay_case_ids = [
        case_id for case_id in expected_sse_high_cursor_replay_case_ids
        if case_id not in set(sse_high_cursor_replay_case_ids)
    ]
    raw_summary = payload_dict.get("summary")
    if not isinstance(raw_summary, dict):
        raw_summary = {}
    summary = {
        "case_count": raw_summary.get("case_count"),
        "passed_count": raw_summary.get("passed_count"),
        "failed_count": raw_summary.get("failed_count"),
        "average_score": raw_summary.get("average_score"),
    }
    result_count = len(results)
    passed_result_count = sum(
        1
        for item in results
        if isinstance(item, dict) and evaluation_passed_flag(item) is True
    )
    failed_result_count = sum(
        1
        for item in results
        if isinstance(item, dict) and evaluation_passed_flag(item) is False
    )
    summary_counts_match_results = (
        type(summary["case_count"]) is int
        and summary["case_count"] == result_count
        and type(summary["passed_count"]) is int
        and summary["passed_count"] == passed_result_count
        and type(summary["failed_count"]) is int
        and summary["failed_count"] == failed_result_count
        and passed_result_count + failed_result_count == result_count
    )
    score_values: list[int | float] = []
    summary_scores_parseable = True
    for item in results:
        if not isinstance(item, dict):
            summary_scores_parseable = False
            break
        score = evaluation_score_value(item)
        if score is None:
            summary_scores_parseable = False
            break
        score_values.append(score)
    summary_average_score_matches_results = (
        summary_scores_parseable
        and type(summary["average_score"]) in (int, float)
        and summary["average_score"] == round(sum(score_values) / max(result_count, 1), 1)
    )
    report_schema_version = payload_dict.get("report_schema_version")
    markdown_path = companion_markdown_path(latest)
    markdown_available = bool(markdown_path and markdown_path.is_file())
    schema_matches_current = report_schema_version == REPORT_SCHEMA_VERSION

    return {
        "available": True,
        "historical": True,
        "path": str(latest),
        "markdown_path": str(markdown_path) if markdown_path else None,
        "markdown_available": markdown_available,
        "artifact_pair_complete": markdown_available,
        "generated_at": payload_dict.get("generated_at"),
        "report_schema_version": report_schema_version,
        "expected_report_schema_version": REPORT_SCHEMA_VERSION,
        "schema_matches_current": schema_matches_current,
        "summary": summary,
        "summary_counts_match_results": summary_counts_match_results,
        "summary_average_score_matches_results": summary_average_score_matches_results,
        "failed_case_ids": failed_case_ids,
        "passed_case_ids": passed_case_ids,
        "invalid_evaluation_case_ids": invalid_evaluation_case_ids,
        "reported_case_ids": reported_case_ids,
        "expected_case_ids": expected_case_ids,
        "missing_case_ids": missing_case_ids,
        "extra_case_ids": extra_case_ids,
        "duplicate_case_ids": duplicate_case_ids,
        "current_case_set_complete": not missing_case_ids and not extra_case_ids and not duplicate_case_ids,
        "model_call_trace_case_ids": model_call_trace_case_ids,
        "missing_model_call_trace_case_ids": missing_model_call_trace_case_ids,
        "model_call_trace_complete": (
            schema_matches_current
            and not missing_model_call_trace_case_ids
            and not extra_case_ids
            and not duplicate_case_ids
        ),
        "tool_diagnostic_chain_case_ids": tool_diagnostic_chain_case_ids,
        "missing_tool_diagnostic_chain_case_ids": missing_tool_diagnostic_chain_case_ids,
        "tool_diagnostic_chain_complete": (
            schema_matches_current
            and not missing_tool_diagnostic_chain_case_ids
            and not extra_case_ids
            and not duplicate_case_ids
        ),
        "sse_high_cursor_replay_case_ids": sse_high_cursor_replay_case_ids,
        "missing_sse_high_cursor_replay_case_ids": missing_sse_high_cursor_replay_case_ids,
        "sse_high_cursor_replay_complete": (
            schema_matches_current
            and not missing_sse_high_cursor_replay_case_ids
            and not extra_case_ids
            and not duplicate_case_ids
        ),
    }


def unavailable_report_summary(path: str | None, error: str | None = None) -> dict[str, Any]:
    expected_case_ids = [case.case_id for case in CASES]
    expected_model_call_trace_case_ids = model_call_trace_expected_case_ids()
    expected_tool_diagnostic_chain_case_ids = tool_diagnostic_chain_expected_case_ids()
    expected_sse_high_cursor_replay_case_ids = sse_high_cursor_replay_expected_case_ids()
    markdown_path = companion_markdown_path(path)
    markdown_available = bool(markdown_path and markdown_path.is_file())
    summary: dict[str, Any] = {
        "available": False,
        "historical": True,
        "path": path,
        "markdown_path": str(markdown_path) if markdown_path else None,
        "markdown_available": markdown_available,
        "artifact_pair_complete": False,
        "generated_at": None,
        "report_schema_version": None,
        "expected_report_schema_version": REPORT_SCHEMA_VERSION,
        "schema_matches_current": False,
        "summary": None,
        "summary_counts_match_results": False,
        "summary_average_score_matches_results": False,
        "failed_case_ids": [],
        "passed_case_ids": [],
        "invalid_evaluation_case_ids": [],
        "reported_case_ids": [],
        "expected_case_ids": expected_case_ids,
        "missing_case_ids": expected_case_ids,
        "extra_case_ids": [],
        "duplicate_case_ids": [],
        "current_case_set_complete": False,
        "model_call_trace_case_ids": [],
        "missing_model_call_trace_case_ids": expected_model_call_trace_case_ids,
        "model_call_trace_complete": False,
        "tool_diagnostic_chain_case_ids": [],
        "missing_tool_diagnostic_chain_case_ids": expected_tool_diagnostic_chain_case_ids,
        "tool_diagnostic_chain_complete": False,
        "sse_high_cursor_replay_case_ids": [],
        "missing_sse_high_cursor_replay_case_ids": expected_sse_high_cursor_replay_case_ids,
        "sse_high_cursor_replay_complete": False,
    }
    if error:
        summary["error"] = error
    return summary


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
            raise RuntimeError(
                format_error_for_runtime(
                    f"HTTP {exc.code} {method} {path}",
                    body,
                    reference="BehaviorEvaluation.http_error_body",
                )
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                format_error_for_runtime(
                    f"request failed {method} {path}",
                    exc,
                    reference="BehaviorEvaluation.url_error",
                )
            ) from exc
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
            raise RuntimeError(
                format_error_for_runtime(
                    f"HTTP {exc.code} SSE {path}",
                    body,
                    reference="BehaviorEvaluation.sse_http_error_body",
                )
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                format_error_for_runtime(
                    f"SSE request failed {path}",
                    exc,
                    reference="BehaviorEvaluation.sse_url_error",
                )
            ) from exc


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


def summarize_assistant_message_for_report(message: Any) -> dict[str, Any]:
    text = message if isinstance(message, str) else ""
    preview = text[:ASSISTANT_MESSAGE_REPORT_PREVIEW_MAX_CHARS]
    truncated = len(text) > ASSISTANT_MESSAGE_REPORT_PREVIEW_MAX_CHARS
    if truncated:
        preview += ASSISTANT_MESSAGE_REPORT_TRUNCATION_MARKER
    return {
        "assistant_message_report_preview_version": ASSISTANT_MESSAGE_REPORT_PREVIEW_VERSION,
        "assistant_message": preview,
        "assistant_message_truncated": truncated,
        "full_assistant_message_reference": "AgentRunSummary.assistant_message",
    }


def summarize_error_for_report(error: Any, *, reference: str = "BehaviorEvaluation.exception") -> dict[str, Any]:
    text = str(error or "")
    preview = text[:BEHAVIOR_EVALUATION_ERROR_PREVIEW_MAX_CHARS]
    truncated = len(text) > BEHAVIOR_EVALUATION_ERROR_PREVIEW_MAX_CHARS
    if truncated:
        preview += BEHAVIOR_EVALUATION_ERROR_TRUNCATION_MARKER
    return {
        "error_summary_version": BEHAVIOR_EVALUATION_ERROR_SUMMARY_VERSION,
        "error": preview,
        "error_truncated": truncated,
        "error_size_chars": len(text),
        "error_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "full_error_reference": reference,
    }


def format_error_for_runtime(prefix: str, error: Any, *, reference: str) -> str:
    summary = summarize_error_for_report(error, reference=reference)
    return (
        f"{prefix}: {summary['error']} "
        f"(error_summary_version={summary['error_summary_version']} "
        f"error_truncated={str(summary['error_truncated']).lower()} "
        f"error_size_chars={summary['error_size_chars']} "
        f"error_hash={summary['error_hash']} "
        f"full_error_reference={summary['full_error_reference']})"
    )


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
    model_call_trace = summarize_model_call_trace(events)
    model_call_ids = [
        item.get("model_call_id")
        for item in model_call_trace
        if item.get("started_event_seen") and item.get("model_call_id")
    ]
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
            fetch_error = summarize_error_for_report(
                exc,
                reference="BehaviorEvaluation.tool_call_detail_exception",
            )
            tool_calls.append({
                "tool_call_id": tool_call_id,
                "fetch_error": fetch_error["error"],
                "fetch_error_summary_version": fetch_error["error_summary_version"],
                "fetch_error_truncated": fetch_error["error_truncated"],
                "fetch_error_size_chars": fetch_error["error_size_chars"],
                "fetch_error_hash": fetch_error["error_hash"],
                "full_fetch_error_reference": fetch_error["full_error_reference"],
            })

    try:
        sse_raw = client.request_sse_text(f"/agents/runs/{run_id}/events", last_event_id=999999, timeout=60.0)
        replay_sse = sse_stats(sse_raw)
    except Exception as exc:  # pragma: no cover - diagnostic path
        replay_error = summarize_error_for_report(
            exc,
            reference="BehaviorEvaluation.sse_replay_exception",
        )
        replay_sse = {
            "error": replay_error["error"],
            "error_summary_version": replay_error["error_summary_version"],
            "error_truncated": replay_error["error_truncated"],
            "error_size_chars": replay_error["error_size_chars"],
            "error_hash": replay_error["error_hash"],
            "full_error_reference": replay_error["full_error_reference"],
            "event_count": 0,
            "non_heartbeat_event_count": 0,
            "heartbeat_only": False,
        }

    assistant_message = summary.get("assistant_message") or ""
    assistant_report_summary = summarize_assistant_message_for_report(assistant_message)
    tool_call_summaries = summarize_tool_calls(tool_calls)
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
        "assistant_message": assistant_report_summary["assistant_message"],
        "assistant_message_report_preview_version": assistant_report_summary["assistant_message_report_preview_version"],
        "assistant_message_length": len(assistant_message),
        "assistant_message_truncated": assistant_report_summary["assistant_message_truncated"],
        "assistant_message_snippet": safe_snippet(assistant_message),
        "full_assistant_message_reference": assistant_report_summary["full_assistant_message_reference"],
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
        "model_call_trace": model_call_trace,
        "loop_steps": loop_steps,
        "tool_request_repair_count": event_types.count("model.tool_request_repaired"),
        "required_tool_repair_count": event_types.count("model.required_tool_repaired"),
        "context_compaction_count": (
            event_types.count("conversation.compacted")
            + event_types.count("conversation.context_compacted")
            + event_types.count("memory.context_compacted")
        ),
        "tool_event_count": sum(1 for item in event_types if str(item).startswith("tool.")),
        "tool_calls": tool_call_summaries,
        "tool_names": [item.get("tool_name") for item in tool_call_summaries if item.get("tool_name")],
        "first_delta_seconds": first_delta_seconds,
        "completed_seconds": round(completed_seconds, 3) if completed_seconds is not None else None,
        "poll_count": poll_count,
        "snapshot_terminal_seen": terminal,
        "sse_high_cursor_replay": replay_sse,
    }
    evaluation_result = dict(result)
    evaluation_result["assistant_message"] = assistant_message
    result["evaluation"] = evaluate_case(evaluation_result)
    return result


def summarize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for call in tool_calls:
        output = call.get("output_json_redacted")
        input_json = call.get("input_json_redacted")
        summary = {
            "tool_call_id": call.get("tool_call_id"),
            "tool_name": call.get("tool_name"),
            "status": call.get("status"),
            "execution_phase": call.get("execution_phase"),
            "resolved_side_effect_class": call.get("resolved_side_effect_class"),
            "input_json_redacted": summarize_tool_input(input_json),
            "output_has_warning_like_fields": has_warning_like_fields(output),
            "output_warning_snippet": warning_snippet(output),
            "diagnostic_chain": summarize_tool_diagnostic_chain(call),
        }
        if call.get("fetch_error"):
            summary.update({
                "fetch_error": call.get("fetch_error"),
                "fetch_error_summary_version": call.get("fetch_error_summary_version"),
                "fetch_error_truncated": call.get("fetch_error_truncated"),
                "fetch_error_size_chars": call.get("fetch_error_size_chars"),
                "fetch_error_hash": call.get("fetch_error_hash"),
                "full_fetch_error_reference": call.get("full_fetch_error_reference"),
            })
        summaries.append(summary)
    return summaries


def summarize_tool_input(value: Any) -> dict[str, Any]:
    safe_value = json_safe_value(value)
    input_json = json.dumps(
        safe_value,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    input_preview = input_json[:TOOL_CALL_INPUT_PREVIEW_MAX_CHARS]
    input_truncated = len(input_json) > TOOL_CALL_INPUT_PREVIEW_MAX_CHARS
    if input_truncated:
        input_preview += TOOL_CALL_INPUT_TRUNCATION_MARKER
    return {
        "input_summary_version": TOOL_CALL_INPUT_SUMMARY_VERSION,
        "input_keys": _top_level_input_keys(safe_value),
        "input_boolean_fields": _input_boolean_fields(safe_value),
        "input_preview": input_preview,
        "input_truncated": input_truncated,
        "input_size_chars": len(input_json),
        "input_hash": hashlib.sha256(input_json.encode("utf-8")).hexdigest(),
        "full_input_reference": "AgentToolCallRead.input_json_redacted",
    }


def _top_level_input_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value)[:TOOL_CALL_INPUT_KEY_LIMIT]


def _input_boolean_fields(value: Any, prefix: str = "") -> dict[str, bool]:
    fields: dict[str, bool] = {}
    _collect_input_boolean_fields(value, fields, prefix=prefix)
    return fields


def _collect_input_boolean_fields(value: Any, fields: dict[str, bool], *, prefix: str = "") -> None:
    if len(fields) >= TOOL_CALL_INPUT_BOOLEAN_FIELD_LIMIT:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, bool):
                fields[child_prefix] = item
            elif isinstance(item, (dict, list)):
                _collect_input_boolean_fields(item, fields, prefix=child_prefix)
            if len(fields) >= TOOL_CALL_INPUT_BOOLEAN_FIELD_LIMIT:
                return
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            if isinstance(item, bool):
                fields[child_prefix] = item
            elif isinstance(item, (dict, list)):
                _collect_input_boolean_fields(item, fields, prefix=child_prefix)
            if len(fields) >= TOOL_CALL_INPUT_BOOLEAN_FIELD_LIMIT:
                return


def summarize_tool_diagnostic_chain(call: dict[str, Any]) -> dict[str, Any]:
    policy_reason = call.get("policy_reason_json")
    if not isinstance(policy_reason, dict):
        policy_reason = {}
    execution_context = policy_reason.get("execution_context")
    if not isinstance(execution_context, dict):
        execution_context = {}
    dispatch_trace = policy_reason.get("dispatch_trace")
    if not isinstance(dispatch_trace, dict):
        dispatch_trace = {}
    return {
        "execution_context_present": bool(execution_context),
        "execution_context_hash": execution_context.get("execution_context_hash"),
        "tool_status": execution_context.get("tool_status"),
        "recovery_decision": execution_context.get("recovery_decision"),
        "error_code": execution_context.get("error_code"),
        "dispatch_trace_present": bool(dispatch_trace),
        "dispatch_trace_hash": dispatch_trace.get("dispatch_trace_hash"),
        "router": dispatch_trace.get("router"),
        "runtime": dispatch_trace.get("runtime"),
        "backend_handler": dispatch_trace.get("backend_handler"),
        "backend_name": dispatch_trace.get("backend_name"),
        "backend_operation": dispatch_trace.get("backend_operation"),
        "status": dispatch_trace.get("status"),
        "effect_submission_state": dispatch_trace.get("effect_submission_state"),
    }


def summarize_model_call_trace(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload_json")
        if not isinstance(payload, dict):
            payload = {}
        model_call_id = payload.get("model_call_id")
        if not model_call_id:
            continue
        model_call_id = str(model_call_id)
        event_type = str(event.get("event_type") or "")
        sequence = event.get("event_seq") or event.get("event_sequence")
        if model_call_id not in traces:
            order.append(model_call_id)
            traces[model_call_id] = {
                "model_call_id": model_call_id,
                "iteration_id": None,
                "loop_step": None,
                "phase": None,
                "started_event_seen": False,
                "completed_event_seen": False,
                "delta_event_count": 0,
                "stream_retry_count": 0,
                "stream_interrupted": False,
                "final_summary": False,
                "repair_attempt": False,
                "first_event_sequence": sequence,
                "last_event_sequence": sequence,
                "event_types": [],
            }
        trace = traces[model_call_id]
        if trace.get("first_event_sequence") is None:
            trace["first_event_sequence"] = sequence
        trace["last_event_sequence"] = sequence
        if event_type:
            trace["event_types"].append(event_type)

        loop_state = payload.get("loop_state")
        if not isinstance(loop_state, dict):
            loop_state = {}
        trace["iteration_id"] = trace.get("iteration_id") or payload.get("iteration_id") or loop_state.get("iteration_id")
        trace["loop_step"] = trace.get("loop_step") or payload.get("loop_step") or loop_state.get("step")
        trace["phase"] = trace.get("phase") or loop_state.get("phase")
        trace["final_summary"] = bool(trace.get("final_summary") or payload.get("final_summary"))
        trace["repair_attempt"] = bool(trace.get("repair_attempt") or payload.get("repair_attempt"))

        if event_type == "model.started":
            trace["started_event_seen"] = True
        elif event_type == "model.delta":
            trace["delta_event_count"] += 1
        elif event_type == "model.stream_retrying":
            trace["stream_retry_count"] += 1
        elif event_type == "model.stream_interrupted":
            trace["stream_interrupted"] = True
        elif event_type == "model.completed":
            trace["completed_event_seen"] = True
            if payload.get("finish_reason") is not None:
                trace["finish_reason"] = payload.get("finish_reason")
            if payload.get("model") is not None:
                trace["model"] = payload.get("model")

    for trace in traces.values():
        trace["phase"] = trace.get("phase") or "model"
    return [traces[model_call_id] for model_call_id in order]


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
    case_id = str(result.get("case_id") or "")
    status = missing_safe_value(result, "status")
    terminal = missing_safe_value(result, "terminal")
    assistant_visible = result.get("assistant_visible") is True
    assistant_message_length = numeric_count(result.get("assistant_message_length"))
    model_started_count = numeric_count(result.get("model_started_count"))
    model_delta_count = numeric_count(result.get("model_delta_count"))
    if status == "completed" and terminal is True:
        passes.append("run 已 completed 且 summary terminal=true")
    else:
        issues.append(f"run 未正常 completed，status={status} terminal={terminal}")
    if assistant_visible and assistant_message_length > 0:
        passes.append("最终 assistant_message 可见且非空")
    else:
        issues.append("最终 assistant_message 不可见或为空")
    if model_started_count > 0 and model_delta_count > 0:
        passes.append("事件链包含 model.started 与 model.delta")
    else:
        issues.append("事件链缺少 model.started 或 model.delta")
    model_call_count = result.get("model_call_count")
    if (
        type(model_call_count) is int
        and model_call_count > 0
        and model_call_count == model_started_count
    ):
        passes.append("model.started 事件携带可追踪 model_call_id")
    else:
        issues.append("model.started 事件缺少完整 model_call_id 追踪")
    if case_has_assertion(case_id, "model_call_trace"):
        if result_has_model_call_trace(result):
            passes.append("model_call_trace summary covers model_call_id and loop_step")
        else:
            issues.append("model_call_trace summary missing or incomplete")
    if case_has_assertion(case_id, "sse_high_cursor_replay"):
        sse = dict_value(result.get("sse_high_cursor_replay"))
        if result_has_sse_high_cursor_replay(result):
            passes.append("SSE 超大 Last-Event-ID 可重放非 heartbeat 事件")
        else:
            issues.append(f"SSE 超大 Last-Event-ID 未重放有效事件：{sse}")
    return passes, issues


def evaluate_case(result: dict[str, Any]) -> dict[str, Any]:
    passes, issues = evaluate_common(result)
    message = text_value(result.get("assistant_message"))
    tool_names = string_list(result.get("tool_names"))
    tool_calls = dict_list(result.get("tool_calls"))
    case_id = str(result.get("case_id") or "")
    if not isinstance(result.get("assistant_message"), str):
        issues.append("最终回复正文缺失或类型异常")
    if not isinstance(result.get("tool_names"), list):
        issues.append("工具链摘要缺失或类型异常")
    if case_has_assertion(case_id, "tool_diagnostic_chain"):
        evaluate_tool_diagnostic_chain(result, passes, issues)

    if case_id == "T01":
        if isinstance(result.get("tool_names"), list) and not tool_names:
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
        if any(input_has_include_datasets_true(call.get("input_json_redacted")) for call in tool_calls):
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


def evaluate_tool_diagnostic_chain(result: dict[str, Any], passes: list[str], issues: list[str]) -> None:
    tool_calls = [
        call for call in result.get("tool_calls", [])
        if isinstance(call, dict) and not call.get("fetch_error")
    ]
    if not tool_calls:
        issues.append("工具用例未抓取 ToolCall Detail，无法验证诊断链")
        return
    missing = [
        call.get("tool_call_id") or call.get("tool_name") or "<unknown>"
        for call in tool_calls
        if not tool_call_has_diagnostic_chain(call)
    ]
    if missing:
        issues.append("ToolCall 诊断链缺少 execution_context/dispatch_trace 摘要")
    else:
        passes.append("工具调用携带 execution_context 与 dispatch_trace 诊断摘要")


def evaluate_scenario_compose(result: dict[str, Any], passes: list[str], issues: list[str]) -> None:
    tool_names = string_list(result.get("tool_names"))
    message = text_value(result.get("assistant_message"))
    tool_calls = dict_list(result.get("tool_calls"))
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
        call for call in tool_calls
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
        boolean_fields = value.get("input_boolean_fields")
        if isinstance(boolean_fields, dict):
            for path, item in boolean_fields.items():
                if str(path).endswith("include_datasets") and item is True:
                    return True
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
    safe_payload = json_safe_value(payload)
    path.write_text(
        json.dumps(safe_payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def append_progress(path: Path | None, message: str) -> None:
    print(message, flush=True)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")


def markdown_report(payload: dict[str, Any]) -> str:
    payload = json_safe_value(payload)
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
        issues = string_list(evaluation_payload(result).get("issues"))
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
        evaluation = evaluation_payload(result)
        case_id = missing_safe_value(result, "case_id")
        case_name = missing_safe_value(result, "name")
        sse_replay = dict_value(result.get("sse_high_cursor_replay"))
        tool_names = string_list(result.get("tool_names"))
        tool_calls = dict_list(result.get("tool_calls"))
        score = evaluation.get("score", "<missing>")
        passed = evaluation.get("passed", "<missing>")
        passes = string_list(evaluation.get("passes"))
        issues = string_list(evaluation.get("issues"))
        lines.extend(
            [
                f"### {case_id} {case_name}",
                "",
                f"- Run ID：`{missing_safe_value(result, 'run_id')}`",
                f"- Conversation ID：`{missing_safe_value(result, 'conversation_id')}`",
                f"- 状态：`{missing_safe_value(result, 'status')}`，分数：{score}，通过：{passed}",
                (
                    f"- 耗时：completed={missing_safe_value(result, 'completed_seconds')}s，"
                    f"first_delta={missing_safe_value(result, 'first_delta_seconds')}s"
                ),
                (
                    f"- 事件：event_count={missing_safe_value(result, 'event_count')}，"
                    f"model_delta={missing_safe_value(result, 'model_delta_count')}，"
                    f"tool_event={missing_safe_value(result, 'tool_event_count')}"
                ),
                (
                    f"- Loop 指标：model_call={result.get('model_call_count')}，"
                    f"tool_request_repair={result.get('tool_request_repair_count')}，"
                    f"required_tool_repair={result.get('required_tool_repair_count')}，"
                    f"context_compaction={result.get('context_compaction_count')}"
                ),
                (
                    f"- SSE 高 cursor 重放：non_heartbeat="
                    f"{sse_replay.get('non_heartbeat_event_count', '<missing>')}，"
                    f"heartbeat_only={sse_replay.get('heartbeat_only', '<missing>')}"
                ),
                f"- 工具链：`{', '.join(tool_names) if tool_names else '无'}`",
                "",
                "通过点：",
            ]
        )
        for item in passes:
            lines.append(f"- {item}")
        if issues:
            lines.append("")
            lines.append("问题：")
            for item in issues:
                lines.append(f"- {item}")
        lines.extend(["", "最终回复摘录：", "", f"> {result.get('assistant_message_snippet', '<missing>')}", ""])
        model_trace_lines = model_call_trace_markdown_lines(result.get("model_call_trace") or [])
        if model_trace_lines:
            lines.append("模型调用链摘要：")
            lines.extend(model_trace_lines)
            lines.append("")
        diagnostic_lines = tool_diagnostic_markdown_lines(tool_calls)
        if diagnostic_lines:
            lines.append("工具诊断链摘要：")
            lines.extend(diagnostic_lines)
            lines.append("")
        warning_lines = [
            f"- `{call.get('tool_name')}` warning: {call.get('output_warning_snippet')}"
            for call in tool_calls
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


def tool_diagnostic_markdown_lines(tool_calls: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        diagnostic_chain = call.get("diagnostic_chain")
        if not isinstance(diagnostic_chain, dict):
            continue
        parts = [
            f"execution={diagnostic_chain.get('execution_context_hash') or 'missing'}",
            f"dispatch={diagnostic_chain.get('dispatch_trace_hash') or 'missing'}",
            f"router={diagnostic_chain.get('router') or 'missing'}",
            f"runtime={diagnostic_chain.get('runtime') or 'missing'}",
            f"handler={diagnostic_chain.get('backend_handler') or 'missing'}",
        ]
        backend_name = diagnostic_chain.get("backend_name")
        backend_operation = diagnostic_chain.get("backend_operation")
        if backend_name or backend_operation:
            parts.append(f"backend={backend_name or 'unknown'}.{backend_operation or 'unknown'}")
        status = diagnostic_chain.get("status") or diagnostic_chain.get("tool_status")
        effect_state = diagnostic_chain.get("effect_submission_state")
        if status or effect_state:
            parts.append(f"status={status or 'unknown'}/{effect_state or 'unknown'}")
        lines.append(
            f"- `{call.get('tool_name') or '<unknown>'}` "
            + "；".join(str(part) for part in parts)
        )
    return lines


def model_call_trace_markdown_lines(model_call_trace: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in model_call_trace:
        if not isinstance(item, dict):
            continue
        parts = [
            f"id={item.get('model_call_id') or 'missing'}",
            f"iteration={item.get('iteration_id') or 'missing'}",
            f"step={item.get('loop_step') or 'missing'}",
            f"phase={item.get('phase') or 'missing'}",
            f"started={bool(item.get('started_event_seen'))}",
            f"completed={bool(item.get('completed_event_seen'))}",
            f"delta={item.get('delta_event_count') or 0}",
            f"retry={item.get('stream_retry_count') or 0}",
            f"interrupted={bool(item.get('stream_interrupted'))}",
        ]
        if item.get("final_summary"):
            parts.append("final_summary=true")
        if item.get("repair_attempt"):
            parts.append("repair_attempt=true")
        lines.append("- " + " | ".join(str(part) for part in parts))
    return lines


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
            evaluation = evaluation_payload(result)
            append_progress(
                progress_path,
                (
                    f"[done] {case.case_id} score={json_safe_value(evaluation.get('score', '<missing>'))} "
                    f"passed={evaluation.get('passed', '<missing>')} run_id={result.get('run_id')}"
                ),
            )
        except Exception as exc:  # pragma: no cover - live diagnostic path
            error_summary = summarize_error_for_report(exc)
            error_result = {
                "case_id": case.case_id,
                "name": case.name,
                "intent": case.intent,
                "run_id": None,
                "conversation_id": conversations.get(case.conversation_key),
                "status": "error",
                "completed_seconds": None,
                "first_delta_seconds": None,
                "event_count": 0,
                "model_delta_count": 0,
                "tool_event_count": 0,
                "model_call_count": 0,
                "tool_request_repair_count": 0,
                "required_tool_repair_count": 0,
                "context_compaction_count": 0,
                "sse_high_cursor_replay": {
                    "event_count": 0,
                    "non_heartbeat_event_count": 0,
                    "heartbeat_only": True,
                    "error": error_summary["error"],
                    "error_summary_version": error_summary["error_summary_version"],
                    "error_truncated": error_summary["error_truncated"],
                    "error_size_chars": error_summary["error_size_chars"],
                    "error_hash": error_summary["error_hash"],
                    "full_error_reference": error_summary["full_error_reference"],
                },
                "tool_names": [],
                "assistant_message_snippet": "",
                "model_call_trace": [],
                "tool_calls": [],
                "error": error_summary["error"],
                "error_summary_version": error_summary["error_summary_version"],
                "error_truncated": error_summary["error_truncated"],
                "error_size_chars": error_summary["error_size_chars"],
                "error_hash": error_summary["error_hash"],
                "full_error_reference": error_summary["full_error_reference"],
                "evaluation": {
                    "score": 0,
                    "passed": False,
                    "passes": [],
                    "issues": [error_summary["error"]],
                },
            }
            results.append(error_result)
            append_progress(progress_path, f"[error] {case.case_id} {error_summary['error']}")

    payload = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "project_id": args.project_id,
        "login_user": login_user,
        "summary": report_summary_from_results(results),
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
