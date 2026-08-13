from __future__ import annotations

import unittest
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.desktop_device_security import utc_now_naive
from app.db.base import Base
from app.models.desktop_device import DesktopDeviceProjectBinding
from app.models.execution_diagnostic import ExecutionRecordIndex, ExecutionStepDiagnostic
from app.models.execution_diagnostic import ExecutionPayloadArtifact
from app.models.project import Project, ProjectEnvironment
from app.models.ui_execution import UiExecution, UiExecutionEvent, UiRuntimePatch
from app.models.ui_execution_artifact import ExecutionArtifactUploadSession
from app.models.user import User
from app.schemas.desktop_device import DesktopDeviceRegisterRequest
from app.schemas.ui_execution import (
    UiExecutionClaimRequest,
    UiExecutionCommandAckRequest,
    UiExecutionCommandCreateRequest,
    UiExecutionCompleteRequest,
    UiExecutionCompleteSummary,
    UiExecutionCreateRequest,
    UiExecutionEventBatchRequest,
    UiExecutionEventItem,
    UiExecutionLeaseRequest,
    UiExecutionPatchRequestCreateRequest,
    UiExecutionRuntimePatchRequest,
    UiLocalRunImportRequest,
    UiLocalRunStepResult,
)
from app.schemas.ui_test_case import UiCaseDsl, UiTestCaseCreateRequest
from app.schemas.ui_execution_artifact import (
    UiArtifactFinalizeRequest,
    UiArtifactPresignRequest,
)
from app.repositories.ui_execution_repository import UiExecutionRepository
from app.services.desktop_device_service import DesktopDeviceService
from app.services.ui_execution_runtime_service import UiExecutionRuntimeService
from app.services.ui_execution_service import UiExecutionService
from app.services.ui_execution_artifact_service import UiExecutionArtifactService
from app.services.ui_local_run_import_service import UiLocalRunImportService
from app.services.ui_test_case_service import UiTestCaseService


def dsl() -> UiCaseDsl:
    return UiCaseDsl.model_validate(
        {
            "schema_version": "ui-case-v1",
            "steps": [
                {
                    "id": "step_001",
                    "name": "Open login",
                    "kind": "action",
                    "operation": "navigate",
                    "input_value": "testauto://smoke/login",
                }
            ],
        }
    )


class FakeObjectStorage:
    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.deleted: list[str] = []

    def presigned_put_url(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str,
        sha256: str,
        expires_in: int,
    ):
        del bucket, expires_in
        return (
            f"https://storage.example/upload/{object_key}",
            {"Content-Type": content_type, "x-amz-meta-sha256": sha256},
        )

    def head(self, *, bucket: str, object_key: str):
        del bucket
        return self.objects[object_key]

    def presigned_get_url(self, *, bucket: str, object_key: str, expires_in: int):
        del bucket, expires_in
        return f"https://storage.example/download/{object_key}"

    def delete(self, *, bucket: str, object_key: str):
        del bucket
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)


class UiExecutionRuntimeServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            username="ui-runtime-admin",
            account="ui-runtime-admin",
            password_hash="hash",
            phone="18800004001",
            email="ui-runtime-admin@example.com",
            is_admin=True,
        )
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="UI runtime project", created_by_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="Test",
            base_url="https://test.example.com",
            created_by_id=self.user.id,
        )
        self.db.add(self.environment)
        self.db.commit()

        case = UiTestCaseService(self.db).create_case(
            project_id=self.project.id,
            payload=UiTestCaseCreateRequest(
                name="Runtime login",
                status="active",
                default_environment_id=self.environment.id,
                dsl=dsl(),
            ),
            current_user=self.user,
        )
        self.case_id = case.case_id
        registered = DesktopDeviceService(self.db).register_device(
            payload=DesktopDeviceRegisterRequest(
                installation_id="installation-runtime-0001",
                name="DESKTOP-RUNTIME-01",
                desktop_version="0.1.0",
                os_name="Windows",
                os_version="11",
                architecture="x86_64",
                supported_protocols={
                    "dsl": ["ui-case-v1"],
                    "ipc": ["desktop-ipc-v1"],
                },
                capabilities={"browsers": ["chromium"]},
            ),
            current_user=self.user,
        )
        self.device_id = registered.device.device_id
        self.access_token = registered.credential.access_token
        device = DesktopDeviceService(self.db).repository.get_by_public_id(self.device_id)
        self.db.add(
            DesktopDeviceProjectBinding(
                device_id=device.id,
                project_id=self.project.id,
                enabled=True,
                accepting_jobs=True,
                concurrency_limit=1,
                created_by_id=self.user.id,
            )
        )
        self.db.commit()
        self.principal = DesktopDeviceService(self.db).authenticate_device_access_token(
            self.access_token
        )
        accepted, _, _ = UiExecutionService(self.db).create_execution(
            project_id=self.project.id,
            case_public_id=case.case_id,
            payload=UiExecutionCreateRequest(
                client_request_id="runtime-request-0001",
                version=1,
                environment_id=self.environment.id,
            ),
            current_user=self.user,
        )
        self.execution_id = accepted.execution_id
        self.runtime = UiExecutionRuntimeService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def claim(self) -> dict:
        return self.runtime.claim(
            execution_public_id=self.execution_id,
            payload=UiExecutionClaimRequest(
                device_id=self.device_id,
                expected_status="queued",
                supported_dsl_versions=["ui-case-v1"],
                supported_ipc_versions=["desktop-ipc-v1"],
            ),
            principal=self.principal,
        )

    def create_queued_execution(self, client_request_id: str) -> str:
        accepted, _, _ = UiExecutionService(self.db).create_execution(
            project_id=self.project.id,
            case_public_id=self.case_id,
            payload=UiExecutionCreateRequest(
                client_request_id=client_request_id,
                version=1,
                environment_id=self.environment.id,
            ),
            current_user=self.user,
        )
        return accepted.execution_id

    @staticmethod
    def lease_payload(claimed: dict) -> UiExecutionLeaseRequest:
        return UiExecutionLeaseRequest(
            lease_id=claimed["lease"]["lease_id"],
            lease_version=claimed["lease"]["version"],
        )

    def event_batch(self, claimed: dict, events: list[dict]) -> UiExecutionEventBatchRequest:
        lease = self.lease_payload(claimed)
        return UiExecutionEventBatchRequest(
            lease_id=lease.lease_id,
            lease_version=lease.lease_version,
            events=[UiExecutionEventItem.model_validate(item) for item in events],
        )

    def test_claim_is_exclusive_and_lease_renew_is_idempotent(self):
        claimed = self.claim()
        replay = self.claim()
        self.assertEqual(replay["lease"]["lease_id"], claimed["lease"]["lease_id"])

        initial = self.lease_payload(claimed)
        renewed = self.runtime.renew_lease(
            execution_public_id=self.execution_id,
            payload=initial,
            principal=self.principal,
        )
        self.assertEqual(renewed["lease"]["version"], initial.lease_version + 1)
        replayed = self.runtime.renew_lease(
            execution_public_id=self.execution_id,
            payload=initial,
            principal=self.principal,
        )
        self.assertTrue(replayed["idempotent_replay"])
        self.assertEqual(replayed["lease"]["version"], renewed["lease"]["version"])

        listed = self.runtime.list_executions(
            project_id=self.project.id,
            current_user=self.user,
            execution_status="claimed",
            delivery_status=None,
            attention_only=False,
            assigned_device_id=self.device_id,
            environment_id=self.environment.id,
            source=None,
            keyword="Runtime",
            page=1,
            page_size=20,
        )
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["facets"]["running"], 1)
        self.assertEqual(listed["items"][0]["project_name"], self.project.name)
        self.assertEqual(listed["items"][0]["environment_name"], self.environment.name)

        other_environment = self.runtime.list_executions(
            project_id=self.project.id,
            current_user=self.user,
            execution_status="claimed",
            delivery_status=None,
            attention_only=False,
            assigned_device_id=self.device_id,
            environment_id=self.environment.id + 10_000,
            source=None,
            keyword=None,
            page=1,
            page_size=20,
        )
        self.assertEqual(other_environment["total"], 0)

    def test_available_list_returns_claimable_device_queue(self):
        second_execution_id = self.create_queued_execution("runtime-request-available-2")

        available = self.runtime.list_available_executions(
            principal=self.principal,
            limit=20,
        )

        self.assertEqual(available["total"], 2)
        self.assertEqual(
            [item["execution_id"] for item in available["items"]],
            [self.execution_id, second_execution_id],
        )
        self.assertEqual(available["items"][0]["expected_status"], "queued")
        self.assertEqual(available["items"][0]["case_name"], "Runtime login")

        self.claim()
        at_capacity = self.runtime.list_available_executions(
            principal=self.principal,
            limit=20,
        )
        self.assertEqual(at_capacity, {"items": [], "total": 0})

    def test_polling_lists_use_bounded_database_round_trips(self):
        repository = UiExecutionRepository(self.db)
        project_id = self.project.id
        device_id = self.principal.device.id
        statements = []

        def record_statement(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            items, total, facets = repository.list_by_project(
                project_id=project_id,
                status=None,
                delivery_status=None,
                attention_only=False,
                assigned_device_public_id=None,
                environment_id=None,
                source=None,
                keyword=None,
                page=1,
                page_size=200,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(total, len(items))
        self.assertEqual(facets["queued"], 1)
        self.assertEqual(len(statements), 2)

        statements.clear()
        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            available, available_total = repository.list_available_for_device(
                device_id=device_id,
                active_count=0,
                limit=100,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(available_total, len(available))
        self.assertEqual(available_total, 1)
        self.assertEqual(len(statements), 1)

    def test_available_list_applies_binding_target_and_runtime_eligibility(self):
        binding = self.runtime.repository.get_project_binding(
            device_id=self.principal.device.id,
            project_id=self.project.id,
        )
        binding.accepting_jobs = False
        self.db.flush()
        self.assertEqual(
            self.runtime.list_available_executions(
                principal=self.principal,
                limit=20,
            ),
            {"items": [], "total": 0},
        )

        binding.accepting_jobs = True
        other_registered = DesktopDeviceService(self.db).register_device(
            payload=DesktopDeviceRegisterRequest(
                installation_id="installation-runtime-available-other",
                name="DESKTOP-RUNTIME-OTHER",
                desktop_version="0.1.0",
                os_name="Windows",
                os_version="11",
                architecture="x86_64",
                supported_protocols={
                    "dsl": ["ui-case-v1"],
                    "ipc": ["desktop-ipc-v1"],
                },
                capabilities={"browsers": ["chromium"]},
            ),
            current_user=self.user,
        )
        other_device = DesktopDeviceService(self.db).repository.get_by_public_id(
            other_registered.device.device_id
        )
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.requested_device_id = other_device.id
        self.db.flush()
        self.assertEqual(
            self.runtime.list_available_executions(
                principal=self.principal,
                limit=20,
            ),
            {"items": [], "total": 0},
        )

        execution.requested_device_id = None
        execution.assigned_device_id = other_device.id
        execution.status = "assigned"
        self.db.flush()
        self.assertEqual(
            self.runtime.list_available_executions(
                principal=self.principal,
                limit=20,
            ),
            {"items": [], "total": 0},
        )
        with self.assertRaises(HTTPException) as claim_error:
            self.runtime.claim(
                execution_public_id=self.execution_id,
                payload=UiExecutionClaimRequest(
                    device_id=self.device_id,
                    expected_status="assigned",
                    supported_dsl_versions=["ui-case-v1"],
                    supported_ipc_versions=["desktop-ipc-v1"],
                ),
                principal=self.principal,
            )
        self.assertEqual(claim_error.exception.status_code, 409)

        execution.assigned_device_id = None
        execution.status = "queued"
        self.principal.device.supported_protocols_json = {
            "dsl": ["ui-case-v2"],
            "ipc": ["desktop-ipc-v1"],
        }
        self.db.flush()
        self.assertEqual(
            self.runtime.list_available_executions(
                principal=self.principal,
                limit=20,
            ),
            {"items": [], "total": 0},
        )

    def test_other_device_and_stale_lease_are_rejected(self):
        claimed = self.claim()
        registered = DesktopDeviceService(self.db).register_device(
            payload=DesktopDeviceRegisterRequest(
                installation_id="installation-runtime-0002",
                name="DESKTOP-RUNTIME-02",
                desktop_version="0.1.0",
                os_name="Windows",
                os_version="11",
                architecture="x86_64",
                supported_protocols={
                    "dsl": ["ui-case-v1"],
                    "ipc": ["desktop-ipc-v1"],
                },
                capabilities={"browsers": ["chromium"]},
            ),
            current_user=self.user,
        )
        second_device = DesktopDeviceService(self.db).repository.get_by_public_id(
            registered.device.device_id
        )
        self.db.add(
            DesktopDeviceProjectBinding(
                device_id=second_device.id,
                project_id=self.project.id,
                enabled=True,
                accepting_jobs=True,
                concurrency_limit=1,
                created_by_id=self.user.id,
            )
        )
        self.db.commit()
        second_principal = DesktopDeviceService(
            self.db
        ).authenticate_device_access_token(registered.credential.access_token)

        with self.assertRaises(HTTPException) as claim_error:
            self.runtime.claim(
                execution_public_id=self.execution_id,
                payload=UiExecutionClaimRequest(
                    device_id=registered.device.device_id,
                    expected_status="queued",
                    supported_dsl_versions=["ui-case-v1"],
                    supported_ipc_versions=["desktop-ipc-v1"],
                ),
                principal=second_principal,
            )
        self.assertEqual(claim_error.exception.status_code, 409)
        self.db.rollback()

        lease = self.lease_payload(claimed)
        with self.assertRaises(HTTPException) as device_error:
            self.runtime.append_events(
                execution_public_id=self.execution_id,
                payload=UiExecutionEventBatchRequest(
                    lease_id=lease.lease_id,
                    lease_version=lease.lease_version,
                    events=[
                        UiExecutionEventItem(
                            client_event_id="wrong-device-event",
                            client_sequence=1,
                            event_type="runtime.log",
                            occurred_at=utc_now_naive(),
                        )
                    ],
                ),
                principal=second_principal,
            )
        self.assertEqual(device_error.exception.status_code, 403)
        self.db.rollback()

        with self.assertRaises(HTTPException) as lease_error:
            self.runtime.append_events(
                execution_public_id=self.execution_id,
                payload=UiExecutionEventBatchRequest(
                    lease_id=lease.lease_id,
                    lease_version=lease.lease_version + 1,
                    events=[
                        UiExecutionEventItem(
                            client_event_id="stale-lease-event",
                            client_sequence=1,
                            event_type="runtime.log",
                            occurred_at=utc_now_naive(),
                        )
                    ],
                ),
                principal=self.principal,
            )
        self.assertEqual(lease_error.exception.status_code, 409)
        self.db.rollback()

    def test_event_sequence_redaction_projection_and_replay(self):
        claimed = self.claim()
        now = utc_now_naive()
        payload = self.event_batch(
            claimed,
            [
                {
                    "client_event_id": "evt-1",
                    "client_sequence": 1,
                    "event_type": "execution.running",
                    "occurred_at": now,
                    "payload": {"authorization": "Bearer secret-value"},
                },
                {
                    "client_event_id": "evt-2",
                    "client_sequence": 2,
                    "event_type": "step.started",
                    "occurred_at": now,
                    "step_id": "step_001",
                    "payload": {"attempt": 1},
                },
                {
                    "client_event_id": "evt-3",
                    "client_sequence": 3,
                    "event_type": "step.finished",
                    "occurred_at": now,
                    "step_id": "step_001",
                    "payload": {
                        "attempt": 1,
                        "status": "passed",
                        "duration_ms": 12,
                        "result": {"url": "https://test.example.com/login"},
                    },
                },
            ],
        )
        accepted = self.runtime.append_events(
            execution_public_id=self.execution_id,
            payload=payload,
            principal=self.principal,
        )
        self.assertEqual(accepted["accepted_through_sequence"], 3)
        replay = self.runtime.append_events(
            execution_public_id=self.execution_id,
            payload=payload,
            principal=self.principal,
        )
        self.assertEqual(replay["duplicate_count"], 3)
        first_event = self.db.scalar(
            select(UiExecutionEvent).where(UiExecutionEvent.client_sequence == 1)
        )
        self.assertNotIn("secret-value", str(first_event.payload_json))
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        self.assertEqual(execution.status, "running")
        self.assertEqual(execution.passed_steps, 1)
        self.assertEqual(
            self.db.query(ExecutionStepDiagnostic)
            .filter(ExecutionStepDiagnostic.execution_type == "ui")
            .count(),
            1,
        )

        conflict = self.event_batch(
            claimed,
            [
                {
                    "client_event_id": "evt-different",
                    "client_sequence": 3,
                    "event_type": "runtime.log",
                    "occurred_at": now,
                }
            ],
        )
        with self.assertRaises(HTTPException) as error:
            self.runtime.append_events(
                execution_public_id=self.execution_id,
                payload=conflict,
                principal=self.principal,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.db.rollback()

    def test_runtime_patch_forces_assisted_completion(self):
        claimed = self.claim()
        lease = self.lease_payload(claimed)
        patch_payload = UiExecutionRuntimePatchRequest(
            lease_id=lease.lease_id,
            lease_version=lease.lease_version,
            step_id="step_001",
            patch_type="locator",
            before={"selector": "#old"},
            after={"selector": "#new"},
            reason="user corrected locator",
        )
        created = self.runtime.create_patch(
            execution_public_id=self.execution_id,
            payload=patch_payload,
            principal=self.principal,
        )
        replay = self.runtime.create_patch(
            execution_public_id=self.execution_id,
            payload=patch_payload,
            principal=self.principal,
        )
        self.assertFalse(created["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(self.db.query(UiRuntimePatch).count(), 1)

        passed = UiExecutionCompleteRequest(
            lease_id=lease.lease_id,
            lease_version=lease.lease_version,
            final_client_sequence=0,
            status="passed",
            summary=UiExecutionCompleteSummary(
                total_steps=1,
                passed_steps=1,
                failed_steps=0,
                skipped_steps=0,
                duration_ms=20,
            ),
        )
        with self.assertRaises(HTTPException) as error:
            self.runtime.complete(
                execution_public_id=self.execution_id,
                payload=passed,
                principal=self.principal,
            )
        self.assertEqual(error.exception.detail["error"], "assisted_status_required")
        self.db.rollback()

        assisted = passed.model_copy(
            update={
                "status": "assisted",
                "summary": passed.summary.model_copy(update={"assisted": True}),
            }
        )
        completed = self.runtime.complete(
            execution_public_id=self.execution_id,
            payload=assisted,
            principal=self.principal,
        )
        self.assertEqual(completed["status"], "assisted")
        self.assertEqual(completed["delivery_status"], "complete")
        self.assertTrue(
            self.runtime.complete(
                execution_public_id=self.execution_id,
                payload=assisted,
                principal=self.principal,
            )["idempotent_replay"]
        )

    def test_platform_patch_request_is_delivered_applied_and_attributed(self):
        claimed = self.claim()
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.status = "waiting_user"
        self.db.commit()
        request_payload = UiExecutionPatchRequestCreateRequest(
            client_request_id="platform-patch-request-1",
            step_id="step_001",
            patch_type="input",
            before={"input_value": "testauto://smoke/login"},
            after={"input_value": "testauto://smoke/login-fixed"},
            reason="operator corrected the current navigation target",
        )

        requested, device_id, replay = self.runtime.create_patch_request(
            execution_public_id=self.execution_id,
            payload=request_payload,
            current_user=self.user,
        )
        replayed, replay_device_id, replay_flag = self.runtime.create_patch_request(
            execution_public_id=self.execution_id,
            payload=request_payload,
            current_user=self.user,
        )

        self.assertEqual(device_id, self.device_id)
        self.assertFalse(replay)
        self.assertTrue(replay_flag)
        self.assertIsNone(replay_device_id)
        self.assertEqual(replayed["command_id"], requested["command_id"])
        self.assertEqual(requested["command_type"], "patch")
        self.assertEqual(
            requested["payload"]["schema_version"],
            "ui-runtime-patch-request-v1",
        )

        renewed = self.runtime.renew_lease(
            execution_public_id=self.execution_id,
            payload=self.lease_payload(claimed),
            principal=self.principal,
        )
        delivered = next(
            item
            for item in renewed["commands"]
            if item["command_id"] == requested["command_id"]
        )
        self.assertEqual(delivered["status"], "delivered")
        with self.assertRaises(HTTPException) as error:
            self.runtime.acknowledge_command(
                execution_public_id=self.execution_id,
                command_public_id=requested["command_id"],
                payload=UiExecutionCommandAckRequest(
                    lease_id=renewed["lease"]["lease_id"],
                    lease_version=renewed["lease"]["version"],
                    status="acknowledged",
                    detail={"applied": True},
                ),
                principal=self.principal,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(
            error.exception.detail["error"],
            "patch_request_not_applied",
        )
        self.db.rollback()

        patch = self.runtime.create_patch(
            execution_public_id=self.execution_id,
            payload=UiExecutionRuntimePatchRequest(
                lease_id=renewed["lease"]["lease_id"],
                lease_version=renewed["lease"]["version"],
                command_id=requested["command_id"],
                step_id="step_001",
                patch_type="input",
                before=requested["payload"]["before"],
                after=requested["payload"]["after"],
                reason=requested["payload"]["reason"],
            ),
            principal=self.principal,
        )
        patch_replay = self.runtime.create_patch(
            execution_public_id=self.execution_id,
            payload=UiExecutionRuntimePatchRequest(
                lease_id=renewed["lease"]["lease_id"],
                lease_version=renewed["lease"]["version"],
                command_id=requested["command_id"],
                step_id="step_001",
                patch_type="input",
                before=requested["payload"]["before"],
                after=requested["payload"]["after"],
                reason=requested["payload"]["reason"],
            ),
            principal=self.principal,
        )

        self.assertEqual(patch["command_id"], requested["command_id"])
        self.assertFalse(patch["idempotent_replay"])
        self.assertTrue(patch_replay["idempotent_replay"])
        stored_patch = self.db.scalar(
            select(UiRuntimePatch).where(UiRuntimePatch.id == patch["patch_id"])
        )
        self.assertEqual(stored_patch.actor_user_id, self.user.id)
        self.assertIsNotNone(stored_patch.request_command_id)

        acknowledged = self.runtime.acknowledge_command(
            execution_public_id=self.execution_id,
            command_public_id=requested["command_id"],
            payload=UiExecutionCommandAckRequest(
                lease_id=renewed["lease"]["lease_id"],
                lease_version=renewed["lease"]["version"],
                status="acknowledged",
                detail={"applied": True, "patch_id": patch["patch_id"]},
            ),
            principal=self.principal,
        )
        self.assertEqual(acknowledged["status"], "acknowledged")

        detail = self.runtime.get_execution(
            execution_public_id=self.execution_id,
            current_user=self.user,
        )
        self.assertEqual(detail["case_version"], 1)
        self.assertTrue(detail["case_checksum"].startswith("sha256:"))
        self.assertEqual(
            detail["runtime_patches"][0]["command_id"],
            requested["command_id"],
        )

    def test_platform_patch_request_rejects_stale_state_payload_and_permission(self):
        self.claim()
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.status = "waiting_user"
        self.db.commit()

        stale = UiExecutionPatchRequestCreateRequest(
            client_request_id="platform-patch-stale",
            step_id="step_001",
            patch_type="input",
            before={"input_value": "stale-value"},
            after={"input_value": "testauto://smoke/login-fixed"},
            reason="stale editor state",
        )
        with self.assertRaises(HTTPException) as error:
            self.runtime.create_patch_request(
                execution_public_id=self.execution_id,
                payload=stale,
                current_user=self.user,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail["error"], "patch_request_stale")
        self.db.rollback()

        invalid_fields = stale.model_copy(
            update={
                "client_request_id": "platform-patch-invalid-fields",
                "before": None,
                "after": {"timeout_ms": 5000},
            }
        )
        with self.assertRaises(HTTPException) as error:
            self.runtime.create_patch_request(
                execution_public_id=self.execution_id,
                payload=invalid_fields,
                current_user=self.user,
            )
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(error.exception.detail["error"], "patch_request_invalid")
        self.db.rollback()

        outsider = User(
            username="ui-patch-outsider",
            account="ui-patch-outsider",
            password_hash="hash",
            phone="18800004009",
            email="ui-patch-outsider@example.com",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.runtime.create_patch_request(
                execution_public_id=self.execution_id,
                payload=stale.model_copy(
                    update={
                        "client_request_id": "platform-patch-outsider",
                        "before": None,
                    }
                ),
                current_user=outsider,
            )
        self.assertEqual(error.exception.status_code, 403)
        self.db.rollback()

        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.status = "running"
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.runtime.create_patch_request(
                execution_public_id=self.execution_id,
                payload=stale.model_copy(
                    update={
                        "client_request_id": "platform-patch-running",
                        "before": None,
                    }
                ),
                current_user=self.user,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail["error"], "command_state_conflict")
        self.db.rollback()

    def test_device_cannot_apply_a_tampered_platform_patch_request(self):
        claimed = self.claim()
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.status = "paused"
        self.db.commit()
        requested, _, _ = self.runtime.create_patch_request(
            execution_public_id=self.execution_id,
            payload=UiExecutionPatchRequestCreateRequest(
                client_request_id="platform-patch-tamper",
                step_id="step_001",
                patch_type="input",
                after={"input_value": "testauto://smoke/login-fixed"},
                reason="operator correction",
            ),
            current_user=self.user,
        )
        renewed = self.runtime.renew_lease(
            execution_public_id=self.execution_id,
            payload=self.lease_payload(claimed),
            principal=self.principal,
        )

        with self.assertRaises(HTTPException) as error:
            self.runtime.create_patch(
                execution_public_id=self.execution_id,
                payload=UiExecutionRuntimePatchRequest(
                    lease_id=renewed["lease"]["lease_id"],
                    lease_version=renewed["lease"]["version"],
                    command_id=requested["command_id"],
                    step_id="step_001",
                    patch_type="input",
                    before=requested["payload"]["before"],
                    after={"input_value": "tampered-target"},
                    reason=requested["payload"]["reason"],
                ),
                principal=self.principal,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(
            error.exception.detail["error"],
            "patch_request_payload_conflict",
        )
        self.db.rollback()

    def test_command_delivery_ack_and_cancel_before_claim(self):
        claimed = self.claim()
        lease = self.lease_payload(claimed)
        now = utc_now_naive()
        self.runtime.append_events(
            execution_public_id=self.execution_id,
            payload=self.event_batch(
                claimed,
                [
                    {
                        "client_event_id": "evt-running",
                        "client_sequence": 1,
                        "event_type": "execution.running",
                        "occurred_at": now,
                    }
                ],
            ),
            principal=self.principal,
        )
        command, device_id, replay = self.runtime.create_command(
            execution_public_id=self.execution_id,
            payload=UiExecutionCommandCreateRequest(
                client_request_id="pause-request-1",
                command_type="pause",
            ),
            current_user=self.user,
        )
        self.assertEqual(device_id, self.device_id)
        self.assertFalse(replay)
        renewed = self.runtime.renew_lease(
            execution_public_id=self.execution_id,
            payload=lease,
            principal=self.principal,
        )
        self.assertEqual(renewed["commands"][0]["status"], "delivered")
        acked = self.runtime.acknowledge_command(
            execution_public_id=self.execution_id,
            command_public_id=command["command_id"],
            payload=UiExecutionCommandAckRequest(
                lease_id=renewed["lease"]["lease_id"],
                lease_version=renewed["lease"]["version"],
                status="acknowledged",
                detail={"applied": True},
            ),
            principal=self.principal,
        )
        self.assertEqual(acked["status"], "acknowledged")

    def test_stale_lease_is_marked_lost_once(self):
        self.claim()
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.lease_expires_at = utc_now_naive() - timedelta(seconds=1)
        self.db.commit()
        self.assertEqual(self.runtime.expire_stale_leases(), 1)
        self.assertEqual(self.runtime.expire_stale_leases(), 0)
        self.db.refresh(execution)
        self.assertEqual(execution.status, "lost")
        self.assertEqual(execution.attention_reason, "lease_lost")
        self.assertEqual(
            self.db.query(UiExecutionEvent)
            .filter(UiExecutionEvent.event_type == "lease.lost")
            .count(),
            1,
        )
        projection = self.db.scalar(
            select(ExecutionRecordIndex).where(
                ExecutionRecordIndex.execution_type == "ui",
                ExecutionRecordIndex.execution_id == execution.id,
            )
        )
        self.assertEqual(projection.status, "lost")

    def test_sse_replays_persisted_events_and_stops_at_terminal_state(self):
        self.claim()
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        execution.lease_expires_at = utc_now_naive() - timedelta(seconds=1)
        self.db.commit()
        self.runtime.expire_stale_leases()
        chunks = list(
            UiExecutionRuntimeService.stream_events(
                execution_public_id=self.execution_id,
                last_event_id=0,
                session_factory=sessionmaker(bind=self.engine),
            )
        )
        self.assertEqual(len(chunks), 1)
        self.assertIn("id: 1", chunks[0])
        self.assertIn("event: lease.lost", chunks[0])
        self.assertEqual(
            list(
                UiExecutionRuntimeService.stream_events(
                    execution_public_id=self.execution_id,
                    last_event_id=1,
                    session_factory=sessionmaker(bind=self.engine),
                )
            ),
            [],
        )

    def test_artifact_presign_finalize_read_and_delete(self):
        claimed = self.claim()
        lease = self.lease_payload(claimed)
        storage = FakeObjectStorage()
        service = UiExecutionArtifactService(self.db, storage=storage)
        payload = UiArtifactPresignRequest(
            lease_id=lease.lease_id,
            lease_version=lease.lease_version,
            client_request_id="artifact-request-1",
            step_id="step_001",
            section="screenshot",
            content_type="image/png",
            original_filename="login.png",
            size_bytes=128,
            sha256="a" * 64,
        )
        created = service.presign(
            execution_public_id=self.execution_id,
            payload=payload,
            principal=self.principal,
        )
        replay = service.presign(
            execution_public_id=self.execution_id,
            payload=payload,
            principal=self.principal,
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(created["artifact_ref"], replay["artifact_ref"])
        upload = self.db.scalar(
            select(ExecutionArtifactUploadSession).where(
                ExecutionArtifactUploadSession.upload_id == created["upload_id"]
            )
        )
        storage.objects[upload.object_key] = {
            "size_bytes": 128,
            "content_type": "image/png",
            "metadata": {"sha256": "a" * 64},
            "etag": "etag-1",
        }
        finalize = UiArtifactFinalizeRequest(
            lease_id=lease.lease_id,
            lease_version=lease.lease_version,
            upload_id=created["upload_id"],
            artifact_ref=created["artifact_ref"],
        )
        finalized = service.finalize(
            execution_public_id=self.execution_id,
            payload=finalize,
            principal=self.principal,
        )
        finalized_replay = service.finalize(
            execution_public_id=self.execution_id,
            payload=finalize,
            principal=self.principal,
        )
        self.assertFalse(finalized["idempotent_replay"])
        self.assertTrue(finalized_replay["idempotent_replay"])
        artifact = self.db.scalar(select(ExecutionPayloadArtifact))
        self.assertEqual(artifact.storage_backend, "minio")
        self.assertEqual(artifact.metadata_json["original_filename"], "login.png")
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        self.assertEqual(execution.delivery_status, "complete")
        self.assertEqual(
            service.list_artifacts(
                execution_public_id=self.execution_id,
                current_user=self.user,
            )["total"],
            1,
        )
        download = service.get_download_url(
            execution_public_id=self.execution_id,
            artifact_ref=created["artifact_ref"],
            current_user=self.user,
        )
        self.assertIn("/download/", download["url"])
        service.delete_artifact(
            execution_public_id=self.execution_id,
            artifact_ref=created["artifact_ref"],
            current_user=self.user,
        )
        self.assertEqual(self.db.query(ExecutionPayloadArtifact).count(), 0)
        self.assertIn(upload.object_key, storage.deleted)

    def test_completion_marks_unfinished_artifact_delivery_failed(self):
        claimed = self.claim()
        lease = self.lease_payload(claimed)
        UiExecutionArtifactService(
            self.db,
            storage=FakeObjectStorage(),
        ).presign(
            execution_public_id=self.execution_id,
            payload=UiArtifactPresignRequest(
                lease_id=lease.lease_id,
                lease_version=lease.lease_version,
                client_request_id="artifact-abandoned-1",
                step_id="step_001",
                section="screenshot",
                content_type="image/png",
                original_filename="failed-step.png",
                size_bytes=128,
                sha256="d" * 64,
            ),
            principal=self.principal,
        )

        completed = self.runtime.complete(
            execution_public_id=self.execution_id,
            payload=UiExecutionCompleteRequest(
                lease_id=lease.lease_id,
                lease_version=lease.lease_version,
                final_client_sequence=0,
                status="passed",
                summary=UiExecutionCompleteSummary(
                    total_steps=1,
                    passed_steps=1,
                    failed_steps=0,
                    skipped_steps=0,
                    duration_ms=20,
                ),
            ),
            principal=self.principal,
        )

        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        self.assertEqual(completed["status"], "passed")
        self.assertEqual(completed["delivery_status"], "failed")
        self.assertEqual(execution.delivery_status, "failed")
        self.assertEqual(execution.attention_reason, "artifact_delivery_failed")

    def test_artifact_finalize_rejects_remote_metadata_mismatch(self):
        claimed = self.claim()
        lease = self.lease_payload(claimed)
        storage = FakeObjectStorage()
        service = UiExecutionArtifactService(self.db, storage=storage)
        created = service.presign(
            execution_public_id=self.execution_id,
            payload=UiArtifactPresignRequest(
                lease_id=lease.lease_id,
                lease_version=lease.lease_version,
                client_request_id="artifact-mismatch-1",
                section="trace",
                content_type="application/zip",
                original_filename="trace.zip",
                size_bytes=256,
                sha256="b" * 64,
            ),
            principal=self.principal,
        )
        upload = self.db.scalar(
            select(ExecutionArtifactUploadSession).where(
                ExecutionArtifactUploadSession.upload_id == created["upload_id"]
            )
        )
        storage.objects[upload.object_key] = {
            "size_bytes": 255,
            "content_type": "application/zip",
            "metadata": {"sha256": "b" * 64},
            "etag": "etag-wrong",
        }
        with self.assertRaises(HTTPException) as error:
            service.finalize(
                execution_public_id=self.execution_id,
                payload=UiArtifactFinalizeRequest(
                    lease_id=lease.lease_id,
                    lease_version=lease.lease_version,
                    upload_id=created["upload_id"],
                    artifact_ref=created["artifact_ref"],
                ),
                principal=self.principal,
            )
        self.assertEqual(error.exception.detail["error"], "artifact_metadata_mismatch")
        self.db.rollback()
        self.assertEqual(self.db.query(ExecutionPayloadArtifact).count(), 0)

    def test_expired_artifact_upload_cleanup_deletes_orphan(self):
        claimed = self.claim()
        lease = self.lease_payload(claimed)
        storage = FakeObjectStorage()
        service = UiExecutionArtifactService(self.db, storage=storage)
        created = service.presign(
            execution_public_id=self.execution_id,
            payload=UiArtifactPresignRequest(
                lease_id=lease.lease_id,
                lease_version=lease.lease_version,
                client_request_id="artifact-expired-1",
                section="log",
                content_type="text/plain",
                original_filename="runtime.log",
                size_bytes=32,
                sha256="c" * 64,
            ),
            principal=self.principal,
        )
        upload = self.db.scalar(
            select(ExecutionArtifactUploadSession).where(
                ExecutionArtifactUploadSession.upload_id == created["upload_id"]
            )
        )
        upload.expires_at = utc_now_naive() - timedelta(seconds=1)
        storage.objects[upload.object_key] = {
            "size_bytes": 32,
            "content_type": "text/plain",
            "metadata": {"sha256": "c" * 64},
            "etag": "etag-expired",
        }
        self.db.commit()
        self.assertEqual(service.cleanup_expired_uploads(), 1)
        self.db.refresh(upload)
        self.assertEqual(upload.status, "expired")
        self.assertIn(upload.object_key, storage.deleted)

    def test_completed_local_run_import_is_atomic_and_idempotent(self):
        now = utc_now_naive()
        original = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == self.execution_id)
        )
        payload = UiLocalRunImportRequest(
            client_request_id="local-import-request-1",
            case_id=original.ui_test_case.public_id,
            version=1,
            environment_id=self.environment.id,
            device_id=self.device_id,
            status="passed",
            summary=UiExecutionCompleteSummary(
                total_steps=1,
                passed_steps=1,
                failed_steps=0,
                skipped_steps=0,
                duration_ms=25,
            ),
            started_at=now,
            finished_at=now + timedelta(milliseconds=25),
            steps=[
                UiLocalRunStepResult(
                    step_id="step_001",
                    status="passed",
                    started_at=now,
                    finished_at=now + timedelta(milliseconds=25),
                    duration_ms=25,
                    result={"url": "https://test.example.com/login"},
                )
            ],
        )
        service = UiLocalRunImportService(self.db)
        imported, replay = service.import_run(
            project_id=self.project.id,
            payload=payload,
            current_user=self.user,
        )
        repeated, replayed = service.import_run(
            project_id=self.project.id,
            payload=payload,
            current_user=self.user,
        )
        self.assertFalse(replay)
        self.assertTrue(replayed)
        self.assertEqual(imported["execution_id"], repeated["execution_id"])
        self.assertEqual(imported["source"], "local_import")
        self.assertEqual(imported["status"], "passed")
        self.assertEqual(len(imported["steps"]), 1)
        imported_model = self.db.scalar(
            select(UiExecution).where(
                UiExecution.public_id == imported["execution_id"]
            )
        )
        projection = self.db.scalar(
            select(ExecutionRecordIndex).where(
                ExecutionRecordIndex.execution_type == "ui",
                ExecutionRecordIndex.execution_id == imported_model.id,
            )
        )
        self.assertEqual(projection.status, "passed")

    def test_platform_patch_request_openapi_contract(self):
        from app.main import create_app

        schema = create_app().openapi()
        operation = schema["paths"][
            "/api/v1/ui-executions/{execution_id}/patch-requests"
        ]["post"]
        request_schema = operation["requestBody"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(
            request_schema["$ref"],
            "#/components/schemas/UiExecutionPatchRequestCreateRequest",
        )
        self.assertIn("202", operation["responses"])
        self.assertEqual(
            operation["security"],
            [{"OAuth2PasswordBearer": []}],
        )
        runtime_patch_schema = schema["components"]["schemas"][
            "UiExecutionRuntimePatchRequest"
        ]
        self.assertIn("command_id", runtime_patch_schema["properties"])

    def test_available_execution_openapi_contract(self):
        from app.main import create_app

        schema = create_app().openapi()
        operation = schema["paths"]["/api/v1/ui-executions/available"]["get"]
        self.assertEqual(operation["security"], [{"HTTPBearer": []}])
        limit = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "limit"
        )
        self.assertEqual(limit["schema"]["default"], 20)
        self.assertEqual(limit["schema"]["maximum"], 200)


if __name__ == "__main__":
    unittest.main()
