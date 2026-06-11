from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cases = TestCaseService(db).list_cases(project_id=project_id, current_user=current_user)
    return success(data=[TestCaseRead.model_validate(item) for item in cases])


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


@router.post("/{test_case_id}/execute", summary="执行已保存测试用例")
def execute_saved_test_case(
    project_id: int,
    test_case_id: int,
    environment_id: int | None = Query(default=None, description="覆盖用例绑定环境"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = TestCaseService(db).execute_saved_case(
        project_id=project_id,
        test_case_id=test_case_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=TestCaseExecutionRead.model_validate(execution), message="测试用例执行完成")


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


@router.post("/batch-execute", summary="批量执行测试用例")
def batch_execute_test_cases(
    project_id: int,
    payload: BatchExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    executions = TestCaseService(db).batch_execute(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=[TestCaseExecutionRead.model_validate(item) for item in executions], message="批量执行完成")
