from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


SCENARIO_GRAPH_VALIDATION_SCHEMA_VERSION = "scenario_graph_validation_v1"
SCENARIO_GRAPH_REPAIR_SCHEMA_VERSION = "scenario_graph_repair_v1"
_TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


@dataclass(frozen=True)
class ScenarioGraphValidation:
    scenario: dict[str, Any]
    validation: dict[str, Any]
    repair: dict[str, Any]


class ScenarioGraphValidator:
    """Validates scenario variable graph and applies deterministic safe repairs."""

    def validate_and_repair(self, scenario: dict[str, Any]) -> ScenarioGraphValidation:
        repaired = copy.deepcopy(scenario)
        initial_issues = self._repair_missing_context_metadata(repaired)
        open_issues = self._validate_open_issues(repaired)
        repaired_issue_codes = sorted({issue["code"] for issue in initial_issues if issue.get("status") == "repaired"})
        validation = {
            "schema_version": SCENARIO_GRAPH_VALIDATION_SCHEMA_VERSION,
            "valid": not open_issues,
            "issue_count": len(initial_issues) + len(open_issues),
            "open_issue_count": len(open_issues),
            "issues": [*initial_issues, *open_issues],
        }
        repair = {
            "schema_version": SCENARIO_GRAPH_REPAIR_SCHEMA_VERSION,
            "applied": bool(repaired_issue_codes),
            "repaired_issue_codes": repaired_issue_codes,
        }
        return ScenarioGraphValidation(scenario=repaired, validation=validation, repair=repair)

    def _repair_missing_context_metadata(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        variables = self._dataset_variables(scenario)
        variable_sources: dict[str, dict[str, str]] = {
            name: {"source_step_id": "dataset", "source_extraction_id": ""}
            for name in variables
        }
        for step in self._execution_steps(scenario):
            config = step.get("config")
            if not isinstance(config, dict):
                continue
            context = self._ensure_context(config)
            extractors = [item for item in config.get("extractors") or [] if isinstance(item, dict)]
            context_extractions = self._context_items(context, "extractions", "extractors")
            context_extraction_names = {str(item.get("name")) for item in context_extractions if item.get("name")}
            missing_context_extractors = [
                copy.deepcopy(item)
                for item in extractors
                if item.get("name") and str(item.get("name")) not in context_extraction_names
            ]
            if missing_context_extractors:
                context.setdefault("extractions", [])
                context["extractions"].extend(self._extractors_with_ids(missing_context_extractors, step_id=step["id"]))
                issues.append({
                    "code": "missing_scenario_context_extraction",
                    "status": "repaired",
                    "step_id": step["id"],
                    "variables": [str(item.get("name")) for item in missing_context_extractors if item.get("name")],
                })

            for target, target_path, variable_name in self._template_bindings(config):
                if variable_name not in variables:
                    continue
                if self._has_binding(context, target=target, target_path=target_path, variable_name=variable_name):
                    continue
                source = variable_sources.get(variable_name, {})
                context.setdefault("bindings", [])
                context["bindings"].append({
                    "id": self._trace_id("BIND-GRAPH", step["id"], target, target_path, variable_name),
                    "source_step_id": source.get("source_step_id", ""),
                    "source_extraction_id": source.get("source_extraction_id", ""),
                    "name": variable_name,
                    "target": target,
                    "target_path": target_path,
                })
                issues.append({
                    "code": "missing_binding",
                    "status": "repaired",
                    "step_id": step["id"],
                    "variable": variable_name,
                    "target": target,
                    "target_path": target_path,
                })

            variables.update(self._action_output_variables(step))
            for extraction in self._context_items(context, "extractions", "extractors"):
                name = extraction.get("name")
                path = extraction.get("path")
                if not name or path is None:
                    continue
                extraction_id = str(extraction.get("id") or self._trace_id("VAR-GRAPH", step["id"], name, path))
                extraction["id"] = extraction_id
                variable_name = str(name)
                variables.add(variable_name)
                variable_sources[variable_name] = {
                    "source_step_id": step["id"],
                    "source_extraction_id": extraction_id,
                }
        return issues

    def _validate_open_issues(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        variables = self._dataset_variables(scenario)
        for step in self._execution_steps(scenario):
            config = step.get("config")
            if not isinstance(config, dict):
                continue
            for target, target_path, variable_name in self._template_bindings(config):
                if variable_name not in variables:
                    issues.append({
                        "code": "undefined_variable",
                        "status": "open",
                        "step_id": step["id"],
                        "variable": variable_name,
                        "target": target,
                        "target_path": target_path,
                    })
            variables.update(self._action_output_variables(step))
            context = config.get("_scenario_context") if isinstance(config.get("_scenario_context"), dict) else {}
            for extraction in self._context_items(context, "extractions", "extractors"):
                name = extraction.get("name")
                path = extraction.get("path")
                if name and path is not None:
                    variables.add(str(name))
        return issues

    def _execution_steps(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        nodes = scenario.get("nodes") if isinstance(scenario.get("nodes"), list) else []
        for node_index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or f"NODE-{node_index}")
            for phase, raw_steps in (
                ("before", node.get("before_actions") or []),
                ("test_case", [node.get("test_case")]),
                ("after", node.get("after_actions") or []),
            ):
                for step_index, raw_step in enumerate(raw_steps, start=1):
                    if not isinstance(raw_step, dict):
                        continue
                    step = raw_step
                    step_id = str(step.get("id") or f"{node_id}-{phase}-{step_index}")
                    step.setdefault("id", step_id)
                    steps.append({
                        "id": step_id,
                        "node_id": node_id,
                        "phase": phase,
                        "kind": step.get("kind"),
                        "config": step.get("config") if isinstance(step.get("config"), dict) else {},
                    })
        return steps

    def _dataset_variables(self, scenario: dict[str, Any]) -> set[str]:
        variables: set[str] = set()
        datasets = scenario.get("datasets") if isinstance(scenario.get("datasets"), list) else []
        for dataset in datasets:
            if not isinstance(dataset, dict):
                continue
            raw_variables = dataset.get("variables")
            if isinstance(raw_variables, dict):
                variables.update(str(key) for key in raw_variables)
        return variables

    def _action_output_variables(self, step: dict[str, Any]) -> set[str]:
        config = step.get("config") if isinstance(step.get("config"), dict) else {}
        outputs: set[str] = set()
        output = config.get("output")
        if isinstance(output, str) and output.strip():
            outputs.add(output.strip())
        raw_outputs = config.get("outputs")
        if isinstance(raw_outputs, list):
            outputs.update(str(item).strip() for item in raw_outputs if str(item).strip())
        return outputs

    def _template_bindings(self, config: dict[str, Any]) -> list[tuple[str, str, str]]:
        bindings: list[tuple[str, str, str]] = []

        def walk(value: Any, root: str, parts: list[str]) -> None:
            if isinstance(value, str):
                for match in _TEMPLATE_RE.finditer(value):
                    bindings.append((root, ".".join(parts), match.group(1).strip()))
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key == "_scenario_context":
                        continue
                    walk(item, root, [*parts, str(key)])
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, root, [*parts, str(index)])

        for root in ("path", "headers", "query_params", "body", "messages", "subprotocols"):
            if root in config:
                walk(config[root], root, [])
        return bindings

    def _ensure_context(self, config: dict[str, Any]) -> dict[str, Any]:
        context = config.get("_scenario_context")
        if not isinstance(context, dict):
            context = {}
            config["_scenario_context"] = context
        return context

    def _context_items(self, context: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        for key in keys:
            value = context.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _extractors_with_ids(self, extractors: list[dict[str, Any]], *, step_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for extractor in extractors:
            item = dict(extractor)
            if not item.get("id"):
                item["id"] = self._trace_id("VAR-GRAPH", step_id, item.get("name"), item.get("path"))
            result.append(item)
        return result

    def _has_binding(
        self,
        context: dict[str, Any],
        *,
        target: str,
        target_path: str,
        variable_name: str,
    ) -> bool:
        for binding in self._context_items(context, "bindings", "inputBindings", "input_bindings"):
            binding_target = str(binding.get("target") or "")
            binding_path = str(binding.get("target_path", binding.get("targetPath", "")) or "")
            binding_name = str(
                binding.get("name")
                or binding.get("variable")
                or binding.get("variable_name")
                or binding.get("variableName")
                or ""
            )
            if binding_target == target and binding_path == target_path and binding_name == variable_name:
                return True
        return False

    def _trace_id(self, prefix: str, *parts: Any) -> str:
        token = "-".join(str(part) for part in parts if part not in (None, ""))
        token = re.sub(r"[^A-Za-z0-9_-]+", "-", token).strip("-")
        return f"{prefix}-{token}"[:128] if token else prefix
