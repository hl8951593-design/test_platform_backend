from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database_connection import (
    DatabaseActionExecution,
    ProjectDatabaseConnection,
)


class DatabaseConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_connections(
        self, *, project_id: int, environment_id: int
    ) -> list[ProjectDatabaseConnection]:
        return list(
            self.db.scalars(
                select(ProjectDatabaseConnection)
                .where(
                    ProjectDatabaseConnection.project_id == project_id,
                    ProjectDatabaseConnection.environment_id == environment_id,
                    ProjectDatabaseConnection.is_deleted.is_(False),
                )
                .order_by(
                    ProjectDatabaseConnection.name.asc(),
                    ProjectDatabaseConnection.id.asc(),
                )
            ).all()
        )

    def get_connection(
        self,
        *,
        project_id: int,
        environment_id: int,
        connection_id: int,
        include_deleted: bool = False,
    ) -> ProjectDatabaseConnection | None:
        filters = [
            ProjectDatabaseConnection.id == connection_id,
            ProjectDatabaseConnection.project_id == project_id,
            ProjectDatabaseConnection.environment_id == environment_id,
        ]
        if not include_deleted:
            filters.append(ProjectDatabaseConnection.is_deleted.is_(False))
        return self.db.scalar(select(ProjectDatabaseConnection).where(*filters))

    def get_connection_by_key(
        self, *, project_id: int, environment_id: int, connection_key: str
    ) -> ProjectDatabaseConnection | None:
        return self.db.scalar(
            select(ProjectDatabaseConnection).where(
                ProjectDatabaseConnection.project_id == project_id,
                ProjectDatabaseConnection.environment_id == environment_id,
                ProjectDatabaseConnection.connection_key == connection_key,
                ProjectDatabaseConnection.is_deleted.is_(False),
            )
        )

    def add_connection(
        self, connection: ProjectDatabaseConnection
    ) -> ProjectDatabaseConnection:
        self.db.add(connection)
        self.db.commit()
        self.db.refresh(connection)
        return connection

    def save_connection(
        self, connection: ProjectDatabaseConnection
    ) -> ProjectDatabaseConnection:
        self.db.commit()
        self.db.refresh(connection)
        return connection

    def add_execution(self, execution: DatabaseActionExecution) -> DatabaseActionExecution:
        self.db.add(execution)
        self.db.flush()
        return execution
