import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.ai_skills.base import AISkill, SkillPackage, load_model_json
from app.ai_skills.registry import register_ai_skill
from app.schemas.ai import AIChatMessage, AIChatRequest, AIGeneratedScenarioResponse
from app.schemas.scenario import ScenarioActionRequest, ScenarioCreateRequest


class ScenarioComposerSkill(AISkill):
    skill_id = "scenario-composer"

    def __init__(self):
        self.package = SkillPackage(Path(__file__).parent / "packages" / self.skill_id)
        self.name = self.package.metadata.name
        self.description = self.package.metadata.description

    def build_chat_request(self, context: dict[str, Any]) -> AIChatRequest:
        payload = context["payload"]
        user_context = {
            "project_id": context["project_id"],
            "environment": context["environment"],
            "requirement": payload.requirement,
            "scenario_name": payload.scenario_name,
            "include_bindings": payload.include_bindings,
            "include_assertions": payload.include_assertions,
            "include_hooks": payload.include_hooks,
            "include_datasets": payload.include_datasets,
            "include_latest_execution": payload.include_latest_execution,
            "execute_candidates": payload.execute_candidates,
            "max_nodes": payload.max_nodes,
            "extra_requirements": payload.extra_requirements,
            "candidate_cases": context["candidate_cases"],
        }
        if context.get("previous_scenario") is not None:
            user_context["previous_scenario"] = context["previous_scenario"]
        if context.get("validation_feedback") is not None:
            user_context["validation_feedback"] = context["validation_feedback"]
        return AIChatRequest(
            messages=[
                AIChatMessage(role="system", content=self.package.read_text("prompts/compose_system.md")),
                AIChatMessage(
                    role="user",
                    content=(
                        "请根据以下上下文组合测试场景草稿。必须输出 JSON，且 reference_id 只能来自 candidate_cases。"
                        "如果包含 previous_scenario 和 validation_feedback，请优先修复执行失败原因，并尽量保持已通过部分稳定。\n"
                        + json.dumps(user_context, ensure_ascii=False, indent=2)
                    ),
                ),
            ],
            thinking="disabled",
            temperature=0.2,
            max_tokens=7000,
            response_format="json",
        )

    def parse_response(self, raw_content: str, context: dict[str, Any]) -> AIGeneratedScenarioResponse:
        try:
            data = self._loads_json(raw_content)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 返回结果不是合法 JSON: {exc}",
            ) from exc

        warnings = self._as_string_list(data.get("warnings"))
        scenario_data = data.get("scenario") if isinstance(data.get("scenario"), dict) else data
        if not isinstance(scenario_data, dict):
            scenario_data = {}
            warnings.append("AI 未返回 scenario 对象")

        normalized = self._normalize_scenario(scenario_data, context, warnings)
        try:
            scenario = ScenarioCreateRequest.model_validate(normalized)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 返回场景结构校验失败: {exc.errors()}",
            ) from exc

        return AIGeneratedScenarioResponse(
            project_id=context["project_id"],
            environment_id=context["environment_id"],
            environment_name=self._environment_name(context),
            source_summary=str(data.get("source_summary") or data.get("summary") or ""),
            scenario=scenario,
            warnings=warnings,
        )

    def _environment_name(self, context: dict[str, Any]) -> str | None:
        environment = context.get("environment")
        if isinstance(environment, dict):
            name = environment.get("name")
            return str(name) if name is not None else None
        name = getattr(environment, "name", None)
        return str(name) if name is not None else None

    def _normalize_scenario(
        self,
        scenario_data: dict[str, Any],
        context: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        payload = context["payload"]
        allowed = context["candidate_index"]
        nodes: list[dict[str, Any]] = []
        raw_nodes = scenario_data.get("nodes")
        if not isinstance(raw_nodes, list):
            raw_nodes = []
            warnings.append("AI 未返回 nodes 数组")

        available_variables = self._dataset_variable_names(scenario_data)
        for index, raw_node in enumerate(raw_nodes[: payload.max_nodes], start=1):
            if not isinstance(raw_node, dict):
                warnings.append(f"第 {index} 个节点不是对象，已忽略")
                continue
            raw_test_case = raw_node.get("test_case") or raw_node.get("testCase") or raw_node
            if not isinstance(raw_test_case, dict):
                warnings.append(f"第 {index} 个节点缺少 test_case，已忽略")
                continue
            kind = str(raw_test_case.get("kind") or "")
            reference_id = self._to_int(raw_test_case.get("reference_id", raw_test_case.get("referenceId")))
            candidate = allowed.get((kind, reference_id))
            if candidate is None:
                warnings.append(f"第 {index} 个节点引用了非候选用例，已忽略: kind={kind}, reference_id={reference_id}")
                continue

            step_id = str(raw_test_case.get("id") or raw_node.get("id") or f"CASE-{index}")[:128]
            node_id = str(raw_node.get("id") or f"NODE-{index}")[:128]
            if node_id == step_id:
                node_id = f"NODE-{index}"
            step_label = str(raw_node.get("name") or candidate["name"])
            before_actions = (
                self._actions(
                    raw_node.get("before_actions", raw_node.get("beforeActions")),
                    warnings,
                    scope=f"{step_label} before_actions",
                )
                if payload.include_hooks
                else []
            )
            available_before_step = {*available_variables, *self._action_outputs(before_actions)}
            config = self._step_config(
                raw_test_case,
                payload,
                candidate,
                warnings,
                available_variables=available_before_step,
                step_label=step_label,
            )
            after_actions = (
                self._actions(
                    raw_node.get("after_actions", raw_node.get("afterActions")),
                    warnings,
                    scope=f"{step_label} after_actions",
                )
                if payload.include_hooks
                else []
            )
            nodes.append({
                "id": node_id,
                "name": step_label[:200],
                "before_actions": before_actions,
                "test_case": {
                    "id": step_id,
                    "kind": kind,
                    "reference_id": reference_id,
                    "name": candidate["name"],
                    "method": candidate["method"],
                    "path": candidate["path"],
                    "config": config,
                    "continue_on_failure": bool(raw_test_case.get("continue_on_failure", raw_test_case.get("continueOnFailure", False))),
                },
                "after_actions": after_actions,
            })
            available_variables.update(self._action_outputs(before_actions))
            available_variables.update(self._config_extraction_names(config))
            available_variables.update(self._action_outputs(after_actions))

        if not nodes:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI 未生成任何可用场景节点",
            )

        datasets = scenario_data.get("datasets") if isinstance(scenario_data.get("datasets"), list) else []
        if not payload.include_datasets:
            datasets = []
        return {
            "name": str(scenario_data.get("name") or payload.scenario_name or "AI 智能组合场景")[:128],
            "description": str(scenario_data.get("description") or payload.requirement),
            "environment_id": context["environment_id"],
            "tags": self._string_list(scenario_data.get("tags")) or ["ai-composed"],
            "nodes": nodes,
            "datasets": datasets,
        }

    def _actions(self, value: Any, warnings: list[str], *, scope: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        actions: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                warnings.append(f"{scope} 第 {index} 个动作不是对象，已忽略")
                continue
            normalized = self._normalize_action(item, warnings, scope=scope, index=index)
            if normalized is not None:
                actions.append(normalized)
        return actions

    def _normalize_action(
        self,
        raw_action: dict[str, Any],
        warnings: list[str],
        *,
        scope: str,
        index: int,
    ) -> dict[str, Any] | None:
        action = dict(raw_action)
        config = action.get("config") if isinstance(action.get("config"), dict) else {}
        config = dict(config)
        kind = str(action.get("kind") or action.get("type") or "").strip()
        if not kind:
            kind = self._infer_action_kind(action, config)
            if kind:
                warnings.append(f"{scope} 第 {index} 个动作缺少 kind，已根据配置推断为 {kind}")
        if not kind:
            warnings.append(f"{scope} 第 {index} 个动作缺少 kind 且无法推断，已忽略")
            return None

        action_id = str(action.get("id") or f"{scope.upper().replace(' ', '-')}-{index}")[:128]
        action_payload = {
            "id": action_id,
            "kind": kind,
            "name": str(action.get("name") or action_id)[:200],
            "config": self._normalize_action_config(action, config, kind),
            "continue_on_failure": bool(action.get("continue_on_failure", action.get("continueOnFailure", False))),
        }
        try:
            return ScenarioActionRequest.model_validate(action_payload).model_dump(mode="json")
        except ValidationError as exc:
            warnings.append(f"{scope} 第 {index} 个动作配置无效，已忽略: {exc.errors()}")
            return None

    def _normalize_action_config(self, action: dict[str, Any], config: dict[str, Any], kind: str) -> dict[str, Any]:
        if kind == "delay":
            if "duration_ms" not in config:
                duration = action.get("duration_ms", action.get("durationMs", action.get("duration")))
                if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                    config["duration_ms"] = int(duration)
            return config
        if kind == "fixed_value":
            if "output" not in config and action.get("output") is not None:
                config["output"] = action["output"]
            if "value" not in config and "value" in action:
                config["value"] = action["value"]
            return config
        if kind == "random":
            for key in ("output", "type", "min", "max", "length"):
                if key not in config and key in action:
                    config[key] = action[key]
            return config
        if kind == "condition":
            if "expression" not in config and action.get("expression") is not None:
                config["expression"] = action["expression"]
            return config
        if kind == "script":
            for key in ("language", "code", "inputs", "outputs", "timeout_ms"):
                if key not in config and key in action:
                    config[key] = action[key]
            if "timeout_ms" not in config and action.get("timeoutMs") is not None:
                config["timeout_ms"] = action["timeoutMs"]
            return config
        return config

    @staticmethod
    def _infer_action_kind(action: dict[str, Any], config: dict[str, Any]) -> str:
        if "expression" in config or "expression" in action:
            return "condition"
        if any(key in config or key in action for key in ("duration_ms", "durationMs", "duration")):
            return "delay"
        if ("output" in config or "output" in action) and ("value" in config or "value" in action):
            return "fixed_value"
        random_type = config.get("type", action.get("type"))
        if random_type in {"integer", "string", "uuid"} and ("output" in config or "output" in action):
            return "random"
        if "code" in config or "code" in action:
            return "script"
        return ""

    def _step_config(
        self,
        raw_test_case: dict[str, Any],
        payload: Any,
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        available_variables: set[str],
        step_label: str,
    ) -> dict[str, Any]:
        config = raw_test_case.get("config") if isinstance(raw_test_case.get("config"), dict) else {}
        config = dict(config)
        self._replace_unbound_templates(config, candidate, available_variables, warnings, step_label=step_label)
        if payload.include_assertions:
            raw_assertions = raw_test_case.get("assertions")
            if not isinstance(raw_assertions, list) and isinstance(config.get("assertions"), list):
                raw_assertions = config.get("assertions")
            if not isinstance(raw_assertions, list) and isinstance(candidate.get("assertions"), list):
                raw_assertions = candidate.get("assertions")
            assertions = self._normalize_assertions(raw_assertions, candidate, warnings, step_label=step_label)
            if assertions:
                config["assertions"] = assertions
            else:
                config.pop("assertions", None)
        else:
            config.pop("assertions", None)
        raw_extractors = raw_test_case.get("extractors")
        if not isinstance(raw_extractors, list) and isinstance(config.get("extractors"), list):
            raw_extractors = config.get("extractors")
        if not isinstance(raw_extractors, list):
            scenario_context = config.get("_scenario_context")
            if isinstance(scenario_context, dict):
                raw_extractors = self._context_items(scenario_context, "extractions", "extractors")
        if not isinstance(raw_extractors, list) and isinstance(candidate.get("extractors"), list):
            raw_extractors = candidate.get("extractors")
        extractors = self._normalize_extractors(raw_extractors, candidate, warnings, step_label=step_label)
        if extractors:
            config["extractors"] = extractors
            scenario_context = config.get("_scenario_context")
            if not isinstance(scenario_context, dict):
                scenario_context = {}
                config["_scenario_context"] = scenario_context
            scenario_context["extractions"] = extractors
        else:
            config.pop("extractors", None)
            scenario_context = config.get("_scenario_context")
            if isinstance(scenario_context, dict):
                scenario_context.pop("extractions", None)
        if payload.include_bindings and isinstance(raw_test_case.get("bindings"), list):
            scenario_context = config.get("_scenario_context")
            if not isinstance(scenario_context, dict):
                scenario_context = {}
                config["_scenario_context"] = scenario_context
            scenario_context["bindings"] = raw_test_case["bindings"]
        return config

    def _replace_unbound_templates(
        self,
        config: dict[str, Any],
        candidate: dict[str, Any],
        available_variables: set[str],
        warnings: list[str],
        *,
        step_label: str,
    ) -> None:
        for root in ("path", "headers", "query_params", "body", "messages", "subprotocols"):
            if root not in config:
                continue
            config[root] = self._replace_unbound_template_value(
                config[root],
                candidate,
                available_variables,
                warnings,
                root=root,
                path=[],
                step_label=step_label,
            )

    def _replace_unbound_template_value(
        self,
        value: Any,
        candidate: dict[str, Any],
        available_variables: set[str],
        warnings: list[str],
        *,
        root: str,
        path: list[str],
        step_label: str,
    ) -> Any:
        if isinstance(value, str):
            names = [match.group(1).strip() for match in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", value)]
            unknown_names = [name for name in names if name not in available_variables]
            if not unknown_names:
                return value
            found, replacement = self._resolve_trace_path(candidate.get(root), ".".join(path))
            if found:
                warnings.append(
                    f"{step_label} 的 {root}.{'.'.join(path)} 引用了未定义变量 "
                    f"{', '.join(unknown_names)}，已回填候选用例真实值"
                )
                return replacement
            warnings.append(
                f"{step_label} 的 {root}.{'.'.join(path)} 引用了未定义变量 "
                f"{', '.join(unknown_names)}，且候选用例无可回填值"
            )
            return value
        if isinstance(value, dict):
            return {
                key: self._replace_unbound_template_value(
                    item,
                    candidate,
                    available_variables,
                    warnings,
                    root=root,
                    path=[*path, str(key)],
                    step_label=step_label,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._replace_unbound_template_value(
                    item,
                    candidate,
                    available_variables,
                    warnings,
                    root=root,
                    path=[*path, str(index)],
                    step_label=step_label,
                )
                for index, item in enumerate(value)
            ]
        return value

    def _normalize_extractors(
        self,
        raw_extractors: Any,
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        step_label: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_extractors, list):
            return []
        if candidate.get("kind") == "websocket_case":
            return self._normalize_websocket_extractors(raw_extractors, candidate, warnings, step_label=step_label)
        return self._normalize_http_extractors(raw_extractors, candidate, warnings, step_label=step_label)

    def _normalize_http_extractors(
        self,
        raw_extractors: list[Any],
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        step_label: str,
    ) -> list[dict[str, Any]]:
        response = self._candidate_response_snapshot(candidate)
        json_body = response.get("json") if response else None
        result: list[dict[str, Any]] = []
        for index, extractor in enumerate(raw_extractors, start=1):
            if not isinstance(extractor, dict):
                warnings.append(f"{step_label} 第 {index} 个提取器不是对象，已忽略")
                continue
            item = dict(extractor)
            name = str(item.get("name") or "").strip()
            path = str(item.get("path") or "").strip()
            if not name:
                warnings.append(f"{step_label} 第 {index} 个提取器缺少 name，已忽略")
                continue
            if not path:
                path = self._find_json_key_path(json_body, name) or ""
            elif json_body is not None:
                found, _ = self._resolve_trace_path(json_body, path)
                if not found:
                    repaired_path = self._find_json_key_path(json_body, name)
                    if repaired_path:
                        warnings.append(f"{step_label} 提取器 {name} 的路径 {path} 不存在，已修正为 {repaired_path}")
                        path = repaired_path
            if not path:
                warnings.append(f"{step_label} 提取器 {name} 无法从响应样本推断路径，已忽略")
                continue
            item["name"] = name
            item["path"] = path
            result.append(item)
        return result

    def _normalize_websocket_extractors(
        self,
        raw_extractors: list[Any],
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        step_label: str,
    ) -> list[dict[str, Any]]:
        response = self._candidate_response_snapshot(candidate)
        messages = response.get("received_messages") if response else None
        if not isinstance(messages, list):
            messages = []
        result: list[dict[str, Any]] = []
        for index, extractor in enumerate(raw_extractors, start=1):
            if not isinstance(extractor, dict):
                warnings.append(f"{step_label} 第 {index} 个提取器不是对象，已忽略")
                continue
            item = dict(extractor)
            name = str(item.get("name") or "").strip()
            path = str(item.get("path") or "").strip()
            message_index = self._to_int(item.get("message_index"))
            if message_index is None or message_index < 0:
                message_index = 0
            if not name:
                warnings.append(f"{step_label} 第 {index} 个 WebSocket 提取器缺少 name，已忽略")
                continue
            if messages:
                selected = messages[message_index].get("json") if message_index < len(messages) else None
                if not path:
                    found_pair = self._find_message_json_key_path(messages, name)
                    if found_pair:
                        message_index, path = found_pair
                elif selected is not None:
                    found, _ = self._resolve_trace_path(selected, path)
                    if not found:
                        found_pair = self._find_message_json_key_path(messages, name)
                        if found_pair:
                            message_index, repaired_path = found_pair
                            warnings.append(f"{step_label} WebSocket 提取器 {name} 的路径 {path} 不存在，已修正为消息 {message_index} 的 {repaired_path}")
                            path = repaired_path
            if not path:
                warnings.append(f"{step_label} WebSocket 提取器 {name} 无法从响应样本推断路径，已忽略")
                continue
            item["name"] = name
            item["message_index"] = message_index
            item["path"] = path
            result.append(item)
        return result

    def _dataset_variable_names(self, scenario_data: dict[str, Any]) -> set[str]:
        names: set[str] = set()
        datasets = scenario_data.get("datasets")
        if not isinstance(datasets, list):
            return names
        for dataset in datasets:
            if not isinstance(dataset, dict):
                continue
            variables = dataset.get("variables")
            if isinstance(variables, dict):
                names.update(str(key) for key in variables)
            for record in dataset.get("records") or []:
                if isinstance(record, dict) and isinstance(record.get("variables"), dict):
                    names.update(str(key) for key in record["variables"])
        return names

    def _action_outputs(self, actions: list[dict[str, Any]]) -> set[str]:
        outputs: set[str] = set()
        for action in actions:
            config = action.get("config")
            if not isinstance(config, dict):
                continue
            output = config.get("output")
            if output:
                outputs.add(str(output))
            raw_outputs = config.get("outputs")
            if isinstance(raw_outputs, list):
                outputs.update(str(item) for item in raw_outputs if str(item).strip())
        return outputs

    def _config_extraction_names(self, config: dict[str, Any]) -> set[str]:
        names: set[str] = set()
        for extraction in config.get("extractors") or []:
            if isinstance(extraction, dict) and extraction.get("name"):
                names.add(str(extraction["name"]))
        context = config.get("_scenario_context")
        if isinstance(context, dict):
            for extraction in self._context_items(context, "extractions", "extractors"):
                if extraction.get("name"):
                    names.add(str(extraction["name"]))
        return names

    def _resolve_trace_path(self, data: Any, path: str) -> tuple[bool, Any]:
        if path == "":
            return True, data
        current = data
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return False, None
        return True, current

    def _find_json_key_path(self, data: Any, target_name: str) -> str | None:
        target = self._normalize_variable_name(target_name)
        fallback: str | None = None

        def walk(value: Any, parts: list[str]) -> str | None:
            nonlocal fallback
            if isinstance(value, dict):
                for key, item in value.items():
                    current_path = ".".join([*parts, str(key)])
                    if key == target_name:
                        return current_path
                    if fallback is None and self._normalize_variable_name(str(key)) == target:
                        fallback = current_path
                    found = walk(item, [*parts, str(key)])
                    if found:
                        return found
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    found = walk(item, [*parts, str(index)])
                    if found:
                        return found
            return None

        return walk(data, []) or fallback

    def _find_message_json_key_path(self, messages: list[Any], target_name: str) -> tuple[int, str] | None:
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            path = self._find_json_key_path(message.get("json"), target_name)
            if path:
                return index, path
        return None

    @staticmethod
    def _normalize_variable_name(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    @staticmethod
    def _context_items(context: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        for key in keys:
            value = context.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _normalize_assertions(
        self,
        raw_assertions: Any,
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        step_label: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_assertions, list):
            return []
        if candidate.get("kind") == "websocket_case":
            return self._normalize_websocket_assertions(raw_assertions, candidate, warnings, step_label=step_label)
        return self._normalize_http_assertions(raw_assertions, candidate, warnings, step_label=step_label)

    def _normalize_http_assertions(
        self,
        raw_assertions: list[Any],
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        step_label: str,
    ) -> list[dict[str, Any]]:
        response = self._candidate_response_snapshot(candidate)
        result: list[dict[str, Any]] = []
        for index, assertion in enumerate(raw_assertions, start=1):
            if not isinstance(assertion, dict):
                warnings.append(f"{step_label} 第 {index} 条断言不是对象，已忽略")
                continue
            item = dict(assertion)
            assertion_type = str(item.get("type") or "").strip()
            if assertion_type not in {"status_code", "body_contains", "json_equals"}:
                warnings.append(f"{step_label} 第 {index} 条 HTTP 断言类型不支持，已忽略: {assertion_type}")
                continue

            if assertion_type == "status_code":
                expected = item.get("expected")
                if self._is_missing_expected(expected):
                    expected = self._find_candidate_assertion_expected(candidate, "status_code")
                if self._is_missing_expected(expected) and response:
                    expected = response.get("status_code")
                if self._is_missing_expected(expected):
                    expected = 200
                item["expected"] = self._as_int_if_possible(expected)
                result.append(item)
                continue

            if assertion_type == "body_contains":
                expected = item.get("expected")
                if self._is_missing_expected(expected):
                    expected = self._find_candidate_assertion_expected(candidate, "body_contains")
                if self._is_missing_expected(expected):
                    warnings.append(f"{step_label} 第 {index} 条 body_contains 缺少 expected，已忽略")
                    continue
                item["expected"] = expected
                result.append(item)
                continue

            path = str(item.get("path") or "").strip()
            if not path:
                warnings.append(f"{step_label} 第 {index} 条 json_equals 缺少 path，已忽略")
                continue
            expected = item.get("expected")
            if self._is_missing_expected(expected):
                expected = self._find_candidate_assertion_expected(candidate, "json_equals", path=path)
            if self._is_missing_expected(expected) and response:
                expected = self._get_json_path(response.get("json"), path)
            if self._is_missing_expected(expected):
                warnings.append(f"{step_label} 第 {index} 条 json_equals 缺少 expected 且无法从响应样本推断，已忽略")
                continue
            item["path"] = path
            item["expected"] = expected
            result.append(item)
        return result

    def _normalize_websocket_assertions(
        self,
        raw_assertions: list[Any],
        candidate: dict[str, Any],
        warnings: list[str],
        *,
        step_label: str,
    ) -> list[dict[str, Any]]:
        response = self._candidate_response_snapshot(candidate)
        messages = response.get("received_messages") if response else None
        if not isinstance(messages, list):
            messages = []
        result: list[dict[str, Any]] = []
        for index, assertion in enumerate(raw_assertions, start=1):
            if not isinstance(assertion, dict):
                warnings.append(f"{step_label} 第 {index} 条断言不是对象，已忽略")
                continue
            item = dict(assertion)
            assertion_type = str(item.get("type") or "").strip()
            if assertion_type not in {"message_count", "message_contains", "message_json_equals"}:
                warnings.append(f"{step_label} 第 {index} 条 WebSocket 断言类型不支持，已忽略: {assertion_type}")
                continue

            if assertion_type == "message_count":
                expected = item.get("expected")
                if self._is_missing_expected(expected):
                    expected = self._find_candidate_assertion_expected(candidate, "message_count")
                if self._is_missing_expected(expected):
                    expected = len(messages) if messages else candidate.get("receive_count")
                if self._is_missing_expected(expected):
                    warnings.append(f"{step_label} 第 {index} 条 message_count 缺少 expected，已忽略")
                    continue
                item["expected"] = self._as_int_if_possible(expected)
                result.append(item)
                continue

            message_index = self._to_int(item.get("message_index"))
            if message_index is None or message_index < 0:
                message_index = 0
            item["message_index"] = message_index

            if assertion_type == "message_contains":
                expected = item.get("expected")
                if self._is_missing_expected(expected):
                    expected = self._find_candidate_assertion_expected(
                        candidate,
                        "message_contains",
                        message_index=message_index,
                    )
                if self._is_missing_expected(expected):
                    warnings.append(f"{step_label} 第 {index} 条 message_contains 缺少 expected，已忽略")
                    continue
                item["expected"] = expected
                result.append(item)
                continue

            path = str(item.get("path") or "").strip()
            if not path:
                warnings.append(f"{step_label} 第 {index} 条 message_json_equals 缺少 path，已忽略")
                continue
            expected = item.get("expected")
            if self._is_missing_expected(expected):
                expected = self._find_candidate_assertion_expected(
                    candidate,
                    "message_json_equals",
                    message_index=message_index,
                    path=path,
                )
            if self._is_missing_expected(expected) and message_index < len(messages):
                expected = self._get_json_path(messages[message_index].get("json"), path)
            if self._is_missing_expected(expected):
                warnings.append(f"{step_label} 第 {index} 条 message_json_equals 缺少 expected 且无法从响应样本推断，已忽略")
                continue
            item["path"] = path
            item["expected"] = expected
            result.append(item)
        return result

    def _candidate_response_snapshot(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        execution_sample = candidate.get("execution_sample")
        if not isinstance(execution_sample, dict):
            return None
        response = execution_sample.get("response_snapshot")
        return response if isinstance(response, dict) else None

    def _find_candidate_assertion_expected(
        self,
        candidate: dict[str, Any],
        assertion_type: str,
        *,
        path: str | None = None,
        message_index: int | None = None,
    ) -> Any:
        for assertion in candidate.get("assertions") or []:
            if not isinstance(assertion, dict) or assertion.get("type") != assertion_type:
                continue
            if path is not None and str(assertion.get("path") or "") != path:
                continue
            if message_index is not None and self._to_int(assertion.get("message_index", 0)) != message_index:
                continue
            return assertion.get("expected")
        return None

    def _get_json_path(self, data: Any, path: str | None) -> Any:
        if path is None or path == "":
            return data
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)] if int(part) < len(current) else None
            else:
                return None
        return current

    def _is_missing_expected(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and value.strip() == "")

    def _as_int_if_possible(self, value: Any) -> Any:
        number = self._to_int(value)
        return number if number is not None else value

    def _loads_json(self, raw_content: str) -> dict[str, Any]:
        data = load_model_json(raw_content)
        return data

    def _as_string_list(self, value: Any) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    def _string_list(self, value: Any) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []

    def _to_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


register_ai_skill(ScenarioComposerSkill())
