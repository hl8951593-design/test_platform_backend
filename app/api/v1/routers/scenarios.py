import json
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.db.session import SessionLocal
from app.models.scenario import (
    TestScenarioRun,
    TestScenarioRunEvent,
    TestScenarioVersion,
)
from app.models.user import User
from app.schemas.scenario import (
    ScenarioCreateRequest,
    ScenarioExecuteRequest,
    ScenarioExecutionQueuedRead,
    ScenarioRead,
    ScenarioRunRead,
    ScenarioUpdateRequest,
)
from app.services.scenario_service import ScenarioService

router = APIRouter()
run_router = APIRouter()


@router.get("", summary="查询项目场景列表")
def list_scenarios(
    project_id: int,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ScenarioService(db).list_scenarios(
        project_id=project_id,
        current_user=current_user,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    result["items"] = [ScenarioRead.model_validate(item) for item in result["items"]]
    return success(data=result)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建场景")
def create_scenario(
    project_id: int,
    payload: ScenarioCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = ScenarioService(db).create_scenario(
        project_id=project_id, payload=payload, current_user=current_user
    )
    return success(data=ScenarioRead.model_validate(item), message="场景创建成功")


@router.get("/{scenario_id}", summary="查询场景详情")
def get_scenario(
    project_id: int,
    scenario_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = ScenarioService(db).get_scenario(
        project_id=project_id, scenario_id=scenario_id, current_user=current_user
    )
    return success(data=ScenarioRead.model_validate(item))


@router.put("/{scenario_id}", summary="更新场景")
def update_scenario(
    project_id: int,
    scenario_id: int,
    payload: ScenarioUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = ScenarioService(db).update_scenario(
        project_id=project_id,
        scenario_id=scenario_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=ScenarioRead.model_validate(item), message="场景更新成功")


@router.delete("/{scenario_id}", summary="删除场景")
def delete_scenario(
    project_id: int,
    scenario_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ScenarioService(db).delete_scenario(
        project_id=project_id, scenario_id=scenario_id, current_user=current_user
    )
    return success(message="场景删除成功")


@router.post(
    "/{scenario_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScenarioExecutionQueuedRead,
    summary="异步执行场景",
)
def execute_scenario(
    project_id: int,
    scenario_id: int,
    payload: ScenarioExecuteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = ScenarioService(db).enqueue_scenario(
        project_id=project_id,
        scenario_id=scenario_id,
        environment_id=payload.environment_id,
        dataset_ids=payload.dataset_ids,
        idempotency_key=payload.idempotency_key,
        current_user=current_user,
    )
    if execution["status"] == "queued":
        background_tasks.add_task(
            ScenarioService.execute_queued_execution, execution["execution_id"]
        )
    return execution


@run_router.get("", summary="查询场景调试历史")
def list_scenario_runs(
    project_id: int,
    scenario_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runs = ScenarioService(db).list_runs(
        project_id=project_id, scenario_id=scenario_id, current_user=current_user
    )
    return success(data=[ScenarioRunRead.model_validate(run) for run in runs])


@run_router.get("/{run_id}", summary="查询场景运行详情")
def get_scenario_run(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = ScenarioService(db).get_run_detail(
        project_id=project_id, run_id=run_id, current_user=current_user
    )
    return success(data=ScenarioRunRead.model_validate(run))


@run_router.delete("/{run_id}", summary="删除场景运行记录")
def delete_scenario_run(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ScenarioService(db).delete_run(
        project_id=project_id, run_id=run_id, current_user=current_user
    )
    return success(message="场景运行记录已删除")


@run_router.get("/{run_id}/events", summary="订阅场景运行实时事件")
def stream_scenario_run_events(
    project_id: int,
    run_id: int,
    last_event_id: int = Header(default=0, alias="Last-Event-ID", ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ScenarioService(db).get_run(
        project_id=project_id, run_id=run_id, current_user=current_user
    )

    def event_stream():
        sequence = last_event_id
        heartbeat_at = time.monotonic()
        while True:
            with SessionLocal() as event_db:
                run = event_db.scalar(select(TestScenarioRun).where(
                    TestScenarioRun.id == run_id,
                    TestScenarioRun.project_id == project_id,
                ))
                if run is None:
                    return
                events = list(event_db.scalars(
                    select(TestScenarioRunEvent)
                    .where(
                        TestScenarioRunEvent.run_id == run_id,
                        TestScenarioRunEvent.sequence > sequence,
                    )
                    .order_by(TestScenarioRunEvent.sequence)
                ).all())
                run_status = run.status
                last_sequence = run.last_event_sequence

            for item in events:
                sequence = item.sequence
                yield (
                    f"id: {item.sequence}\n"
                    f"event: {item.event}\n"
                    f"data: {json.dumps(item.payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
                heartbeat_at = time.monotonic()

            if (
                run_status in {"passed", "failed", "timeout", "cancelled"}
                and sequence >= last_sequence
            ):
                return
            if time.monotonic() - heartbeat_at >= 15:
                with SessionLocal() as heartbeat_db:
                    heartbeat_run = heartbeat_db.scalar(
                        select(TestScenarioRun)
                        .where(
                            TestScenarioRun.id == run_id,
                            TestScenarioRun.project_id == project_id,
                        )
                        .with_for_update()
                    )
                    if heartbeat_run is None:
                        return
                    if heartbeat_run.status in {
                        "passed", "failed", "timeout", "cancelled"
                    }:
                        continue
                    heartbeat_version = heartbeat_db.get(
                        TestScenarioVersion, heartbeat_run.scenario_version_id
                    )
                    item = ScenarioService(heartbeat_db)._append_event(
                        heartbeat_run,
                        heartbeat_version.version if heartbeat_version else 0,
                        "heartbeat",
                        {"status": heartbeat_run.status},
                    )
                    sequence = item.sequence
                    heartbeat_payload = item.payload
                yield (
                    f"id: {sequence}\n"
                    "event: heartbeat\n"
                    f"data: {json.dumps(heartbeat_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
                heartbeat_at = time.monotonic()
            time.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
