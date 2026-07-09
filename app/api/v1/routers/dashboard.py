from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
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
