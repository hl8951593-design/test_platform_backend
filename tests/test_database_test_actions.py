import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.database_connection import (
    DatabaseActionExecution,
    ProjectDatabaseConnection,
)
from app.models.project import Project, ProjectEnvironment
from app.models.user import User
from app.schemas.database_connection import (
    DatabaseActionConfig,
    DatabaseConnectionCreateRequest,
)
from app.schemas.scenario import ScenarioActionRequest
from app.schemas.scenario import ScenarioCreateRequest
from app.services.database_action_service import (
    DatabaseActionResult,
    DatabaseActionExecutor,
    DatabaseTargetClient,
    validate_database_action,
)
from app.services.database_connection_service import DatabaseConnectionService
from app.services.scenario_service import ScenarioService


class DatabaseActionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            username="owner",
            account="database-owner",
            password_hash="hash",
            phone="18800000001",
            email="database-owner@example.com",
        )
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Database actions", created_by_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="test",
            base_url="https://test.example.com",
            created_by_id=self.user.id,
        )
        self.other_environment = ProjectEnvironment(
            project_id=self.project.id,
            name="stage",
            base_url="https://stage.example.com",
            created_by_id=self.user.id,
        )
        self.db.add_all([self.environment, self.other_environment])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_connection(
        self,
        *,
        environment: ProjectEnvironment | None = None,
        provider: str = "mysql",
        connection_key: str = "orders",
        allow_writes: bool = False,
    ) -> ProjectDatabaseConnection:
        environment = environment or self.environment
        username = None if provider == "mongodb" else "tester"
        payload = DatabaseConnectionCreateRequest(
            name=f"{provider} orders",
            connection_key=connection_key,
            provider=provider,
            host="db.example.com",
            database_name="orders",
            username=username,
            password="top-secret",
            allow_writes=allow_writes,
        )
        with patch.object(DatabaseConnectionService, "_validate_target_host"):
            result = DatabaseConnectionService(self.db).create_connection(
                project_id=self.project.id,
                environment_id=environment.id,
                payload=payload,
                current_user=self.user,
            )
        self.assertTrue(result.password_configured)
        self.assertFalse(hasattr(result, "password"))
        return self.db.get(ProjectDatabaseConnection, result.id)

    def test_connection_password_is_encrypted_and_response_is_masked(self):
        connection = self.create_connection(provider="postgresql")

        self.assertIsNotNone(connection.password_encrypted)
        self.assertTrue(connection.password_encrypted.startswith("enc:v1:"))
        self.assertNotIn("top-secret", connection.password_encrypted)

    def test_scenario_schema_accepts_database_actions(self):
        action = ScenarioActionRequest.model_validate(
            {
                "id": "DB-1",
                "kind": "database_query",
                "name": "查询订单",
                "config": {
                    "connection_key": "orders",
                    "sql": "SELECT status FROM orders WHERE id = :order_id",
                    "parameters": {"order_id": "{{order_id}}"},
                },
            }
        )

        self.assertEqual(action.kind, "database_query")

    def test_scenario_definition_freezes_connection_key_without_secret(self):
        connection = self.create_connection(provider="postgresql")
        from app.models.test_case import TestCase

        test_case = TestCase(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="Create order",
            method="POST",
            path="/orders",
            body_type="json",
            created_by_id=self.user.id,
        )
        self.db.add(test_case)
        self.db.commit()
        payload = ScenarioCreateRequest.model_validate(
            {
                "name": "Database scenario",
                "environment_id": self.environment.id,
                "nodes": [
                    {
                        "id": "NODE-1",
                        "name": "Create order",
                        "before_actions": [
                            {
                                "id": "DB-1",
                                "kind": "database_query",
                                "name": "Read tenant",
                                "config": {
                                    "connection_id": connection.id,
                                    "sql": "SELECT id FROM tenants WHERE code = :code",
                                    "parameters": {"code": "{{tenant_code}}"},
                                    "extractors": [
                                        {"name": "tenant_id", "path": "rows.0.id"}
                                    ],
                                    "_scenario_context": {
                                        "extractions": [
                                            {
                                                "id": "VAR-TENANT",
                                                "name": "tenant_id",
                                                "path": "rows.0.id",
                                            }
                                        ],
                                        "bindings": [],
                                    },
                                },
                            }
                        ],
                        "test_case": {
                            "id": "HTTP-1",
                            "kind": "api_case",
                            "reference_id": test_case.id,
                            "name": test_case.name,
                        },
                    }
                ],
            }
        )

        definition = ScenarioService(self.db)._validated_definition(
            self.project.id, payload
        )
        action = definition["nodes"][0]["before_actions"][0]
        self.assertEqual(action["config"]["connection_key"], "orders")
        self.assertEqual(
            action["config"]["_scenario_context"]["extractions"][0]["id"],
            "VAR-TENANT",
        )
        self.assertEqual(action["connection_snapshot"]["provider"], "postgresql")
        self.assertNotIn("password", str(definition).lower())

    def test_scenario_database_action_preserves_extracted_value_type(self):
        service = ScenarioService(self.db)
        database_result = DatabaseActionResult(
            execution_id=81,
            status="passed",
            runtime_output={"rows": [{"id": 9527}], "row_count": 1},
            stored_output={"rows": [{"id": 9527}], "row_count": 1},
            assertion_results=[],
            extracted_variables=[
                {
                    "extraction_id": "database:DB-1:order_id",
                    "name": "order_id",
                    "path": "rows.0.id",
                    "value": 9527,
                    "masked": False,
                }
            ],
            extracted_values={"order_id": 9527},
            attempt_history=[],
            error_message="",
            duration_ms=5,
            request_snapshot={"connection": {"connection_key": "orders"}},
        )
        variables: dict[str, object] = {}
        variable_sources: dict[str, dict] = {}
        with patch.object(
            service.database_action_executor,
            "execute",
            return_value=database_result,
        ):
            result = service._execute_step(
                project_id=self.project.id,
                environment_id=self.environment.id,
                step={
                    "id": "DB-1",
                    "kind": "database_query",
                    "name": "Read order",
                    "config": {
                        "connection_key": "orders",
                        "sql": "SELECT id FROM orders WHERE id = :id",
                        "parameters": {"id": 9527},
                    },
                },
                step_index=1,
                variable_step_index=1,
                variables=variables,
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources=variable_sources,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(variables["order_id"], 9527)
        self.assertEqual(variables["step_1"]["rows"][0]["id"], 9527)

    def test_query_assertion_extraction_and_environment_key_resolution(self):
        original = self.create_connection(environment=self.environment)
        selected = self.create_connection(environment=self.other_environment)
        executor = DatabaseActionExecutor(self.db)
        output = {
            "columns": ["id", "status"],
            "rows": [{"id": 9527, "status": "PAID"}],
            "row_count": 1,
            "scalar": 9527,
            "truncated": False,
        }
        with (
            patch.object(DatabaseConnectionService, "_validate_target_host"),
            patch.object(DatabaseTargetClient, "query", return_value=output),
        ):
            result = executor.execute(
                project_id=self.project.id,
                environment_id=self.other_environment.id,
                scenario_run_id=None,
                step_id="DB-QUERY-1",
                kind="database_query",
                raw_config={
                    "connection_id": original.id,
                    "connection_key": "orders",
                    "sql": "SELECT id, status FROM orders WHERE id = :id",
                    "parameters": {"id": 9527},
                    "assertions": [
                        {"type": "row_count", "operator": "eq", "expected": 1},
                        {
                            "type": "value",
                            "path": "rows.0.status",
                            "operator": "eq",
                            "expected": "PAID",
                        },
                    ],
                    "extractors": [
                        {"name": "order_id", "path": "rows.0.id"}
                    ],
                },
                current_user=self.user,
            )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.extracted_values, {"order_id": 9527})
        self.assertTrue(all(item["passed"] for item in result.assertion_results))
        audit = self.db.get(DatabaseActionExecution, result.execution_id)
        self.assertEqual(audit.connection_id, selected.id)
        self.assertEqual(audit.status, "passed")

    def test_database_write_requires_connection_opt_in(self):
        connection = self.create_connection(allow_writes=False)

        with self.assertRaisesRegex(ValueError, "未开启写操作"):
            DatabaseActionExecutor(self.db).execute(
                project_id=self.project.id,
                environment_id=self.environment.id,
                scenario_run_id=None,
                step_id="DB-WRITE-1",
                kind="database_execute",
                raw_config={
                    "connection_id": connection.id,
                    "sql": "UPDATE orders SET status = :status WHERE id = :id",
                    "parameters": {"status": "PAID", "id": 1},
                },
                current_user=self.user,
            )

    def test_mongodb_rejects_server_side_javascript(self):
        connection = self.create_connection(provider="mongodb")
        config = DatabaseActionConfig.model_validate(
            {
                "connection_id": connection.id,
                "collection": "orders",
                "operation": "find",
                "filter": {"$where": "sleep(1000)"},
            }
        )

        with self.assertRaisesRegex(ValueError, "不允许使用"):
            validate_database_action(connection, "database_query", config)

    def test_connection_keys_are_unique_per_environment(self):
        first = self.create_connection()
        second = self.create_connection(environment=self.other_environment)

        self.assertNotEqual(first.id, second.id)
        keys = list(
            self.db.scalars(
                select(ProjectDatabaseConnection.connection_key).order_by(
                    ProjectDatabaseConnection.id
                )
            ).all()
        )
        self.assertEqual(keys, ["orders", "orders"])


if __name__ == "__main__":
    unittest.main()
