import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app import models  # noqa: F401, E402


def sync_permission_schema() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "users" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "is_admin" not in user_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN is_admin BOOL NOT NULL DEFAULT 0 COMMENT '是否管理员'"
                    )
                )

    if "test_cases" in table_names:
        test_case_columns = {column["name"] for column in inspector.get_columns("test_cases")}
        if "body_type" not in test_case_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE test_cases "
                        "ADD COLUMN body_type VARCHAR(32) NOT NULL DEFAULT 'json' COMMENT '请求体格式'"
                    )
                )

    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    sync_permission_schema()
    print("permission schema synced")
