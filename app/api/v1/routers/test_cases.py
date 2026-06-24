from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.config import settings
from app.core.execution_worker import execution_worker
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
    return success(message="测试用例删除成功")


def _submit_http_execution(execution_id: int) -> Future[None]:
    future = execution_worker.submit_future(
        TestCaseService.execute_queued_execution,
        execution_id,
    )
    if future is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return future


def _wait_for_http_execution(db: Session, execution) -> None:
    future = _submit_http_execution(execution.id)
    try:
        future.result(timeout=settings.EXECUTION_REQUEST_WAIT_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="测试用例执行超时，请稍后在执行中心查看结果",
        ) from exc
    db.refresh(execution)


@router.post(
    "/{test_case_id}/execute",
    status_code=status.HTTP_200_OK,
    summary="异步执行已保存测试用例",
)
def execute_saved_test_case(
    project_id: int,
    test_case_id: int,
    environment_id: int | None = Query(default=None, description="覆盖用例绑定环境"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = TestCaseService(db).enqueue_saved_case(
        project_id=project_id,
        test_case_id=test_case_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    _wait_for_http_execution(db, execution)
    return success(
        data=TestCaseExecutionRead.model_validate(execution),
        message="测试用例执行完成",
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
    return success(data=TestCaseExecutionRead.model_validate(execution), message="临时测试用例执行完成")


@router.post(
    "/batch-execute",
    status_code=status.HTTP_200_OK,
    summary="异步批量执行测试用例",
)
def batch_execute_test_cases(
    project_id: int,
    payload: BatchExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestCaseService(db)
    executions = [
        service.enqueue_saved_case(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=payload.environment_id,
            current_user=current_user,
        )
        for test_case_id in payload.test_case_ids
    ]
    futures = [_submit_http_execution(execution.id) for execution in executions]
    try:
        for future in futures:
            future.result(timeout=settings.EXECUTION_REQUEST_WAIT_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="批量测试用例执行超时，请稍后在执行中心查看结果",
        ) from exc
    for execution in executions:
        db.refresh(execution)
    return success(
        data=[TestCaseExecutionRead.model_validate(item) for item in executions],
        message="批量测试用例执行完成",
    )
