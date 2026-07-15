import importlib
import unittest
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.system_test_case import SystemTestCase
from app.models.test_case import TestCase
from app.models.user import User


def _methods_by_path(router) -> dict[str, set[str]]:
    methods: dict[str, set[str]] = {}
    for route in router.routes:
        if hasattr(route, "methods"):
            methods.setdefault(route.path, set()).update(route.methods or ())
    return methods


class SystemTestCasePersistenceTests(unittest.TestCase):
    def test_models_define_project_scoped_tables_and_constraints(self):
        from app.models.system_test_case import (
            SystemCaseApiRelation,
            SystemTestCase,
        )

        self.assertEqual(SystemTestCase.__tablename__, "system_test_cases")
        self.assertEqual(
            SystemCaseApiRelation.__tablename__,
            "system_case_api_relations",
        )

        case_columns = SystemTestCase.__table__.columns
        relation_columns = SystemCaseApiRelation.__table__.columns
        for column_name in (
            "project_id",
            "case_code",
            "title",
            "business_module",
            "test_objective",
            "priority",
            "status",
            "tags",
            "ai_generated",
            "created_by_id",
        ):
            self.assertIn(column_name, case_columns)
        for column_name in (
            "project_id",
            "system_case_id",
            "api_case_id",
            "relation_type",
            "confidence",
            "sort_order",
        ):
            self.assertIn(column_name, relation_columns)

        index_columns = {
            index.name: tuple(column.name for column in index.columns)
            for index in SystemTestCase.__table__.indexes
        }
        self.assertEqual(
            index_columns["ix_system_test_cases_project_updated_id"],
            ("project_id", "updated_at", "id"),
        )
        self.assertEqual(
            index_columns["ix_system_test_cases_project_status_priority"],
            ("project_id", "status", "priority"),
        )

        unique_constraints = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in SystemCaseApiRelation.__table__.constraints
            if constraint.name
        }
        self.assertEqual(
            unique_constraints["uq_system_case_api_relations_case_api"],
            ("system_case_id", "api_case_id"),
        )

    def test_migration_is_chained_after_current_head(self):
        migration = importlib.import_module(
            "migrations.versions.0039_system_test_cases"
        )

        self.assertEqual(migration.revision, "0039_system_test_cases")
        self.assertEqual(
            migration.down_revision,
            "0038_non_agent_query_performance_indexes",
        )


class SystemTestCaseRouteTests(unittest.TestCase):
    def test_first_stage_routes_are_registered(self):
        from app.api.v1.api import api_router

        methods = _methods_by_path(api_router)

        self.assertEqual(
            {"GET", "POST"},
            methods["/projects/{project_id}/system-test-cases"],
        )
        self.assertEqual(
            {"POST"},
            methods["/projects/{project_id}/system-test-cases/batch-delete"],
        )
        self.assertEqual(
            {"GET"},
            methods["/projects/{project_id}/system-test-cases/api-candidates"],
        )
        self.assertEqual(
            {"GET"},
            methods["/projects/{project_id}/system-test-cases/statistics"],
        )
        self.assertEqual(
            {"GET", "PUT", "DELETE"},
            methods["/system-test-cases/{system_case_id}"],
        )
        self.assertEqual(
            {"POST"},
            methods["/system-test-cases/{system_case_id}/duplicate"],
        )
        self.assertEqual(
            {"GET", "PUT"},
            methods["/system-test-cases/{system_case_id}/relations"],
        )


class SystemTestCaseServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self.user = User(
            id=1,
            username="admin",
            account="admin",
            password_hash="hash",
            phone="10000000000",
            email="admin@example.com",
            is_admin=True,
        )
        self.other_user = User(
            id=2,
            username="other",
            account="other",
            password_hash="hash",
            phone="10000000001",
            email="other@example.com",
            is_admin=True,
        )
        self.project = Project(id=10, name="Project A", created_by_id=1)
        self.other_project = Project(id=11, name="Project B", created_by_id=2)
        self.environment = ProjectEnvironment(
            id=20,
            project_id=10,
            name="test",
            base_url="https://example.com",
            created_by_id=1,
        )
        self.db.add_all([self.user, self.other_user, self.project, self.other_project, self.environment])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _create_api_case(self, *, case_id: int, project_id: int, name: str) -> TestCase:
        api_case = TestCase(
            id=case_id,
            project_id=project_id,
            environment_id=20 if project_id == 10 else None,
            name=name,
            description=None,
            method="POST",
            path="/login",
            headers=None,
            query_params=None,
            body_type="json",
            body=None,
            assertions=[{"type": "status_code", "expected": 200}],
            extractors=[],
            retry_policy={},
            created_by_id=1 if project_id == 10 else 2,
            last_execution_status="passed",
            last_executed_at=datetime(2026, 7, 11, 9, 0, 0),
        )
        self.db.add(api_case)
        self.db.commit()
        return api_case

    def test_create_and_list_cases_are_project_scoped(self):
        from app.schemas.system_test_case import SystemTestCaseCreateRequest
        from app.services.system_test_case_service import SystemTestCaseService

        service = SystemTestCaseService(self.db)
        created = service.create_case(
            project_id=10,
            payload=SystemTestCaseCreateRequest(
                title="用户登录成功",
                businessModule="登录",
                testObjective="验证账号密码登录",
                priority="P0",
                status="enabled",
                tags=["smoke"],
                createdBy="qa",
            ),
            current_user=self.user,
        )
        self.db.add(
            SystemTestCase(
                project_id=11,
                case_code="STC-000001",
                title="其他项目",
                business_module="登录",
                test_objective="不应出现在项目 10",
                priority="P1",
                status="draft",
                tags=[],
                ai_generated=False,
                created_by_id=2,
            )
        )
        self.db.commit()

        result = service.list_cases(
            project_id=10,
            current_user=self.user,
            keyword="登录",
            status_filter=None,
            priority=None,
            relation_status=None,
            page=1,
            page_size=20,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], str(created["id"]))
        self.assertEqual(result["items"][0]["projectId"], "10")
        self.assertEqual(result["items"][0]["projectName"], "Project A")
        self.assertEqual(result["items"][0]["caseCode"], "STC-000001")
        self.assertEqual(result["items"][0]["relationStatus"], "unlinked")
        self.assertEqual(result["items"][0]["linkedApiCaseCount"], 0)

    def test_relations_reject_api_cases_from_another_project(self):
        from app.schemas.system_test_case import (
            SystemCaseApiRelationInput,
            SystemCaseApiRelationsReplaceRequest,
            SystemTestCaseCreateRequest,
        )
        from app.services.system_test_case_service import SystemTestCaseService

        service = SystemTestCaseService(self.db)
        created = service.create_case(
            project_id=10,
            payload=SystemTestCaseCreateRequest(
                title="用户登录成功",
                businessModule="登录",
                testObjective="验证账号密码登录",
                createdBy="qa",
            ),
            current_user=self.user,
        )
        self._create_api_case(case_id=101, project_id=11, name="Other API")

        with self.assertRaises(HTTPException) as context:
            service.replace_relations(
                system_case_id=int(created["id"]),
                payload=SystemCaseApiRelationsReplaceRequest(
                    relations=[
                        SystemCaseApiRelationInput(
                            apiCaseId="101",
                            relationType="manual",
                            sortOrder=1,
                        )
                    ]
                ),
                current_user=self.user,
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_statistics_count_all_project_cases_and_relation_coverage(self):
        from app.schemas.system_test_case import (
            SystemCaseApiRelationInput,
            SystemCaseApiRelationsReplaceRequest,
            SystemTestCaseCreateRequest,
        )
        from app.services.system_test_case_service import SystemTestCaseService

        service = SystemTestCaseService(self.db)
        first = service.create_case(
            project_id=10,
            payload=SystemTestCaseCreateRequest(
                title="登录成功",
                businessModule="登录",
                testObjective="成功路径",
                aiGenerated=True,
                createdBy="qa",
            ),
            current_user=self.user,
        )
        service.create_case(
            project_id=10,
            payload=SystemTestCaseCreateRequest(
                title="登录失败",
                businessModule="登录",
                testObjective="异常路径",
                createdBy="qa",
            ),
            current_user=self.user,
        )
        self._create_api_case(case_id=100, project_id=10, name="Login API")
        service.replace_relations(
            system_case_id=int(first["id"]),
            payload=SystemCaseApiRelationsReplaceRequest(
                relations=[
                    SystemCaseApiRelationInput(
                        apiCaseId="100",
                        relationType="direct",
                        sortOrder=1,
                    )
                ]
            ),
            current_user=self.user,
        )

        stats = service.statistics(project_id=10, current_user=self.user)

        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["linkedApiCaseCount"], 1)
        self.assertEqual(stats["unlinkedSystemCaseCount"], 1)
        self.assertEqual(stats["aiGeneratedCount"], 1)
        self.assertEqual(stats["apiRelationCoverageRate"], 50)

    def test_api_candidates_project_filters_and_maps_frontend_fields(self):
        from app.services.system_test_case_service import SystemTestCaseService

        service = SystemTestCaseService(self.db)
        self._create_api_case(case_id=100, project_id=10, name="Login API")
        self._create_api_case(case_id=101, project_id=11, name="Other API")

        items = service.list_api_candidates(
            project_id=10,
            current_user=self.user,
            keyword="login",
            method="POST",
            environment="test",
            execution_status="passed",
            tag=None,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "100")
        self.assertEqual(items[0]["projectId"], "10")
        self.assertEqual(items[0]["name"], "Login API")
        self.assertEqual(items[0]["method"], "POST")
        self.assertEqual(items[0]["path"], "/login")
        self.assertEqual(items[0]["environment"], "test")
        self.assertEqual(items[0]["executionStatus"], "passed")
        self.assertEqual(items[0]["assertionCount"], 1)

    def test_update_duplicate_batch_delete_and_relations_return_frontend_contract(self):
        from app.schemas.system_test_case import (
            SystemCaseApiRelationInput,
            SystemCaseApiRelationsReplaceRequest,
            SystemTestCaseBatchDeleteRequest,
            SystemTestCaseCreateRequest,
            SystemTestCaseUpdateRequest,
        )
        from app.services.system_test_case_service import SystemTestCaseService

        service = SystemTestCaseService(self.db)
        created = service.create_case(
            project_id=10,
            payload=SystemTestCaseCreateRequest(
                title="登录成功",
                businessModule="登录",
                testObjective="成功路径",
                createdBy="qa",
            ),
            current_user=self.user,
        )
        updated = service.update_case(
            system_case_id=int(created["id"]),
            payload=SystemTestCaseUpdateRequest(
                title="登录成功更新",
                priority="P0",
                tags=["smoke", "login"],
            ),
            current_user=self.user,
        )
        self.assertEqual(updated["title"], "登录成功更新")
        self.assertEqual(updated["priority"], "P0")
        self.assertEqual(updated["tags"], ["smoke", "login"])

        self._create_api_case(case_id=100, project_id=10, name="Login API")
        relation_result = service.replace_relations(
            system_case_id=int(created["id"]),
            payload=SystemCaseApiRelationsReplaceRequest(
                relations=[
                    SystemCaseApiRelationInput(
                        apiCaseId="100",
                        relationType="manual",
                        confidence=0.8,
                        sortOrder=2,
                    )
                ]
            ),
            current_user=self.user,
        )
        self.assertEqual(relation_result["relations"][0]["apiCaseId"], "100")
        self.assertEqual(relation_result["systemCase"]["relationStatus"], "linked")
        self.assertEqual(relation_result["systemCase"]["linkedApiCaseIds"], ["100"])

        duplicated = service.duplicate_case(
            system_case_id=int(created["id"]),
            current_user=self.user,
        )
        self.assertNotEqual(duplicated["id"], created["id"])
        self.assertEqual(duplicated["status"], "draft")
        self.assertEqual(duplicated["caseCode"], "STC-000002")

        result = service.batch_delete(
            project_id=10,
            payload=SystemTestCaseBatchDeleteRequest(ids=[created["id"], duplicated["id"], "999"]),
            current_user=self.user,
        )
        self.assertEqual(result["deletedCount"], 2)


if __name__ == "__main__":
    unittest.main()
