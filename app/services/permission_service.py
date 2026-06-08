from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import NORMAL_TESTER_GRANTABLE_PERMISSIONS
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.repositories.project_repository import ProjectRepository


class PermissionService:
    def __init__(self, db: Session):
        self.db = db
        self.project_repository = ProjectRepository(db)

    def is_admin(self, user: User) -> bool:
        return bool(user.is_admin)

    def is_project_creator(self, user: User, project: Project) -> bool:
        return project.created_by_id == user.id

    def get_project_or_404(self, project_id: int) -> Project:
        project = self.project_repository.get_by_id(project_id)
        if project is None or project.is_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return project

    def can_access_project(self, user: User, project_id: int) -> bool:
        project = self.get_project_or_404(project_id)
        if self.is_admin(user) or self.is_project_creator(user, project):
            return True
        return self.project_repository.get_member(project_id=project_id, user_id=user.id) is not None

    def require_project_access(self, user: User, project_id: int) -> Project:
        project = self.get_project_or_404(project_id)
        if self.is_admin(user) or self.is_project_creator(user, project):
            return project
        if self.project_repository.get_member(project_id=project_id, user_id=user.id) is not None:
            return project
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无项目访问权限")

    def has_project_permission(self, user: User, project_id: int, permission_code: str) -> bool:
        project = self.get_project_or_404(project_id)
        if self.is_admin(user) or self.is_project_creator(user, project):
            return True
        permission_codes = self.project_repository.get_member_permission_codes(
            project_id=project_id,
            user_id=user.id,
        )
        return permission_code in permission_codes

    def require_project_permission(self, user: User, project_id: int, permission_code: str) -> Project:
        project = self.get_project_or_404(project_id)
        if self.is_admin(user) or self.is_project_creator(user, project):
            return project

        permission_codes = self.project_repository.get_member_permission_codes(
            project_id=project_id,
            user_id=user.id,
        )
        if permission_code in permission_codes:
            return project
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无功能操作权限")

    def require_can_grant_member_permissions(self, operator: User, project_id: int) -> Project:
        project = self.get_project_or_404(project_id)
        if self.is_admin(operator) or self.is_project_creator(operator, project):
            return project
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无成员授权权限")

    def require_project_creator_or_admin(self, user: User, project_id: int) -> Project:
        project = self.get_project_or_404(project_id)
        if self.is_admin(user) or self.is_project_creator(user, project):
            return project
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要项目创建者或管理员权限")

    def add_normal_tester(
        self,
        *,
        operator: User,
        project_id: int,
        user_id: int,
        permission_codes: set[str],
    ) -> ProjectMember:
        self.require_can_grant_member_permissions(operator, project_id)
        invalid_permissions = permission_codes - NORMAL_TESTER_GRANTABLE_PERMISSIONS
        if invalid_permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效权限编码: {', '.join(sorted(invalid_permissions))}",
            )

        member = self.project_repository.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            member = self.project_repository.add_member(
                project_id=project_id,
                user_id=user_id,
                added_by_id=operator.id,
            )
        self.project_repository.replace_member_permissions(
            member_id=member.id,
            permission_codes=permission_codes,
        )
        return member
