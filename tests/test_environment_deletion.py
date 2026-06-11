import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectEnvironmentCreateRequest
from app.services.project_service import ProjectService


class EnvironmentNameReuseTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        user = User(
            username="owner",
            account="owner",
            password_hash="hash",
            phone="10000000000",
            email="owner@example.com",
        )
        self.db.add(user)
        self.db.flush()
        project = Project(name="Project", created_by_id=user.id)
        self.db.add(project)
        self.db.commit()
        self.user_id = user.id
        self.project_id = project.id

    def tearDown(self):
        self.db.close()

    def test_create_purges_legacy_soft_deleted_environment(self):
        old_environment = ProjectEnvironment(
            project_id=self.project_id,
            name="test",
            base_url="https://old.example.com",
            is_deleted=True,
            created_by_id=self.user_id,
        )
        self.db.add(old_environment)
        self.db.commit()

        created = ProjectRepository(self.db).create_environment(
            project_id=self.project_id,
            name="test",
            base_url="https://new.example.com",
            description=None,
            is_default=True,
            created_by_id=self.user_id,
        )

        self.assertEqual(created.name, "test")
        self.assertTrue(created.is_default)
        matching = list(self.db.scalars(
            select(ProjectEnvironment).where(
                ProjectEnvironment.project_id == self.project_id,
                ProjectEnvironment.name == "test",
            )
        ).all())
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].base_url, "https://new.example.com")
        self.assertEqual(
            self.db.scalar(
                select(func.count())
                .select_from(ProjectEnvironment)
                .where(
                    ProjectEnvironment.project_id == self.project_id,
                    ProjectEnvironment.is_deleted.is_(True),
                )
            ),
            0,
        )

    def test_delete_physically_removes_environment_and_releases_name(self):
        repository = ProjectRepository(self.db)
        environment = repository.create_environment(
            project_id=self.project_id,
            name="uat",
            base_url="https://uat.example.com",
            description=None,
            is_default=False,
            created_by_id=self.user_id,
        )

        environment_id = environment.id
        repository.delete_environment(environment)
        self.assertIsNone(self.db.get(ProjectEnvironment, environment_id))
        recreated = repository.create_environment(
            project_id=self.project_id,
            name="uat",
            base_url="https://new-uat.example.com",
            description=None,
            is_default=False,
            created_by_id=self.user_id,
        )

        self.assertEqual(recreated.name, "uat")


class EnvironmentConflictTests(unittest.TestCase):
    def test_active_duplicate_returns_conflict(self):
        db = MagicMock()
        service = ProjectService(db)
        service.permission_service.require_project_permission = MagicMock()
        service.project_repository = MagicMock()
        service.project_repository.create_environment.side_effect = IntegrityError(
            "statement",
            {},
            Exception("duplicate"),
        )
        payload = ProjectEnvironmentCreateRequest(
            name="test",
            base_url="https://example.com",
        )

        with self.assertRaises(HTTPException) as context:
            service.create_environment(
                project_id=1,
                payload=payload,
                current_user=SimpleNamespace(id=2),
            )

        self.assertEqual(context.exception.status_code, 409)
        db.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
