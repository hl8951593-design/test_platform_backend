from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_account(self, account: str) -> User | None:
        statement = select(User).where(User.account == account)
        return self.db.scalar(statement)

    def get_by_account_phone_or_email(self, account: str, phone: str, email: str) -> User | None:
        statement = select(User).where(
            or_(User.account == account, User.phone == phone, User.email == email)
        )
        return self.db.scalar(statement)

    def create(
        self,
        *,
        username: str,
        avatar: str | None,
        account: str,
        password_hash: str,
        phone: str,
        email: str,
    ) -> User:
        user = User(
            username=username,
            avatar=avatar,
            account=account,
            password_hash=password_hash,
            phone=phone,
            email=email,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_admin(self, *, user_id: int, is_admin: bool) -> User | None:
        user = self.get_by_id(user_id)
        if user is None:
            return None
        user.is_admin = is_admin
        self.db.commit()
        self.db.refresh(user)
        return user
