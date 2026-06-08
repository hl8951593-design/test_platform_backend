from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.permissions import ProjectPermission
from app.core.response import success
from app.models.user import User
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectEnvironmentCreateRequest,
    ProjectEnvironmentRead,
    ProjectEnvironmentVariableRead,
    ProjectEnvironmentVariableUpsertRequest,
    ProjectEnvironmentUpdateRequest,
    ProjectMemberGrantRequest,
    ProjectRead,
    ProjectUpdateRequest,
)
from app.services.project_service import ProjectService

router = APIRouter()


@router.get("/permissions", summary="查询项目权限编码")
def list_project_permissions():
    permissions = [{"code": permission.value, "name": permission.name} for permission in ProjectPermission]
    return success(data=permissions)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建项目")
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = ProjectService(db).create(payload, current_user)
    return success(data=ProjectRead.model_validate(project), message="项目创建成功")


@router.get("", summary="查询当前用户可见项目列表")
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    projects = ProjectService(db).list_visible_projects(current_user)
    return success(data=[ProjectRead.model_validate(project) for project in projects])


@router.get("/{project_id}", summary="查询项目详情")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = ProjectService(db).get_visible_project(project_id, current_user)
    return success(data=ProjectRead.model_validate(project))


@router.put("/{project_id}", summary="更新项目")
def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = ProjectService(db).update(project_id, payload, current_user)
    return success(data=ProjectRead.model_validate(project), message="项目更新成功")


@router.delete("/{project_id}", summary="删除项目")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = ProjectService(db).delete(project_id, current_user)
    return success(data=ProjectRead.model_validate(project), message="项目删除成功")


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED, summary="添加普通测试人员权限")
def grant_normal_tester_permissions(
    project_id: int,
    payload: ProjectMemberGrantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = ProjectService(db).grant_normal_tester_permissions(
        project_id=project_id,
        user_id=payload.user_id,
        permission_codes=payload.permission_codes,
        current_user=current_user,
    )
    return success(data=member, message="项目成员权限已更新")


@router.get("/{project_id}/environments", summary="查询项目环境列表")
def list_project_environments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    environments = ProjectService(db).list_environments(project_id, current_user)
    return success(data=[ProjectEnvironmentRead.model_validate(environment) for environment in environments])


@router.post("/{project_id}/environments", status_code=status.HTTP_201_CREATED, summary="创建项目环境")
def create_project_environment(
    project_id: int,
    payload: ProjectEnvironmentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    environment = ProjectService(db).create_environment(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=ProjectEnvironmentRead.model_validate(environment), message="项目环境创建成功")


@router.put("/{project_id}/environments/{environment_id}", summary="更新项目环境")
def update_project_environment(
    project_id: int,
    environment_id: int,
    payload: ProjectEnvironmentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    environment = ProjectService(db).update_environment(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=ProjectEnvironmentRead.model_validate(environment), message="项目环境更新成功")


@router.delete("/{project_id}/environments/{environment_id}", summary="删除项目环境")
def delete_project_environment(
    project_id: int,
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    environment = ProjectService(db).delete_environment(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=ProjectEnvironmentRead.model_validate(environment), message="项目环境删除成功")


@router.get("/{project_id}/environments/{environment_id}/variables", summary="查询项目环境变量")
def list_project_environment_variables(
    project_id: int,
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    variables = ProjectService(db).list_environment_variables(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=[ProjectEnvironmentVariableRead.model_validate(variable) for variable in variables])


@router.post("/{project_id}/environments/{environment_id}/variables", summary="新增或更新项目环境变量")
def upsert_project_environment_variable(
    project_id: int,
    environment_id: int,
    payload: ProjectEnvironmentVariableUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    variable = ProjectService(db).upsert_environment_variable(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=ProjectEnvironmentVariableRead.model_validate(variable), message="项目环境变量已保存")


@router.delete("/{project_id}/environments/{environment_id}/variables/{variable_id}", summary="删除项目环境变量")
def delete_project_environment_variable(
    project_id: int,
    environment_id: int,
    variable_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ProjectService(db).delete_environment_variable(
        project_id=project_id,
        environment_id=environment_id,
        variable_id=variable_id,
        current_user=current_user,
    )
    return success(message="项目环境变量已删除")
