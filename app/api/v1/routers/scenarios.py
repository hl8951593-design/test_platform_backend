from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.scenario import (
    ScenarioCreateRequest,
    ScenarioExecuteRequest,
    ScenarioRead,
    ScenarioRunRead,
    ScenarioUpdateRequest,
)
from app.services.scenario_service import ScenarioService

router = APIRouter()
run_router = APIRouter()


@router.get("", summary="查询项目场景列表")
def list_scenarios(project_id: int, keyword: str | None = None,
                   page: int = Query(default=1, ge=1),
                   page_size: int = Query(default=20, ge=1, le=200),
                   db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    result = ScenarioService(db).list_scenarios(
        project_id=project_id, current_user=current_user, keyword=keyword,
        page=page, page_size=page_size,
    )
    result["items"] = [ScenarioRead.model_validate(item) for item in result["items"]]
    return success(data=result)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建场景")
def create_scenario(project_id: int, payload: ScenarioCreateRequest, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    item = ScenarioService(db).create_scenario(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=ScenarioRead.model_validate(item), message="场景创建成功")


@router.get("/{scenario_id}", summary="查询场景详情")
def get_scenario(project_id: int, scenario_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    item = ScenarioService(db).get_scenario(project_id=project_id, scenario_id=scenario_id, current_user=current_user)
    return success(data=ScenarioRead.model_validate(item))


@router.put("/{scenario_id}", summary="更新场景")
def update_scenario(project_id: int, scenario_id: int, payload: ScenarioUpdateRequest, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    item = ScenarioService(db).update_scenario(
        project_id=project_id, scenario_id=scenario_id, payload=payload, current_user=current_user
    )
    return success(data=ScenarioRead.model_validate(item), message="场景更新成功")


@router.delete("/{scenario_id}", summary="删除场景")
def delete_scenario(project_id: int, scenario_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    ScenarioService(db).delete_scenario(project_id=project_id, scenario_id=scenario_id, current_user=current_user)
    return success(message="场景删除成功")


@router.post("/{scenario_id}/execute", summary="执行场景")
def execute_scenario(project_id: int, scenario_id: int, payload: ScenarioExecuteRequest, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    runs = ScenarioService(db).execute_scenario(
        project_id=project_id, scenario_id=scenario_id, environment_id=payload.environment_id,
        dataset_ids=payload.dataset_ids, idempotency_key=payload.idempotency_key, current_user=current_user,
    )
    return success(data=[ScenarioRunRead.model_validate(run) for run in runs], message="场景执行完成")


@run_router.get("", summary="查询场景调试历史")
def list_scenario_runs(project_id: int, scenario_id: int | None = None, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    runs = ScenarioService(db).list_runs(project_id=project_id, scenario_id=scenario_id, current_user=current_user)
    return success(data=[ScenarioRunRead.model_validate(run) for run in runs])


@run_router.get("/{run_id}", summary="查询场景运行详情")
def get_scenario_run(project_id: int, run_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    run = ScenarioService(db).get_run(project_id=project_id, run_id=run_id, current_user=current_user)
    return success(data=ScenarioRunRead.model_validate(run))
