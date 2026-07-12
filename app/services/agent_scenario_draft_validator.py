from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from app.services.agent_scenario_source_service import ResolvedScenarioSource
from app.services.scenario_graph_validator import ScenarioGraphValidator


SCENARIO_DRAFT_VALIDATION_SCHEMA_VERSION = "agent_scenario_draft_validation_v1"
_TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


@dataclass(frozen=True)
class ScenarioDraftValidationResult:
    valid: bool
    scenario: dict[str, Any]
    validation: dict[str, Any]


@dataclass(frozen=True)
class ScenarioDraftGroundingResult:
    scenario: dict[str, Any]
    grounding: dict[str, Any]


@dataclass(frozen=True)
class _VariableSource:
    name: str
    path: str
    step_id: str
    node_id: str
    extraction_id: str


class AgentScenarioDraftValidator:
    def ground(
        self,
        *,
        draft: dict[str, Any],
        source: ResolvedScenarioSource,
    ) -> ScenarioDraftGroundingResult:
        """Replace model-authored request details with the authoritative saved-case snapshots."""
        scenario = copy.deepcopy(draft)
        scenario["environment_id"] = source.environment_id
        case_index = {
            (_kind_for_case_type(str(item.get("case_type") or "")), _positive_int(item.get("reference_id"))): item
            for item in source.case_snapshots
            if _positive_int(item.get("reference_id")) is not None
        }
        canonicalized_node_count = 0
        removed_unsupported_extractor_count = 0
        nodes = scenario.get("nodes") if isinstance(scenario.get("nodes"), list) else []
        saved_by_node_identity: dict[int, dict[str, Any]] = {}
        for raw_node in nodes:
            if not isinstance(raw_node, dict) or not isinstance(raw_node.get("test_case"), dict):
                continue
            step = raw_node["test_case"]
            kind = str(step.get("kind") or "")
            reference_id = _positive_int(step.get("reference_id", step.get("referenceId")))
            saved = case_index.get((kind, reference_id))
            if saved is None:
                continue
            saved_by_node_identity[id(raw_node)] = saved
            original_config = step.get("config") if isinstance(step.get("config"), dict) else {}
            saved_extractors = [copy.deepcopy(item) for item in (saved.get("extractors") or []) if isinstance(item, dict)]
            saved_extractor_identities = {
                (str(item.get("name") or ""), str(item.get("path") or ""))
                for item in saved_extractors
            }
            original_extractor_identities = {
                (str(item.get("name") or ""), str(item.get("path") or ""))
                for item in _step_extractors(original_config)
                if item.get("name") and item.get("path") is not None
            }
            removed_unsupported_extractor_count += len(
                original_extractor_identities - saved_extractor_identities
            )
            authoritative_config = _authoritative_case_config(saved, kind=kind)
            before = {
                "method": step.get("method"),
                "path": step.get("path"),
                "config": original_config,
            }
            step["name"] = str(saved.get("name") or step.get("name") or "")
            step["method"] = str(saved.get("method") or ("WS" if kind == "websocket_case" else "")).upper()
            step["path"] = str(saved.get("path") or "")
            step["config"] = authoritative_config
            raw_node["name"] = step["name"]
            after = {
                "method": step["method"],
                "path": step["path"],
                "config": authoritative_config,
            }
            if before != after:
                canonicalized_node_count += 1
        dataset_variables = _dataset_variables(scenario)
        allowed_template_variables = set(source.environment_variable_names) | dataset_variables
        for saved in saved_by_node_identity.values():
            allowed_template_variables.update(
                str(item.get("name") or "")
                for item in (saved.get("extractors") or [])
                if isinstance(item, dict) and item.get("name")
            )
        grounded_nodes: list[dict[str, Any]] = []
        excluded_nodes: list[dict[str, Any]] = []
        for raw_node in nodes:
            if not isinstance(raw_node, dict):
                grounded_nodes.append(raw_node)
                continue
            step = raw_node.get("test_case") if isinstance(raw_node.get("test_case"), dict) else {}
            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            unresolved_variables = sorted({
                variable_name
                for _target, _target_path, variable_name in _template_bindings(config)
                if variable_name not in allowed_template_variables
            })
            if unresolved_variables and id(raw_node) in saved_by_node_identity:
                excluded_nodes.append({
                    "node_id": str(raw_node.get("id") or ""),
                    "reference_id": _positive_int(step.get("reference_id", step.get("referenceId"))),
                    "reason": "saved_case_external_template_unresolved",
                    "unresolved_variables": unresolved_variables,
                })
                continue
            grounded_nodes.append(raw_node)
        scenario["nodes"] = grounded_nodes
        return ScenarioDraftGroundingResult(
            scenario=scenario,
            grounding={
                "schema_version": "agent_scenario_evidence_grounding_v1",
                "source_case_count": len(source.case_snapshots),
                "referenced_node_count": len(nodes),
                "grounded_node_count": len(grounded_nodes),
                "excluded_node_count": len(excluded_nodes),
                "excluded_nodes": excluded_nodes,
                "canonicalized_node_count": canonicalized_node_count,
                "removed_unsupported_extractor_count": removed_unsupported_extractor_count,
                "dependency_policy": "saved_case_configuration_only",
            },
        )

    def validate(
        self,
        *,
        draft: dict[str, Any],
        source: ResolvedScenarioSource,
    ) -> ScenarioDraftValidationResult:
        graph_result = ScenarioGraphValidator().validate_and_repair(
            copy.deepcopy(draft),
            external_variables=set(source.environment_variable_names),
        )
        scenario = graph_result.scenario
        issues: list[dict[str, Any]] = []
        referenced_case_count = 0
        unresolved_reference_count = 0
        extractor_count = 0
        binding_count = 0
        resolved_template_count = 0
        unresolved_template_count = 0
        edges: set[tuple[str, str]] = set()

        nodes = scenario.get("nodes") if isinstance(scenario.get("nodes"), list) else []
        if not nodes:
            issues.append({"code": "scenario_nodes_missing"})

        if _positive_int(scenario.get("environment_id")) != source.environment_id:
            issues.append({
                "code": "scenario_environment_reference_mismatch",
                "expected_environment_id": source.environment_id,
                "actual_environment_id": scenario.get("environment_id"),
            })

        case_index = {
            (_kind_for_case_type(str(item.get("case_type") or "")), _positive_int(item.get("reference_id"))): item
            for item in source.case_snapshots
            if _positive_int(item.get("reference_id")) is not None
        }
        variable_sources: dict[str, list[_VariableSource]] = {}
        dataset_variables = _dataset_variables(scenario)
        environment_variables = set(source.environment_variable_names)
        ordered_steps: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

        for node_index, raw_node in enumerate(nodes, start=1):
            if not isinstance(raw_node, dict):
                issues.append({"code": "scenario_node_invalid", "node_index": node_index})
                continue
            node_id = str(raw_node.get("id") or f"NODE-{node_index}")
            step = raw_node.get("test_case")
            if not isinstance(step, dict):
                unresolved_reference_count += 1
                issues.append({"code": "scenario_node_test_case_missing", "node_id": node_id})
                continue
            step_id = str(step.get("id") or f"{node_id}-test_case")
            kind = str(step.get("kind") or "")
            reference_id = _positive_int(step.get("reference_id", step.get("referenceId")))
            saved = case_index.get((kind, reference_id))
            if saved is None:
                unresolved_reference_count += 1
                issues.append({
                    "code": "saved_case_reference_unresolved",
                    "node_id": node_id,
                    "step_id": step_id,
                    "kind": kind,
                    "reference_id": reference_id,
                })
                continue
            referenced_case_count += 1
            method = str(step.get("method") or "").upper()
            path = str(step.get("path") or "")
            saved_method = str(saved.get("method") or ("WS" if kind == "websocket_case" else "")).upper()
            saved_path = str(saved.get("path") or "")
            mismatch_fields: list[str] = []
            if method and method != saved_method:
                mismatch_fields.append("method")
            if path and path != saved_path:
                mismatch_fields.append("path")
            if mismatch_fields:
                issues.append({
                    "code": "node_request_reference_mismatch",
                    "node_id": node_id,
                    "step_id": step_id,
                    "reference_id": reference_id,
                    "fields": mismatch_fields,
                    "saved_method": saved_method,
                    "saved_path": saved_path,
                    "draft_method": method,
                    "draft_path": path,
                })

            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            ordered_steps.append((node_id, step_id, config, saved))
            saved_extractors = {
                (str(item.get("name") or ""), str(item.get("path") or ""))
                for item in (saved.get("extractors") or [])
                if isinstance(item, dict) and item.get("name") and item.get("path") is not None
            }
            seen_extractors: set[tuple[str, str]] = set()
            for extractor in _step_extractors(config):
                name = str(extractor.get("name") or "")
                extractor_path = str(extractor.get("path") or "")
                identity = (name, extractor_path)
                if not name or not extractor_path or identity in seen_extractors:
                    continue
                seen_extractors.add(identity)
                extractor_count += 1
                extraction_id = str(extractor.get("id") or f"VAR-{step_id}-{name}")
                if identity not in saved_extractors:
                    issues.append({
                        "code": "extractor_not_evidenced",
                        "node_id": node_id,
                        "step_id": step_id,
                        "name": name,
                        "path": extractor_path,
                        "reference_id": reference_id,
                    })
                    continue
                variable_sources.setdefault(name, []).append(_VariableSource(
                    name=name,
                    path=extractor_path,
                    step_id=step_id,
                    node_id=node_id,
                    extraction_id=extraction_id,
                ))

        for node_id, step_id, config, _saved in ordered_steps:
            context = config.get("_scenario_context") if isinstance(config.get("_scenario_context"), dict) else {}
            context_bindings = [
                item
                for item in (context.get("bindings") or context.get("inputBindings") or [])
                if isinstance(item, dict)
            ]
            for target, target_path, variable_name in _template_bindings(config):
                if variable_name in dataset_variables or variable_name in environment_variables:
                    resolved_template_count += 1
                    continue
                candidates = variable_sources.get(variable_name, [])
                if len(candidates) != 1:
                    unresolved_template_count += 1
                    issues.append({
                        "code": "binding_source_not_evidenced",
                        "node_id": node_id,
                        "step_id": step_id,
                        "variable": variable_name,
                        "candidate_source_count": len(candidates),
                        "target": target,
                        "target_path": target_path,
                    })
                    continue
                source_item = candidates[0]
                matching_bindings = [
                    item
                    for item in context_bindings
                    if _binding_name(item) == variable_name
                    and str(item.get("target") or "") == target
                    and str(item.get("target_path", item.get("targetPath", "")) or "") == target_path
                ]
                if len(matching_bindings) != 1:
                    unresolved_template_count += 1
                    issues.append({
                        "code": "template_binding_missing_or_ambiguous",
                        "node_id": node_id,
                        "step_id": step_id,
                        "variable": variable_name,
                        "target": target,
                        "target_path": target_path,
                        "binding_count": len(matching_bindings),
                    })
                    continue
                binding = matching_bindings[0]
                binding_source_step = str(binding.get("source_step_id", binding.get("sourceStepId", "")) or "")
                binding_source_extraction = str(
                    binding.get("source_extraction_id", binding.get("sourceExtractionId", "")) or ""
                )
                if (
                    binding_source_step != source_item.step_id
                    or binding_source_extraction != source_item.extraction_id
                ):
                    unresolved_template_count += 1
                    issues.append({
                        "code": "binding_source_reference_mismatch",
                        "node_id": node_id,
                        "step_id": step_id,
                        "variable": variable_name,
                        "expected_source_step_id": source_item.step_id,
                        "expected_source_extraction_id": source_item.extraction_id,
                    })
                    continue
                resolved_template_count += 1
                binding_count += 1
                edges.add((source_item.node_id, node_id))

        cycles = _cycle_edges(edges)
        if cycles:
            issues.append({"code": "scenario_dependency_cycle", "edges": [list(edge) for edge in cycles]})
        graph_errors = [
            item
            for item in (graph_result.validation.get("issues") or [])
            if isinstance(item, dict) and item.get("status") == "open"
        ]
        valid = not issues and not graph_errors and unresolved_reference_count == 0
        validation = {
            "schema_version": SCENARIO_DRAFT_VALIDATION_SCHEMA_VERSION,
            "valid": valid,
            "referenced_case_count": referenced_case_count,
            "unresolved_reference_count": unresolved_reference_count,
            "dependency_edge_count": len(edges),
            "resolved_template_count": resolved_template_count,
            "unresolved_template_count": unresolved_template_count,
            "extractor_count": extractor_count,
            "binding_count": binding_count,
            "graph_errors": graph_errors,
            "graph_validation": graph_result.validation,
            "graph_repair": graph_result.repair,
            "quality_issues": issues,
            "evidence_sources": [dict(item) for item in source.evidence_sources],
        }
        return ScenarioDraftValidationResult(valid=valid, scenario=scenario, validation=validation)


def _kind_for_case_type(case_type: str) -> str:
    return "websocket_case" if case_type == "websocket" else "api_case"


def _authoritative_case_config(saved: dict[str, Any], *, kind: str) -> dict[str, Any]:
    common = {
        "headers": copy.deepcopy(saved.get("headers") or {}),
        "assertions": copy.deepcopy(saved.get("assertions") or []),
        "extractors": copy.deepcopy(saved.get("extractors") or []),
        "retry_policy": copy.deepcopy(saved.get("retry_policy") or {}),
    }
    if kind == "websocket_case":
        return {
            **common,
            "subprotocols": copy.deepcopy(saved.get("subprotocols") or []),
            "messages": copy.deepcopy(saved.get("messages") or []),
            **({"receive_count": saved["receive_count"]} if saved.get("receive_count") is not None else {}),
            **({"connect_timeout_ms": saved["connect_timeout_ms"]} if saved.get("connect_timeout_ms") is not None else {}),
            **({"receive_timeout_ms": saved["receive_timeout_ms"]} if saved.get("receive_timeout_ms") is not None else {}),
        }
    return {
        **common,
        "query_params": copy.deepcopy(saved.get("query_params") or {}),
        "body_type": str(saved.get("body_type") or "none"),
        "body": copy.deepcopy(saved.get("body")),
    }


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dataset_variables(scenario: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for dataset in scenario.get("datasets") or []:
        if not isinstance(dataset, dict):
            continue
        variables = dataset.get("variables")
        if isinstance(variables, dict):
            names.update(str(name) for name in variables)
    return names


def _step_extractors(config: dict[str, Any]) -> list[dict[str, Any]]:
    result = [item for item in (config.get("extractors") or []) if isinstance(item, dict)]
    context = config.get("_scenario_context") if isinstance(config.get("_scenario_context"), dict) else {}
    result.extend(
        item
        for item in (context.get("extractions") or context.get("extractors") or [])
        if isinstance(item, dict)
    )
    return result


def _template_bindings(config: dict[str, Any]) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []

    def walk(value: Any, root: str, parts: list[str]) -> None:
        if isinstance(value, str):
            for match in _TEMPLATE_RE.finditer(value):
                result.append((root, ".".join(parts), match.group(1).strip()))
        elif isinstance(value, dict):
            for key, child in value.items():
                if key != "_scenario_context":
                    walk(child, root, [*parts, str(key)])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, root, [*parts, str(index)])

    for root in ("path", "headers", "query_params", "body", "messages", "subprotocols"):
        if root in config:
            walk(config[root], root, [])
    return result


def _binding_name(binding: dict[str, Any]) -> str:
    return str(
        binding.get("name")
        or binding.get("variable")
        or binding.get("variable_name")
        or binding.get("variableName")
        or ""
    )


def _cycle_edges(edges: set[tuple[str, str]]) -> list[tuple[str, str]]:
    adjacency: dict[str, set[str]] = {}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set())
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            cycle_nodes.add(node)
            return
        if node in visited:
            return
        visiting.add(node)
        for target in adjacency.get(node, set()):
            if target in visiting:
                cycle_nodes.update((node, target))
            else:
                visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in adjacency:
        visit(node)
    return sorted(edge for edge in edges if edge[0] in cycle_nodes and edge[1] in cycle_nodes)
