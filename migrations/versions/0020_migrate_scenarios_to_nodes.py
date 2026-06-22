"""migrate scenario definitions from steps to nodes

Revision ID: 0020_scenario_nodes
Revises: 0019_media_objects
"""

from collections.abc import Sequence
import copy

from alembic import op
import sqlalchemy as sa


revision: str = "0020_scenario_nodes"
down_revision: str | Sequence[str] | None = "0019_media_objects"
branch_labels = None
depends_on = None


ACTION_KINDS = {"condition", "delay", "random", "fixed_value", "script"}
CASE_KINDS = {"api_case", "websocket_case"}


def _without_phase(step: dict) -> dict:
    result = copy.deepcopy(step)
    result.pop("execution_phase", None)
    result.pop("executionPhase", None)
    result.pop("phase", None)
    return result


def _convert_definition(version_id: int, definition: dict) -> dict:
    if isinstance(definition.get("nodes"), list) and "steps" not in definition:
        return definition
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"version {version_id}: steps is missing or empty")

    if any(not isinstance(step, dict) for step in steps):
        raise ValueError(f"version {version_id}: step is not an object")
    ordered_steps = sorted(
        enumerate(steps),
        key=lambda pair: (
            {"setup": 0, "main": 1, "teardown": 2}.get(
                pair[1].get(
                    "execution_phase",
                    pair[1].get("executionPhase", pair[1].get("phase", "main")),
                ),
                1,
            ),
            pair[0],
        ),
    )
    normalized = []
    for _, step in ordered_steps:
        phase = step.get("execution_phase", step.get("executionPhase", step.get("phase", "main")))
        kind = step.get("kind")
        if phase not in {"setup", "main", "teardown"}:
            raise ValueError(f"version {version_id}: unknown execution phase {phase!r}")
        if kind not in ACTION_KINDS | CASE_KINDS:
            raise ValueError(
                f"version {version_id}: unsupported step kind {kind!r}"
            )
        if phase == "teardown" and kind in CASE_KINDS:
            raise ValueError(
                f"version {version_id}: teardown test cases cannot be represented safely"
            )
        normalized.append((phase, kind, _without_phase(step)))

    cases = [item for _, kind, item in normalized if kind in CASE_KINDS]
    if not cases:
        raise ValueError(f"version {version_id}: no main API/WebSocket test case")

    teardown_actions = [
        item for phase, kind, item in normalized
        if phase == "teardown" and kind in ACTION_KINDS
    ]
    before_teardown = [
        item for phase, _, item in normalized if phase != "teardown"
    ]
    if teardown_actions and any(
        not item.get("continue_on_failure", False) for item in before_teardown
    ):
        raise ValueError(
            f"version {version_id}: global teardown cannot be preserved after a stopping step"
        )

    nodes = []
    pending_actions = []
    for phase, kind, item in normalized:
        if phase == "teardown":
            continue
        if kind in ACTION_KINDS:
            pending_actions.append(item)
            continue
        index = len(nodes)
        nodes.append({
            "id": f"MIGRATED-NODE-{index + 1}",
            "name": str(item.get("name") or item.get("id") or f"Node {index + 1}"),
            "before_actions": pending_actions,
            "test_case": item,
            "after_actions": [],
        })
        pending_actions = []

    if pending_actions:
        if any(
            not action.get("continue_on_failure", False)
            for action in pending_actions[:-1]
        ):
            raise ValueError(
                f"version {version_id}: terminal actions contain an ambiguous stopping boundary"
            )
        nodes[-1]["after_actions"].extend(pending_actions)
    nodes[-1]["after_actions"].extend(teardown_actions)
    converted = copy.deepcopy(definition)
    converted.pop("steps", None)
    converted["nodes"] = nodes
    return converted


def upgrade() -> None:
    connection = op.get_bind()
    versions = sa.table(
        "test_scenario_versions",
        sa.column("id", sa.Integer()),
        sa.column("definition", sa.JSON()),
    )
    rows = connection.execute(sa.select(versions.c.id, versions.c.definition)).mappings().all()
    converted = []
    errors = []
    for row in rows:
        try:
            converted.append((row["id"], _convert_definition(row["id"], row["definition"] or {})))
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError(
            "Scenario node migration aborted; manually migrate or remove these definitions: "
            + "; ".join(errors)
        )
    for version_id, definition in converted:
        connection.execute(
            versions.update().where(versions.c.id == version_id).values(definition=definition)
        )


def downgrade() -> None:
    raise RuntimeError("Scenario nodes migration is intentionally irreversible")
