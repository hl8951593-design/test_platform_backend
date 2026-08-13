from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.database_connection import (
    DatabaseConnectionCreateRequest,
    DatabaseConnectionUpdateRequest,
)
from app.services.database_connection_service import DatabaseConnectionService


router = APIRouter(
    prefix="/projects/{project_id}/environments/{environment_id}/database-connections"
)


@router.get("", summary="查询环境数据库连接")
def list_database_connections(
    project_id: int,
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = DatabaseConnectionService(db).list_connections(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=items)


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建环境数据库连接")
def create_database_connection(
    project_id: int,
    environment_id: int,
    payload: DatabaseConnectionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = DatabaseConnectionService(db).create_connection(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=item, message="数据库连接创建成功")


@router.put("/{connection_id}", summary="更新环境数据库连接")
def update_database_connection(
    project_id: int,
    environment_id: int,
    connection_id: int,
    payload: DatabaseConnectionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = DatabaseConnectionService(db).update_connection(
        project_id=project_id,
        environment_id=environment_id,
        connection_id=connection_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=item, message="数据库连接更新成功")


@router.delete("/{connection_id}", summary="删除环境数据库连接")
def delete_database_connection(
    project_id: int,
    environment_id: int,
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    DatabaseConnectionService(db).delete_connection(
        project_id=project_id,
        environment_id=environment_id,
        connection_id=connection_id,
        current_user=current_user,
    )
    return success(message="数据库连接删除成功")


@router.post("/{connection_id}/test", summary="测试环境数据库连接")
def test_database_connection(
    project_id: int,
    environment_id: int,
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DatabaseConnectionService(db).test_connection(
        project_id=project_id,
        environment_id=environment_id,
        connection_id=connection_id,
        current_user=current_user,
    )
    return success(data=result, message="数据库连接测试完成")
