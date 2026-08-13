from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.execution_worker import execution_worker
from app.core.response import success
from app.models.user import User
from app.schemas.dashboard import CreateDashboardAIJobRequest, CreateDashboardRegressionRunRequest
from app.services.dashboard_ai_analysis_service import DashboardAIAnalysisService
from app.services.dashboard_asset_snapshot_service import DashboardAssetSnapshotService
from app.services.dashboard_regression_service import DashboardRegressionService
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/quality-overview", summary="工作台质量总览")
def get_quality_overview(
    project_id: int,
    environment_id: int | None = None,
    range_value: Annotated[str, Query(alias="range")] = "today",
    version: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = DashboardService(db).quality_overview(
        project_id=project_id,
        environment_id=environment_id,
        range_value=range_value,
        version=version,
        current_user=current_user,
    )
    return success(data=overview)


@router.get("/project-asset-trends", summary="查询项目测试资产趋势")
def get_project_asset_trends(
    project_id: int,
    environment_id: int | None = None,
    range_value: Annotated[str, Query(alias="range")] = "30d",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DashboardAssetSnapshotService(db).project_asset_trends(
        project_id=project_id,
        environment_id=environment_id,
        range_value=range_value,
        current_user=current_user,
    )
    return success(data=result)


@router.get("/activity-feed", summary="分页查询工作台活动明细")
def get_activity_feed(
    project_id: int,
    environment_id: int | None = None,
    resource_type: str | None = None,
    status_value: Annotated[str | None, Query(alias="status")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DashboardService(db).activity_feed(
        project_id=project_id,
        current_user=current_user,
        environment_id=environment_id,
        resource_type=resource_type,
        status_value=status_value,
        date_from=datetime.combine(date_from, time.min) if date_from else None,
        date_to=datetime.combine(date_to, time.max) if date_to else None,
        page=page,
        page_size=page_size,
    )
    return success(data=result)


def _reserve_dashboard_job():
    reservation = execution_worker.reserve(1)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return reservation


@router.post(
    "/ai-analysis-jobs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建异步工作台 AI 分析任务",
)
def create_ai_analysis_job(
    payload: CreateDashboardAIJobRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reservation = _reserve_dashboard_job()
    try:
        result = DashboardAIAnalysisService(db).create_job(payload=payload, current_user=current_user)
        reservation.submit_future(DashboardAIAnalysisService.execute_queued_job, result.job_id)
    finally:
        reservation.release_unused()
    return success(data=result, message="AI 分析任务已受理")


@router.get("/ai-analysis-jobs/{job_id}", summary="查询工作台 AI 分析任务")
def get_ai_analysis_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DashboardAIAnalysisService(db).get_job(job_id=job_id, current_user=current_user)
    return success(data=result)


@router.post(
    "/regression-runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建统一工作台回归任务",
)
def create_regression_run(
    payload: CreateDashboardRegressionRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reservation = _reserve_dashboard_job()
    try:
        result = DashboardRegressionService(db).create_run(payload=payload, current_user=current_user)
        reservation.submit_future(DashboardRegressionService.execute_queued_run, str(result.run_id))
    finally:
        reservation.release_unused()
    return success(data=result, message="回归任务已受理")


@router.get("/regression-runs/{run_id}", summary="查询统一工作台回归任务")
def get_regression_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DashboardRegressionService(db).get_run(run_id=run_id, current_user=current_user)
    return success(data=result)


@router.get("/insights/{insight_type}", summary="查询工作台洞察详情")
def get_insight_detail(
    insight_type: str,
    project_id: int,
    environment_id: int | None = None,
    range_value: Annotated[str, Query(alias="range")] = "7d",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DashboardService(db).insight_detail(
        insight_type=insight_type,
        project_id=project_id,
        current_user=current_user,
        environment_id=environment_id,
        range_value=range_value,
        page=page,
        page_size=page_size,
    )
    return success(data=result)
