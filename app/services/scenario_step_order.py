import copy
from typing import Any


def ordered_scenario_steps(definition: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        raise RuntimeError("Scenario definition has not been migrated to nodes")
    steps: list[dict[str, Any]] = []
    for node_index, node in enumerate(nodes):
        node_id = str(node.get("id") or "")
        groups = (
            ("before", node.get("before_actions") or []),
            ("test_case", [node.get("test_case")]),
            ("after", node.get("after_actions") or []),
        )
        for phase, items in groups:
            for item in items:
                if not isinstance(item, dict):
                    raise RuntimeError(
                        f"Scenario node {node_id or node_index} is missing its test_case"
                    )
                step = copy.deepcopy(item)
                step["_node_id"] = node_id
                step["_node_index"] = node_index
                step["_node_phase"] = phase
                steps.append(step)
    return steps


def scenario_step_descriptors(
    definition: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        steps = ordered_scenario_steps(definition)
    except RuntimeError:
        return []
    return [
        {
            "step_id": str(step.get("id")),
            "step_index": index,
            "kind": str(step.get("kind") or "scenario"),
            "name": str(step.get("name") or step.get("id")),
            "node_id": step.get("_node_id"),
            "node_index": step.get("_node_index"),
            "node_phase": step.get("_node_phase"),
        }
        for index, step in enumerate(steps)
        if step.get("id")
    ]
