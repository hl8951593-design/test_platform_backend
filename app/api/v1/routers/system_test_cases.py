from fastapi import APIRouter, Depends, Query, status as http_status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.read_response_cache import read_response_cache
from app.core.response import success
from app.models.user import User
from app.schemas.system_test_case import (
    SystemCaseApiRelationsReplaceRequest,
    SystemTestCaseBatchDeleteRequest,
    SystemTestCaseCreateRequest,
    SystemTestCaseUpdateRequest,
)
from app.services.system_test_case_service import SystemTestCaseService

router = APIRouter()


@router.get("/projects/{project_id}/system-test-cases", summary="查询系统测试用例列表")
def list_system_test_cases(
    project_id: int,
    keyword: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    relation_status: str | None = Query(default=None, alias="relationStatus"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = SystemTestCaseService(db).list_cases(
        project_id=project_id,
        current_user=current_user,
        keyword=keyword,
        status_filter=status,
        priority=priority,
        relation_status=relation_status,
        page=page,
        page_size=page_size,
    )
    return success(data=result)


@router.post(
    "/projects/{project_id}/system-test-cases",
    status_code=http_status.HTTP_201_CREATED,
    summary="新增系统测试用例",
)
def create_system_test_case(
    project_id: int,
    payload: SystemTestCaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = SystemTestCaseService(db).create_case(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    _clear_system_case_cache()
    return success(data=item, message="系统测试用例创建成功")


@router.post("/projects/{project_id}/system-test-cases/batch-delete", summary="批量删除系统测试用例")
def batch_delete_system_test_cases(
    project_id: int,
    payload: SystemTestCaseBatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = SystemTestCaseService(db).batch_delete(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    _clear_system_case_cache()
    return success(data=result, message="系统测试用例批量删除成功")


@router.get("/projects/{project_id}/system-test-cases/api-candidates", summary="查询可关联 API 用例")
def list_system_test_case_api_candidates(
    project_id: int,
    keyword: str | None = None,
    method: str | None = None,
    environment: str | None = None,
    execution_status: str | None = Query(default=None, alias="executionStatus"),
    tag: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = SystemTestCaseService(db).list_api_candidates(
        project_id=project_id,
        current_user=current_user,
        keyword=keyword,
        method=method,
        environment=environment,
        execution_status=execution_status,
        tag=tag,
    )
    return success(data=items)


@router.get("/projects/{project_id}/system-test-cases/statistics", summary="系统测试用例统计")
def get_system_test_case_statistics(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = SystemTestCaseService(db).statistics(
        project_id=project_id,
        current_user=current_user,
    )
    return success(data=result)


@router.get("/system-test-cases/{system_case_id}", summary="查询系统测试用例详情")
def get_system_test_case(
    system_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = SystemTestCaseService(db).get_case(
        system_case_id=system_case_id,
        current_user=current_user,
    )
    return success(data=item)


@router.put("/system-test-cases/{system_case_id}", summary="更新系统测试用例")
def update_system_test_case(
    system_case_id: int,
    payload: SystemTestCaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = SystemTestCaseService(db).update_case(
        system_case_id=system_case_id,
        payload=payload,
        current_user=current_user,
    )
    _clear_system_case_cache()
    return success(data=item, message="系统测试用例更新成功")


@router.delete("/system-test-cases/{system_case_id}", summary="删除系统测试用例")
def delete_system_test_case(
    system_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    SystemTestCaseService(db).delete_case(
        system_case_id=system_case_id,
        current_user=current_user,
    )
    _clear_system_case_cache()
    return success(message="系统测试用例删除成功")


@router.post("/system-test-cases/{system_case_id}/duplicate", summary="复制系统测试用例")
def duplicate_system_test_case(
    system_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = SystemTestCaseService(db).duplicate_case(
        system_case_id=system_case_id,
        current_user=current_user,
    )
    _clear_system_case_cache()
    return success(data=item, message="系统测试用例复制成功")


@router.get("/system-test-cases/{system_case_id}/relations", summary="查询系统用例 API 关系")
def list_system_test_case_relations(
    system_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = SystemTestCaseService(db).list_relations(
        system_case_id=system_case_id,
        current_user=current_user,
    )
    return success(data=items)


@router.put("/system-test-cases/{system_case_id}/relations", summary="保存系统用例 API 关系")
def replace_system_test_case_relations(
    system_case_id: int,
    payload: SystemCaseApiRelationsReplaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = SystemTestCaseService(db).replace_relations(
        system_case_id=system_case_id,
        payload=payload,
        current_user=current_user,
    )
    _clear_system_case_cache()
    return success(data=result, message="系统用例关联关系保存成功")


def _clear_system_case_cache() -> None:
    read_response_cache.clear_prefix(("system_test_cases",))
    read_response_cache.clear_prefix(("projects",))
