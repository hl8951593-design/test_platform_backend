import ast
import copy
import re
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.sensitive_data import (
    decrypt_sensitive,
    encrypt_sensitive,
    mask_sensitive,
    request_fingerprint,
)
from app.models.project import ProjectEnvironment
from app.models.scenario import TestScenario, TestScenarioRun, TestScenarioVersion
from app.models.test_case import TestCase
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase
from app.schemas.scenario import ScenarioCreateRequest, ScenarioPayload, ScenarioUpdateRequest
from app.schemas.test_case import TestCaseRequestConfig
from app.schemas.websocket_test_case import WebSocketTestCaseConfig
from app.services.permission_service import PermissionService
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class ScenarioService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_scenarios(self, *, project_id: int, current_user: User, keyword: str | None,
                       page: int, page_size: int) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        filters = [TestScenario.project_id == project_id, TestScenario.is_deleted.is_(False)]
        if keyword:
            filters.append(or_(TestScenario.name.contains(keyword), TestScenario.description.contains(keyword)))
        total = self.db.scalar(select(func.count()).select_from(TestScenario).where(*filters)) or 0
        scenarios = list(self.db.scalars(
            select(TestScenario).where(*filters).order_by(TestScenario.updated_at.desc(), TestScenario.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return {
            "items": [self._detail(item) for item in scenarios],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_scenario(self, *, project_id: int, scenario_id: int, current_user: User) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        return self._detail(self._get_scenario(project_id, scenario_id))

    def create_scenario(self, *, project_id: int, payload: ScenarioCreateRequest, current_user: User) -> dict[str, Any]:
        self._require_manage(current_user, project_id)
        definition = self._validated_definition(project_id, payload)
        scenario = TestScenario(
            project_id=project_id, environment_id=payload.environment_id, current_version=1,
            name=payload.name, description=payload.description, tags=payload.tags,
            created_by_id=current_user.id, updated_by_id=current_user.id,
        )
        self.db.add(scenario)
        self.db.flush()
        self.db.add(TestScenarioVersion(
            scenario_id=scenario.id, version=1, definition=definition, created_by_id=current_user.id
        ))
        self._commit_unique()
        self.db.refresh(scenario)
        return self._detail(scenario)

    def update_scenario(self, *, project_id: int, scenario_id: int, payload: ScenarioUpdateRequest,
                        current_user: User) -> dict[str, Any]:
        self._require_manage(current_user, project_id)
        scenario = self._get_scenario(project_id, scenario_id)
        if scenario.current_version != payload.version:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "message": "场景版本冲突", "current_version": scenario.current_version,
            })
        definition = self._validated_definition(project_id, payload)
        scenario.current_version += 1
        scenario.environment_id = payload.environment_id
        scenario.name = payload.name
        scenario.description = payload.description
        scenario.tags = payload.tags
        scenario.updated_by_id = current_user.id
        self.db.add(TestScenarioVersion(
            scenario_id=scenario.id, version=scenario.current_version,
            definition=definition, created_by_id=current_user.id,
        ))
        self._commit_unique()
        self.db.refresh(scenario)
        return self._detail(scenario)

    def delete_scenario(self, *, project_id: int, scenario_id: int, current_user: User) -> None:
        self._require_manage(current_user, project_id)
        scenario = self._get_scenario(project_id, scenario_id)
        from app.models.test_plan import TestPlan, TestPlanScenario

        referenced = self.db.scalar(
            select(func.count())
            .select_from(TestPlanScenario)
            .join(TestPlan, TestPlan.id == TestPlanScenario.plan_id)
            .where(TestPlanScenario.scenario_id == scenario_id, TestPlan.is_deleted.is_(False))
        ) or 0
        if referenced:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="场景已被测试计划引用，不能删除")
        version_ids = list(self.db.scalars(
            select(TestScenarioVersion.id).where(
                TestScenarioVersion.scenario_id == scenario.id
            )
        ).all())
        self.db.execute(
            update(TestScenarioRun)
            .where(TestScenarioRun.scenario_id == scenario.id)
            .values(scenario_id=None, scenario_version_id=None)
        )
        if version_ids:
            self.db.execute(
                delete(TestScenarioVersion).where(TestScenarioVersion.id.in_(version_ids))
            )
        self.db.delete(scenario)
        self.db.commit()

    def execute_scenario(self, *, project_id: int, scenario_id: int, environment_id: int | None,
                         dataset_ids: list[str] | None, idempotency_key: str | None, current_user: User,
                         trigger_type: str = "manual", scenario_version: int | None = None,
                         plan_run_id: int | None = None, deadline: datetime | None = None) -> list[TestScenarioRun]:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        scenario = self._get_scenario(project_id, scenario_id)
        version = self._get_version(scenario, scenario_version)
        definition = decrypt_sensitive(copy.deepcopy(version.definition))
        selected_environment_id = environment_id or scenario.environment_id
        self._get_environment(project_id, selected_environment_id)
        all_datasets = definition.get("datasets", [])
        datasets = [item for item in all_datasets if item.get("enabled", True)]
        if dataset_ids is not None:
            requested = set(dataset_ids)
            datasets = [item for item in all_datasets if item["id"] in requested]
            if {item["id"] for item in datasets} != requested:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据集不存在")
        elif not all_datasets:
            datasets = [{"id": None, "name": None, "variables": {}}]

        runs = []
        for dataset in datasets:
            key = f"{idempotency_key}:{dataset['id']}" if idempotency_key and dataset["id"] else idempotency_key
            fingerprint = request_fingerprint({
                "scenario_id": scenario.id,
                "scenario_version": version.version,
                "environment_id": selected_environment_id,
                "dataset_id": dataset.get("id"),
                "plan_run_id": plan_run_id,
            })
            existing = self._idempotent(project_id, key, fingerprint)
            if existing:
                runs.append(existing)
                continue
            runs.append(self._execute_dataset(
                scenario=scenario, version=version, definition=definition, environment_id=selected_environment_id,
                dataset=dataset, idempotency_key=key, request_hash=fingerprint,
                current_user=current_user, trigger_type=trigger_type, plan_run_id=plan_run_id,
                deadline=deadline,
            ))
        if runs:
            scenario.last_run_at = datetime.utcnow()
            self.db.commit()
        return runs

    def list_runs(self, *, project_id: int, scenario_id: int | None, current_user: User) -> list[TestScenarioRun]:
        self._require_view(current_user, project_id)
        filters = [TestScenarioRun.project_id == project_id]
        if scenario_id is not None:
            filters.append(TestScenarioRun.scenario_id == scenario_id)
        return list(self.db.scalars(
            select(TestScenarioRun).where(*filters).order_by(TestScenarioRun.started_at.desc(), TestScenarioRun.id.desc())
            .limit(200)
        ).all())

    def get_run(self, *, project_id: int, run_id: int, current_user: User) -> TestScenarioRun:
        self._require_view(current_user, project_id)
        run = self.db.scalar(select(TestScenarioRun).where(
            TestScenarioRun.id == run_id, TestScenarioRun.project_id == project_id
        ))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景运行记录不存在")
        return run

    def _execute_dataset(self, *, scenario: TestScenario, version: TestScenarioVersion, definition: dict,
                         environment_id: int, dataset: dict, idempotency_key: str | None, request_hash: str,
                         current_user: User, trigger_type: str, plan_run_id: int | None,
                         deadline: datetime | None) -> TestScenarioRun:
        started_at = datetime.utcnow()
        variables = copy.deepcopy(dataset.get("variables") or {})
        run = TestScenarioRun(
            scenario_id=scenario.id, scenario_version_id=version.id, plan_run_id=plan_run_id,
            project_id=scenario.project_id,
            environment_id=environment_id, dataset_id=dataset.get("id"), dataset_name=dataset.get("name"),
            status="running", trigger_type=trigger_type, idempotency_key=idempotency_key,
            request_hash=request_hash, scenario_snapshot=mask_sensitive(definition),
            variables_snapshot=mask_sensitive(variables),
            step_results=[], triggered_by_id=current_user.id, started_at=started_at,
        )
        self.db.add(run)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._idempotent(scenario.project_id, idempotency_key, request_hash)
            if existing:
                return existing
            raise
        self.db.refresh(run)

        results = []
        stop = False
        for index, step in enumerate(definition["steps"], start=1):
            if deadline is not None and datetime.utcnow() >= deadline:
                results.append(self._timeout_result(step, index))
                stop = True
                continue
            if stop:
                results.append(self._skipped_result(step, index))
                continue
            result = self._execute_step(
                project_id=scenario.project_id, environment_id=environment_id, step=step,
                step_index=index, variables=variables, previous_results=results, current_user=current_user,
                scenario_run_id=run.id, deadline=deadline,
            )
            results.append(result)
            if result["status"] != "passed" and not step.get("continue_on_failure", False):
                stop = True

        finished_at = datetime.utcnow()
        run.step_results = results
        run.variables_snapshot = mask_sensitive(variables)
        run.status = (
            "timeout" if any(item["status"] == "timeout" for item in results)
            else "failed" if any(item["status"] == "failed" for item in results)
            else "passed"
        )
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _execute_step(self, *, project_id: int, environment_id: int, step: dict, step_index: int,
                      variables: dict[str, Any], previous_results: list[dict], current_user: User,
                      scenario_run_id: int, deadline: datetime | None) -> dict[str, Any]:
        started_at = datetime.utcnow()
        execution_id = None
        error_message = None
        status_value = "passed"
        output = None
        try:
            remaining = (deadline - datetime.utcnow()).total_seconds() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise TimeoutError("Scenario execution deadline exceeded")
            config = self._render(step.get("config") or {}, variables)
            if step["kind"] == "delay":
                delay_seconds = config.get("delayMs", config.get("delay_ms", 0)) / 1000
                if remaining is not None and delay_seconds > remaining:
                    raise TimeoutError("Scenario execution deadline exceeded")
                time.sleep(delay_seconds)
            elif step["kind"] == "condition":
                passed = self._evaluate_condition(str(config["expression"]), variables, previous_results)
                output = {"result": passed}
                if not passed:
                    status_value = "failed"
                    error_message = "条件判断结果为 false"
            elif step["kind"] == "api_case":
                data = copy.deepcopy(step["case_snapshot"])
                data["environment_id"] = environment_id
                data.update(config)
                data["environment_id"] = environment_id
                payload = TestCaseRequestConfig.model_validate(self._render(data, variables))
                existing_case_id = self.db.scalar(
                    select(TestCase.id).where(
                        TestCase.project_id == project_id,
                        TestCase.id == step["reference_id"],
                    )
                )
                execution = TestCaseService(self.db)._execute(  # noqa: SLF001
                    project_id=project_id, test_case_id=existing_case_id, payload=payload,
                    current_user=current_user, scenario_run_id=scenario_run_id, timeout_seconds=remaining,
                )
                execution_id, status_value = execution.id, execution.status
                output = execution.response_snapshot
                error_message = execution.error_message
            else:
                data = copy.deepcopy(step["case_snapshot"])
                data["environment_id"] = environment_id
                data.update(config)
                data["environment_id"] = environment_id
                payload = WebSocketTestCaseConfig.model_validate(self._render(data, variables))
                existing_case_id = self.db.scalar(
                    select(WebSocketTestCase.id).where(
                        WebSocketTestCase.project_id == project_id,
                        WebSocketTestCase.id == step["reference_id"],
                    )
                )
                execution = WebSocketTestCaseService(self.db)._execute(  # noqa: SLF001
                    project_id, existing_case_id, payload, current_user,
                    scenario_run_id=scenario_run_id, timeout_seconds=remaining,
                )
                execution_id, status_value = execution.id, execution.status
                output = execution.response_snapshot
                error_message = execution.error_message
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            status_value = "timeout" if isinstance(exc, TimeoutError) else "failed"
            error_message = str(exc)
        finished_at = datetime.utcnow()
        result = {
            "step_id": step["id"], "step_index": step_index, "kind": step["kind"], "name": step["name"],
            "status": status_value if status_value in {"passed", "timeout"} else "failed",
            "output": output, "error_message": error_message, "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        }
        variables[f"step_{step_index}"] = output
        return result

    def _validated_definition(self, project_id: int, payload: ScenarioPayload) -> dict:
        self._get_environment(project_id, payload.environment_id)
        steps = []
        for item in payload.steps:
            step = item.model_dump()
            if item.kind == "api_case":
                asset = self.db.scalar(select(TestCase).where(TestCase.id == item.reference_id, TestCase.project_id == project_id))
            elif item.kind == "websocket_case":
                asset = self.db.scalar(select(WebSocketTestCase).where(
                    WebSocketTestCase.id == item.reference_id, WebSocketTestCase.project_id == project_id
                ))
            else:
                asset = None
            if item.kind in {"api_case", "websocket_case"}:
                if asset is None:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"步骤引用用例不存在: {item.id}")
                step.update({"name": asset.name, "method": asset.method if item.kind == "api_case" else "WS", "path": asset.path})
                step["case_snapshot"] = self._case_snapshot(asset, websocket=item.kind == "websocket_case")
            steps.append(step)
        return encrypt_sensitive({"steps": steps, "datasets": [item.model_dump() for item in payload.datasets]})

    def _detail(self, scenario: TestScenario) -> dict[str, Any]:
        version = self._get_version(scenario)
        definition = decrypt_sensitive(version.definition)
        public_steps = []
        for item in definition["steps"]:
            step = copy.deepcopy(item)
            step.pop("case_snapshot", None)
            public_steps.append(step)
        return {
            "id": scenario.id, "project_id": scenario.project_id, "environment_id": scenario.environment_id,
            "current_version": scenario.current_version, "name": scenario.name, "description": scenario.description,
            "tags": scenario.tags, "steps": public_steps, "datasets": mask_sensitive(definition["datasets"]),
            "created_at": scenario.created_at, "updated_at": scenario.updated_at, "last_run_at": scenario.last_run_at,
        }

    def _get_scenario(self, project_id: int, scenario_id: int) -> TestScenario:
        item = self.db.scalar(select(TestScenario).where(
            TestScenario.id == scenario_id, TestScenario.project_id == project_id, TestScenario.is_deleted.is_(False)
        ))
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
        return item

    def _get_version(self, scenario: TestScenario, version_number: int | None = None) -> TestScenarioVersion:
        version = self.db.scalar(select(TestScenarioVersion).where(
            TestScenarioVersion.scenario_id == scenario.id,
            TestScenarioVersion.version == (version_number or scenario.current_version),
        ))
        if version is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="场景版本不存在")
        return version

    def _case_snapshot(self, case: TestCase | WebSocketTestCase, *, websocket: bool) -> dict[str, Any]:
        if websocket:
            return {
                "path": case.path, "headers": copy.deepcopy(case.headers), "subprotocols": copy.deepcopy(case.subprotocols or []),
                "messages": copy.deepcopy(case.messages or []), "receive_count": case.receive_count,
                "connect_timeout_ms": case.connect_timeout_ms, "receive_timeout_ms": case.receive_timeout_ms,
                "assertions": copy.deepcopy(case.assertions or []), "extractors": copy.deepcopy(case.extractors or []),
            }
        return {
            "method": case.method, "path": case.path, "headers": copy.deepcopy(case.headers),
            "query_params": copy.deepcopy(case.query_params), "body_type": case.body_type, "body": copy.deepcopy(case.body),
            "assertions": copy.deepcopy(case.assertions or []), "extractors": copy.deepcopy(case.extractors or []),
        }

    def _get_environment(self, project_id: int, environment_id: int) -> ProjectEnvironment:
        item = self.db.scalar(select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id, ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        ))
        if item is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="执行环境不存在或不属于当前项目")
        return item

    def _idempotent(self, project_id: int, key: str | None, request_hash: str) -> TestScenarioRun | None:
        if not key:
            return None
        existing = self.db.scalar(select(TestScenarioRun).where(
            TestScenarioRun.project_id == project_id, TestScenarioRun.idempotency_key == key
        ))
        if existing is not None and existing.request_hash and existing.request_hash != request_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="幂等键已用于不同的场景执行请求")
        return existing

    def _render(self, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            matches = list(re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", value))
            if len(matches) == 1 and matches[0].span() == (0, len(value)):
                resolved = self._resolve_path(variables, matches[0].group(1))
                return value if resolved is None else copy.deepcopy(resolved)
            return re.sub(
                r"\{\{\s*([^{}]+?)\s*\}\}",
                lambda match: (
                    match.group(0)
                    if (resolved := self._resolve_path(variables, match.group(1))) is None
                    else str(resolved)
                ),
                value,
            )
        if isinstance(value, dict):
            return {key: self._render(item, variables) for key, item in value.items()}
        if isinstance(value, list):
            return [self._render(item, variables) for item in value]
        return value

    def _resolve_path(self, values: dict[str, Any], path: str) -> Any:
        current: Any = values
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return None
        return current

    def _evaluate_condition(self, expression: str, variables: dict[str, Any], results: list[dict]) -> bool:
        tree = ast.parse(expression, mode="eval")
        allowed = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Name, ast.Load, ast.Constant,
                   ast.Subscript, ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.Lt, ast.LtE)
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise ValueError("条件表达式包含不支持的语法")
        return bool(eval(compile(tree, "<scenario-condition>", "eval"), {"__builtins__": {}}, {
            "variables": variables, "steps": results,
        }))

    def _skipped_result(self, step: dict, index: int) -> dict:
        now = datetime.utcnow().isoformat()
        return {"step_id": step["id"], "step_index": index, "kind": step["kind"], "name": step["name"],
                "status": "skipped", "execution_id": None, "output": None, "error_message": None,
                "started_at": now, "finished_at": now, "duration_ms": 0}

    def _timeout_result(self, step: dict, index: int) -> dict:
        now = datetime.utcnow().isoformat()
        return {"step_id": step["id"], "step_index": index, "kind": step["kind"], "name": step["name"],
                "status": "timeout", "execution_id": None, "output": None,
                "error_message": "Scenario execution deadline exceeded",
                "started_at": now, "finished_at": now, "duration_ms": 0}

    def _commit_unique(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同一项目下场景名称不能重复") from exc

    def _require_view(self, user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(user, project_id, ProjectPermission.VIEW_SCENARIO.value)

    def _require_manage(self, user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(user, project_id, ProjectPermission.MANAGE_SCENARIO.value)
