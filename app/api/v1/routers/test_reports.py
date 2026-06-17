from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.test_report import ReportSourceType
from app.services.test_report_service import TestReportService

router = APIRouter()


@router.get("", summary="List test reports")
def list_test_reports(
    project_id: int,
    source_type: ReportSourceType | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    environment_id: int | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report_page = TestReportService(db).list_reports(
        project_id=project_id,
        current_user=current_user,
        source_type=source_type,
        status_filter=status_filter,
        environment_id=environment_id,
        started_from=started_from,
        started_to=started_to,
        page=page,
        page_size=page_size,
    )
    return success(data=report_page)


@router.get("/trends", summary="Get daily test report trends")
def get_test_report_trends(
    project_id: int,
    source_type: ReportSourceType | None = None,
    environment_id: int | None = None,
    started_from: date | None = None,
    started_to: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trends = TestReportService(db).get_trends(
        project_id=project_id,
        current_user=current_user,
        source_type=source_type,
        environment_id=environment_id,
        started_from=started_from,
        started_to=started_to,
    )
    return success(data=trends)


@router.get("/{source_type}/{source_id}", summary="Get a structured test report")
def get_test_report(
    project_id: int,
    source_type: ReportSourceType,
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = TestReportService(db).get_report(
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        current_user=current_user,
    )
    return success(data=report)


@router.get(
    "/{source_type}/{source_id}/html",
    summary="Download a test report as HTML",
    response_class=HTMLResponse,
)
def download_test_report_html(
    project_id: int,
    source_type: ReportSourceType,
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestReportService(db)
    report = service.get_report(
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        current_user=current_user,
    )
    return HTMLResponse(
        content=service.render_html(report),
        headers={
            "Content-Disposition": (
                f'attachment; filename="test-report-{source_type}-{source_id}.html"'
            )
        },
    )
