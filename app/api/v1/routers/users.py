from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_admin
from app.core.response import success
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.admin import UserAdminUpdateRequest
from app.schemas.user import UserRead

router = APIRouter()


@router.put("/{user_id}/admin", summary="设置用户管理员权限")
def update_user_admin_status(
    user_id: int,
    payload: UserAdminUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    if user_id == current_admin.id and not payload.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能取消自己的管理员权限")

    user = UserRepository(db).set_admin(user_id=user_id, is_admin=payload.is_admin)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return success(data=UserRead.model_validate(user), message="用户管理员权限已更新")
