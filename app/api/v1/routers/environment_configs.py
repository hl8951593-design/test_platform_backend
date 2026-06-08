from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.project import (
    ProjectEnvironmentCreateRequest,
    ProjectEnvironmentDetailRead,
    ProjectEnvironmentVariableRead,
    ProjectEnvironmentVariableUpsertRequest,
    ProjectEnvironmentUpdateRequest,
    TestCaseEnvironmentBindRequest,
)
from app.services.project_service import ProjectService

router = APIRouter()


@router.get("", summary="查询项目环境配置列表")
def list_environment_configs(
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    configs = ProjectService(db).list_environment_configs(
        project_id=project_id,
        current_user=current_user,
    )
    return success(data=configs)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建项目环境配置")
def create_environment_config(
    payload: ProjectEnvironmentCreateRequest,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProjectService(db)
    environment = service.create_environment(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    config = service.get_environment_config(
        project_id=project_id,
        environment_id=environment.id,
        current_user=current_user,
    )
    return success(data=config, message="环境配置创建成功")


@router.get("/{environment_id}", summary="查询环境配置详情")
def get_environment_config(
    environment_id: int,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = ProjectService(db).get_environment_config(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=config)


@router.put("/{environment_id}", summary="更新环境配置")
def update_environment_config(
    environment_id: int,
    payload: ProjectEnvironmentUpdateRequest,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProjectService(db)
    service.update_environment(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    config = service.get_environment_config(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=config, message="环境配置更新成功")


@router.delete("/{environment_id}", summary="删除环境配置")
def delete_environment_config(
    environment_id: int,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    environment = ProjectService(db).delete_environment(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(
        data=ProjectEnvironmentDetailRead.model_validate(environment),
        message="环境配置删除成功",
    )


@router.get("/{environment_id}/variables", summary="查询环境配置变量")
def list_environment_config_variables(
    environment_id: int,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    variables = ProjectService(db).list_environment_variables(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=[ProjectEnvironmentVariableRead.model_validate(variable) for variable in variables])


@router.post("/{environment_id}/variables", summary="新增或更新环境配置变量")
def upsert_environment_config_variable(
    environment_id: int,
    payload: ProjectEnvironmentVariableUpsertRequest,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    variable = ProjectService(db).upsert_environment_variable(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(
        data=ProjectEnvironmentVariableRead.model_validate(variable),
        message="环境配置变量保存成功",
    )


@router.delete("/{environment_id}/variables/{variable_id}", summary="删除环境配置变量")
def delete_environment_config_variable(
    environment_id: int,
    variable_id: int,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ProjectService(db).delete_environment_variable(
        project_id=project_id,
        environment_id=environment_id,
        variable_id=variable_id,
        current_user=current_user,
    )
    return success(message="环境配置变量删除成功")


@router.get("/{environment_id}/test-cases", summary="查询绑定此环境配置的用例")
def list_environment_config_test_cases(
    environment_id: int,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    test_cases = ProjectService(db).list_environment_test_cases(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=test_cases)


@router.put("/test-cases/{test_case_id}/environment", summary="绑定或解绑用例环境配置")
def bind_test_case_environment(
    test_case_id: int,
    payload: TestCaseEnvironmentBindRequest,
    project_id: int = Query(description="所属项目 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    test_case = ProjectService(db).bind_test_case_environment(
        project_id=project_id,
        test_case_id=test_case_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=test_case, message="用例环境配置已更新")
