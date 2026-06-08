import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402


def set_admin(account: str, is_admin: bool) -> None:
    db = SessionLocal()
    try:
        repository = UserRepository(db)
        user = repository.get_by_account(account)
        if user is None:
            raise SystemExit(f"user not found: {account}")
        repository.set_admin(user_id=user.id, is_admin=is_admin)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set a user as admin by account.")
    parser.add_argument("account", help="User account")
    parser.add_argument("--unset", action="store_true", help="Remove admin permission")
    args = parser.parse_args()

    set_admin(args.account, is_admin=not args.unset)
    print("admin status updated")
