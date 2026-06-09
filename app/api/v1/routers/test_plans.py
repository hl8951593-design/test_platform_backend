from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.test_plan import TestPlanRun
from app.models.user import User
from app.schemas.test_plan import (
    TestPlanCreateRequest,
    TestPlanEnabledRequest,
    TestPlanExecuteRequest,
    TestPlanImportRequest,
    TestPlanRead,
    TestPlanUpdateRequest,
)
from app.services.test_plan_service import TestPlanService

router = APIRouter()
run_router = APIRouter()


def _plan_data(plan):
    return TestPlanRead.model_validate(plan)


def _run_data(run: TestPlanRun, *, include_results: bool = False):
    return {
        "id": run.id, "plan_id": run.plan_id, "plan_name": run.plan_name, "plan_version": run.plan_version,
        "project_id": run.project_id, "environment_id": run.environment_id, "environment_name": run.environment_name,
        "status": run.status, "trigger": run.trigger, "scheduled_at": run.scheduled_at,
        "started_at": run.started_at, "finished_at": run.finished_at,
        "duration_ms": run.duration_ms, "target_count": run.target_count, "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "operator": {"id": run.operator_id, "name": run.operator.username if run.operator else str(run.operator_id)},
        **({"target_results": run.target_results} if include_results else {}),
    }


@router.get("", summary="查询测试计划列表")
def list_plans(
    project_id: int, keyword: str | None = None, enabled: bool | None = None, trigger_type: str | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = TestPlanService(db).list_plans(
        project_id=project_id, current_user=current_user, keyword=keyword, enabled=enabled,
        trigger_type=trigger_type, page=page, page_size=page_size,
    )
    result["items"] = [_plan_data(item) for item in result["items"]]
    return success(data=result)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建测试计划")
def create_plan(project_id: int, payload: TestPlanCreateRequest, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    plan = TestPlanService(db).create_plan(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=_plan_data(plan), message="测试计划创建成功")


@router.post("/import", summary="导入测试计划")
def import_plans(project_id: int, payload: TestPlanImportRequest | list[TestPlanCreateRequest], db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    payloads = payload.plans if isinstance(payload, TestPlanImportRequest) else payload
    plans = TestPlanService(db).import_plans(project_id=project_id, payloads=payloads, current_user=current_user)
    return success(data=[_plan_data(plan) for plan in plans], message="测试计划导入成功")


@router.get("/export", summary="导出测试计划")
def export_plans(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    plans = TestPlanService(db).export_plans(project_id=project_id, current_user=current_user)
    return success(data={"version": "1.0", "plans": [_plan_data(plan) for plan in plans]})


@router.get("/schedule", summary="查询计划调度实例")
def list_schedule(
    project_id: int,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start = start_at or datetime.utcnow()
    end = end_at or start + timedelta(days=14)
    items = TestPlanService(db).list_schedule(
        project_id=project_id, current_user=current_user, start_at=start, end_at=end,
    )
    return success(data={"items": items})


@router.get("/{plan_id}", summary="查询测试计划详情")
def get_plan(project_id: int, plan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success(data=_plan_data(TestPlanService(db).get_plan(project_id=project_id, plan_id=plan_id, current_user=current_user)))


@router.put("/{plan_id}", summary="更新测试计划")
def update_plan(project_id: int, plan_id: int, payload: TestPlanUpdateRequest, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    plan = TestPlanService(db).update_plan(project_id=project_id, plan_id=plan_id, payload=payload, current_user=current_user)
    return success(data=_plan_data(plan), message="测试计划更新成功")


@router.delete("/{plan_id}", summary="删除测试计划")
def delete_plan(project_id: int, plan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    plan = TestPlanService(db).delete_plan(project_id=project_id, plan_id=plan_id, current_user=current_user)
    return success(data=_plan_data(plan), message="测试计划删除成功")


@router.put("/{plan_id}/enabled", summary="启用或停用测试计划")
def set_plan_enabled(project_id: int, plan_id: int, payload: TestPlanEnabledRequest, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    plan = TestPlanService(db).set_enabled(
        project_id=project_id, plan_id=plan_id, enabled=payload.enabled, version=payload.version, current_user=current_user
    )
    return success(data=_plan_data(plan), message="测试计划状态已更新")


@router.post("/{plan_id}/execute", summary="手动执行测试计划")
def execute_plan(project_id: int, plan_id: int, payload: TestPlanExecuteRequest, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    run = TestPlanService(db).execute_plan(
        project_id=project_id, plan_id=plan_id, environment_id=payload.environment_id,
        idempotency_key=payload.idempotency_key, current_user=current_user,
    )
    return success(data=_run_data(run, include_results=True), message="测试计划执行完成")


@run_router.get("", summary="查询测试计划执行历史")
def list_runs(project_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=200),
              db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = TestPlanService(db).list_runs(project_id=project_id, current_user=current_user, page=page, page_size=page_size)
    result["items"] = [_run_data(run) for run in result["items"]]
    return success(data=result)


@run_router.delete("", summary="清空项目测试计划执行历史")
def clear_runs(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    count = TestPlanService(db).clear_runs(project_id=project_id, current_user=current_user)
    return success(data={"deleted_count": count}, message="测试计划执行历史已清空")


@run_router.get("/{run_id}", summary="查询测试计划运行详情")
def get_run(project_id: int, run_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    run = TestPlanService(db).get_run(project_id=project_id, run_id=run_id, current_user=current_user)
    return success(data=_run_data(run, include_results=True))


@run_router.delete("/{run_id}", summary="删除测试计划运行记录")
def delete_run(project_id: int, run_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    TestPlanService(db).delete_run(project_id=project_id, run_id=run_id, current_user=current_user)
    return success(message="测试计划运行记录已删除")
