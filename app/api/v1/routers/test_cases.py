from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.async_response import execution_started_payload
from app.core.execution_worker import ExecutionReservation, execution_worker
from app.core.read_response_cache import read_response_cache
from app.core.response import success
from app.models.user import User
from app.schemas.test_case import (
    BatchExecuteRequest,
    TestCaseCreateRequest,
    TestCaseExecutionRead,
    TestCaseRead,
    TestCaseUpdateRequest,
    UnsavedTestCaseExecuteRequest,
)
from app.services.test_case_service import TestCaseService

router = APIRouter()


@router.get("", summary="查询项目测试用例列表")
def list_test_cases(
    project_id: int,
    keyword: str | None = None,
    environment_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = (
        "test_cases",
        id(db.get_bind()),
        current_user.id,
        bool(current_user.is_admin),
        project_id,
        keyword or "",
        environment_id,
        page,
        page_size,
    )

    def build_response():
        result = TestCaseService(db).list_cases(
            project_id=project_id,
            current_user=current_user,
            keyword=keyword,
            environment_id=environment_id,
            page=page,
            page_size=page_size,
        )
        result["items"] = [
            TestCaseRead.model_validate(item) for item in result["items"]
        ]
        return success(data=result)

    return read_response_cache.get_or_set(cache_key, build_response)


@router.post("", status_code=status.HTTP_201_CREATED, summary="新增测试用例")
def create_test_case(
    project_id: int,
    payload: TestCaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    test_case = TestCaseService(db).create_case(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    read_response_cache.clear_prefix(("test_cases",))
    read_response_cache.clear_prefix(("projects",))
    read_response_cache.clear_prefix(("environment_configs",))
    return success(data=TestCaseRead.model_validate(test_case), message="测试用例创建成功")


@router.put("/{test_case_id}", summary="更新测试用例")
def update_test_case(
    project_id: int,
    test_case_id: int,
    payload: TestCaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    test_case = TestCaseService(db).update_case(
        project_id=project_id,
        test_case_id=test_case_id,
        payload=payload,
        current_user=current_user,
    )
    read_response_cache.clear_prefix(("test_cases",))
    read_response_cache.clear_prefix(("projects",))
    read_response_cache.clear_prefix(("environment_configs",))
    return success(data=TestCaseRead.model_validate(test_case), message="测试用例更新成功")


@router.delete("/{test_case_id}", summary="删除测试用例")
def delete_test_case(
    project_id: int,
    test_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    TestCaseService(db).delete_case(
        project_id=project_id,
        test_case_id=test_case_id,
        current_user=current_user,
    )
    read_response_cache.clear_prefix(("test_cases",))
    read_response_cache.clear_prefix(("projects",))
    read_response_cache.clear_prefix(("environment_configs",))
    return success(message="测试用例删除成功")


def _reserve_http_executions(count: int) -> ExecutionReservation:
    reservation = execution_worker.reserve(count)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return reservation


def _submit_http_execution(execution_id: int, reservation: ExecutionReservation | None = None):
    future = (
        reservation.submit_future(TestCaseService.execute_queued_execution, execution_id)
        if reservation is not None
        else execution_worker.submit_future(
            TestCaseService.execute_queued_execution,
            execution_id,
        )
    )
    if future is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return future


def _invalidate_http_execution_caches(_future=None) -> None:
    read_response_cache.clear_prefix(("test_cases",))
    read_response_cache.clear_prefix(("projects",))


@router.post(
    "/{test_case_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="异步执行已保存测试用例",
)
def execute_saved_test_case(
    project_id: int,
    test_case_id: int,
    environment_id: int | None = Query(default=None, description="覆盖用例绑定环境"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reservation = _reserve_http_executions(1)
    try:
        execution = TestCaseService(db).enqueue_saved_case(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            current_user=current_user,
        )
        future = _submit_http_execution(execution.id, reservation)
        future.add_done_callback(_invalidate_http_execution_caches)
    finally:
        reservation.release_unused()
    _invalidate_http_execution_caches()
    return success(
        data=execution_started_payload(
            TestCaseExecutionRead.model_validate(execution),
            execution_type="http",
            execution_id=execution.id,
            project_id=project_id,
        ),
        message="测试用例执行已受理",
    )


@router.post("/execute-unsaved", summary="执行未保存测试用例")
def execute_unsaved_test_case(
    project_id: int,
    payload: UnsavedTestCaseExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = TestCaseService(db).execute_unsaved_case(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    read_response_cache.clear_prefix(("projects",))
    return success(data=TestCaseExecutionRead.model_validate(execution), message="临时测试用例执行完成")


@router.post(
    "/batch-execute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="异步批量执行测试用例",
)
def batch_execute_test_cases(
    project_id: int,
    payload: BatchExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reservation = _reserve_http_executions(len(payload.test_case_ids))
    executions = []
    try:
        service = TestCaseService(db)
        service.validate_saved_case_batch(
            project_id=project_id,
            test_case_ids=payload.test_case_ids,
            environment_id=payload.environment_id,
            current_user=current_user,
        )
        for test_case_id in payload.test_case_ids:
            execution = service.enqueue_saved_case(
                project_id=project_id,
                test_case_id=test_case_id,
                environment_id=payload.environment_id,
                current_user=current_user,
            )
            executions.append(execution)
            future = _submit_http_execution(execution.id, reservation)
            future.add_done_callback(_invalidate_http_execution_caches)
    finally:
        reservation.release_unused()
    _invalidate_http_execution_caches()
    return success(
        data=[
            execution_started_payload(
                TestCaseExecutionRead.model_validate(item),
                execution_type="http",
                execution_id=item.id,
                project_id=project_id,
            )
            for item in executions
        ],
        message="批量测试用例执行已受理",
    )
