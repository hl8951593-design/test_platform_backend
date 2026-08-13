import importlib
import inspect
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1.api import api_router
from app.api.v1.deps import get_current_user, get_db
from app.api.v1.routers import ui_test_cases
from app.api.v1.routers.ui_test_cases import _execution_notification_targets
from app.db.base import Base
from app.models.execution_diagnostic import ExecutionRecordIndex
from app.models.desktop_device import DesktopDevice, DesktopDeviceProjectBinding
from app.models.project import Project, ProjectEnvironment, ProjectEnvironmentVariable
from app.models.ui_execution import UiExecution
from app.models.ui_test_case import UiTestCase, UiTestCaseVersion
from app.models.user import User
from app.repositories.execution_record_repository import ExecutionRecordRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.ui_execution import UiExecutionCreateRequest
from app.schemas.ui_test_case import (
    UiCaseDsl,
    UiTestCaseCreateRequest,
    UiTestCaseUpdateRequest,
    UiTestCaseVersionCreateRequest,
)
from app.services.ui_execution_service import UiExecutionService
from app.services.execution_record_service import ExecutionRecordService
from app.services.ui_test_case_service import UiTestCaseService


def flat_dsl(*, with_click: bool = False, secret: bool = False) -> dict:
    steps = [
        {
            "id": "step_001",
            "name": "Open smoke page",
            "kind": "action",
            "operation": "navigate",
            "input_value": "testauto://smoke/login",
        }
    ]
    if with_click:
        steps.append(
            {
                "id": "step_002",
                "name": "Click login",
                "kind": "action",
                "operation": "click",
                "locator_by": "role",
                "locator_value": "button: Login",
            }
        )
    if secret:
        steps.append(
            {
                "id": "step_003",
                "name": "Fill password",
                "kind": "action",
                "operation": "fill",
                "locator_by": "label",
                "locator_value": "Password",
                "input_value": "${secret.password}",
            }
        )
    return {"schema_version": "ui-case-v1", "steps": steps}


class UiCaseDslTests(unittest.TestCase):
    def test_accepts_target_nested_shape_and_normalizes_for_current_worker(self):
        dsl = UiCaseDsl.model_validate(
            {
                "schema_version": "ui-case-v1",
                "steps": [
                    {
                        "id": "step_001",
                        "name": "Open login",
                        "type": "action",
                        "action": "navigate",
                        "url": "testauto://smoke/login",
                    },
                    {
                        "id": "step_002",
                        "name": "Click login",
                        "type": "action",
                        "action": "click",
                        "locator": {
                            "by": "role",
                            "role": "button",
                            "name": "Login",
                        },
                    },
                ],
            }
        )

        canonical = dsl.canonical_dict()
        self.assertEqual(canonical["steps"][0]["operation"], "navigate")
        self.assertEqual(canonical["steps"][0]["input_value"], "testauto://smoke/login")
        self.assertEqual(canonical["steps"][1]["locator_by"], "role")
        self.assertEqual(canonical["steps"][1]["locator_value"], "button: Login")
        self.assertNotIn("action", canonical["steps"][1])
        self.assertNotIn("options", canonical["steps"][1])

    def test_accepts_extended_playwright_actions_assertions_and_options(self):
        dsl = UiCaseDsl.model_validate(
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "Drag card",
                        "kind": "action",
                        "operation": "drag_to",
                        "locator_by": "test_id",
                        "locator_value": "source-card",
                        "options": {
                            "target_locator_by": "test_id",
                            "target_locator_value": "target-column",
                            "exact": True,
                            "nth": 0,
                        },
                    },
                    {
                        "id": "step_002",
                        "name": "Button enabled",
                        "kind": "assertion",
                        "operation": "enabled",
                        "locator_by": "role",
                        "locator_value": "button: Submit",
                    },
                ]
            }
        )

        canonical = dsl.canonical_dict()
        self.assertEqual(canonical["steps"][0]["operation"], "drag_to")
        self.assertEqual(canonical["steps"][0]["options"]["target_locator_value"], "target-column")
        self.assertEqual(canonical["steps"][1]["operation"], "enabled")

    def test_accepts_desktop_recorder_v2_evidence_options(self):
        locator = {
            "by": "role",
            "value": "button: 登录",
            "recommended": True,
            "match_count": 1,
            "stability": "high",
            "score": 340,
            "exact": True,
            "within": {},
            "filters": {},
            "fingerprint_similarity": 1.0,
            "actionability": True,
            "reasons": [],
        }
        dsl = UiCaseDsl.model_validate(
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "点击登录",
                        "kind": "action",
                        "operation": "click",
                        "locator_by": "role",
                        "locator_value": "button: 登录",
                        "options": {
                            "source_page_url": "https://example.test/login",
                            "source_frame_url": "https://example.test/login",
                            "destination_page_url": "https://example.test/dashboard",
                            "destination_page_title": "工作台",
                            "page_id": "page_001",
                            "recording_event_id": "event_001",
                            "recording_action_id": "action_001",
                            "locator_candidates": [locator],
                            "target_fingerprint": {
                                "version": 2,
                                "tag": "button",
                                "input_type": "button",
                                "role": "button",
                                "accessible_name": "登录",
                                "test_id": "",
                                "label": "",
                                "text": "登录",
                                "placeholder": "",
                                "name": "",
                                "form": "登录表单",
                                "landmark": "main",
                                "shadow_root": "none",
                                "shadow_hosts": [],
                                "shadow_contract": "",
                                "stable_attributes": {"type": "submit"},
                            },
                            "locator_plan": {
                                "version": 1,
                                "primary": locator,
                                "fallbacks": [],
                            },
                            "action_episode": {
                                "version": 1,
                                "pre_state": {
                                    "url": "https://example.test/login",
                                    "title": "登录",
                                    "visible": True,
                                    "disabled": False,
                                    "checked": None,
                                    "text": "登录",
                                    "value": "",
                                },
                                "post_state": {
                                    "url": "https://example.test/dashboard",
                                    "title": "工作台",
                                    "visible": True,
                                    "disabled": False,
                                    "checked": None,
                                    "text": "登录",
                                    "value": "",
                                },
                                "signals": ["url_changed"],
                            },
                            "target_similarity": 1.0,
                            "actionability_passed": True,
                            "validation_lanes": [
                                {
                                    "run": 1,
                                    "locator": "passed",
                                    "identity": "passed",
                                    "actionability": "passed",
                                    "session": "not_captured",
                                    "variant": "not_captured",
                                    "execution": "passed",
                                    "error": "",
                                    "target_similarity": 1.0,
                                }
                            ],
                            "hard_gate_failures": [],
                            "source_is_main_frame": True,
                            "network_dependencies": [
                                {
                                    "classification": "primary",
                                    "method": "GET",
                                    "url": "https://example.test/api/session",
                                    "resource_type": "fetch",
                                    "elapsed_ms": 120,
                                }
                            ],
                        },
                    }
                ]
            }
        )

        options = dsl.canonical_dict()["steps"][0]["options"]
        self.assertEqual(options["locator_plan"]["primary"]["value"], "button: 登录")
        self.assertEqual(options["target_fingerprint"]["accessible_name"], "登录")
        self.assertEqual(options["action_episode"]["signals"], ["url_changed"])
        self.assertEqual(options["destination_page_url"], "https://example.test/dashboard")
        self.assertEqual(options["validation_lanes"][0]["execution"], "passed")

    def test_profile_ref_is_an_opaque_local_alias_and_never_a_file_path(self):
        payload = {
            "browser": {"profile_ref": "ctx_0123456789abcdef"},
            "steps": [
                {
                    "id": "step_001",
                    "name": "Open login",
                    "kind": "action",
                    "operation": "navigate",
                    "input_value": "https://example.test/login",
                }
            ],
        }

        dsl = UiCaseDsl.model_validate(payload)
        self.assertEqual(dsl.canonical_dict()["browser"]["profile_ref"], "ctx_0123456789abcdef")

        for unsafe_ref in ("C:\\Users\\qa\\profile", "../profile", "/tmp/profile"):
            with self.subTest(unsafe_ref=unsafe_ref), self.assertRaises(ValidationError):
                UiCaseDsl.model_validate(
                    {**payload, "browser": {"profile_ref": unsafe_ref}}
                )

    def test_rejects_unknown_operation_duplicate_step_and_absolute_upload_path(self):
        invalid_payloads = [
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "Script",
                        "kind": "action",
                        "operation": "javascript",
                    }
                ]
            },
            {
                "steps": [
                    {
                        "id": "same",
                        "name": "One",
                        "kind": "action",
                        "operation": "navigate",
                        "input_value": "/one",
                    },
                    {
                        "id": "same",
                        "name": "Two",
                        "kind": "action",
                        "operation": "navigate",
                        "input_value": "/two",
                    },
                ]
            },
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "Upload",
                        "kind": "action",
                        "operation": "upload",
                        "locator_by": "label",
                        "locator_value": "File",
                        "input_value": "C:\\Users\\me\\secret.txt",
                    }
                ]
            },
            {
                "steps": [
                    {
                        "id": "step_001",
                        "name": "Drag without target",
                        "kind": "action",
                        "operation": "drag_to",
                        "locator_by": "test_id",
                        "locator_value": "source-card",
                    }
                ]
            },
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                UiCaseDsl.model_validate(payload)


class UiTestCaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            username="ui-admin",
            account="ui-admin",
            password_hash="hash",
            phone="18800002001",
            email="ui-admin@example.com",
            is_admin=True,
        )
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="UI project", created_by_id=self.user.id)
        self.other_project = Project(name="Other project", created_by_id=self.user.id)
        self.db.add_all([self.project, self.other_project])
        self.db.flush()
        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="Test",
            base_url="https://test.example.com",
            created_by_id=self.user.id,
        )
        self.other_environment = ProjectEnvironment(
            project_id=self.other_project.id,
            name="Other",
            base_url="https://other.example.com",
            created_by_id=self.user.id,
        )
        self.db.add_all([self.environment, self.other_environment])
        self.db.flush()
        self.db.add_all(
            [
                ProjectEnvironmentVariable(
                    environment_id=self.environment.id,
                    name="tenant",
                    value="qa",
                    is_secret=False,
                ),
                ProjectEnvironmentVariable(
                    environment_id=self.environment.id,
                    name="password",
                    value="encrypted-value-must-not-enter-snapshot",
                    is_secret=True,
                ),
            ]
        )
        self.db.commit()
        self.case_service = UiTestCaseService(self.db)
        self.execution_service = UiExecutionService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_case(self, *, active: bool = True, secret: bool = False):
        return self.case_service.create_case(
            project_id=self.project.id,
            payload=UiTestCaseCreateRequest(
                name="Login UI",
                status="active" if active else "draft",
                tags=["smoke", "smoke", " ui "],
                default_environment_id=self.environment.id,
                dsl=UiCaseDsl.model_validate(flat_dsl(secret=secret)),
            ),
            current_user=self.user,
        )

    def test_create_lists_and_soft_deletes_case(self):
        created = self.create_case()

        self.assertEqual(created.current_version, 1)
        self.assertEqual(created.tags, ["smoke", "ui"])
        listed = self.case_service.list_cases(
            project_id=self.project.id,
            keyword="Login",
            case_status="active",
            environment_id=self.environment.id,
            page=1,
            page_size=20,
            current_user=self.user,
        )
        self.assertEqual(listed["total"], 1)

        self.case_service.delete_case(
            case_public_id=created.case_id,
            current_user=self.user,
        )
        self.assertEqual(
            self.case_service.list_cases(
                project_id=self.project.id,
                keyword=None,
                case_status=None,
                environment_id=None,
                page=1,
                page_size=20,
                current_user=self.user,
            )["total"],
            0,
        )
        self.assertEqual(self.db.query(UiTestCaseVersion).count(), 1)

    def test_versions_are_immutable_checksum_idempotent_and_optimistically_locked(self):
        created = self.create_case()
        version_two_payload = UiTestCaseVersionCreateRequest(
            base_version=1,
            dsl=UiCaseDsl.model_validate(flat_dsl(with_click=True)),
            change_summary="add login click",
        )
        version_two = self.case_service.create_version(
            case_public_id=created.case_id,
            payload=version_two_payload,
            current_user=self.user,
        )
        retry = self.case_service.create_version(
            case_public_id=created.case_id,
            payload=version_two_payload,
            current_user=self.user,
        )

        self.assertEqual(version_two.version, 2)
        self.assertEqual(retry.version, 2)
        self.assertEqual(self.db.query(UiTestCaseVersion).count(), 2)
        version_one = self.case_service.get_version(
            case_public_id=created.case_id,
            version_number=1,
            current_user=self.user,
        )
        self.assertEqual(len(version_one.dsl["steps"]), 1)

        with self.assertRaises(HTTPException) as conflict:
            self.case_service.create_version(
                case_public_id=created.case_id,
                payload=UiTestCaseVersionCreateRequest(
                    base_version=1,
                    dsl=UiCaseDsl.model_validate(flat_dsl(secret=True)),
                ),
                current_user=self.user,
            )
        self.assertEqual(conflict.exception.status_code, 409)

    def test_cross_project_environment_and_navigation_host_are_rejected(self):
        with self.assertRaises(HTTPException) as cross_project:
            self.case_service.create_case(
                project_id=self.project.id,
                payload=UiTestCaseCreateRequest(
                    name="Wrong env",
                    default_environment_id=self.other_environment.id,
                    dsl=UiCaseDsl.model_validate(flat_dsl()),
                ),
                current_user=self.user,
            )
        self.assertEqual(cross_project.exception.status_code, 404)

        hostile = flat_dsl()
        hostile["steps"][0]["input_value"] = "https://evil.example.net/login"
        with self.assertRaises(HTTPException) as host_error:
            self.case_service.create_case(
                project_id=self.project.id,
                payload=UiTestCaseCreateRequest(
                    name="Wrong host",
                    default_environment_id=self.environment.id,
                    dsl=UiCaseDsl.model_validate(hostile),
                ),
                current_user=self.user,
            )
        self.assertEqual(host_error.exception.status_code, 422)

    def test_loopback_navigation_alias_matches_loopback_environment(self):
        self.environment.base_url = "http://127.0.0.1:8000/api/v1"
        self.db.commit()
        local_ui = flat_dsl()
        local_ui["steps"][0]["input_value"] = "http://localhost:5174/login"

        validation = self.case_service.validate_unsaved(
            project_id=self.project.id,
            default_environment_id=self.environment.id,
            dsl=UiCaseDsl.model_validate(local_ui),
            current_user=self.user,
        )

        self.assertTrue(validation.valid)
        self.assertEqual(validation.step_count, 1)

    def test_non_member_permissions_and_cross_project_execution_environment_are_rejected(self):
        outsider = User(
            username="ui-outsider",
            account="ui-outsider",
            password_hash="hash",
            phone="18800002003",
            email="ui-outsider@example.com",
        )
        self.db.add(outsider)
        self.db.commit()
        with self.assertRaises(HTTPException) as forbidden:
            self.case_service.list_cases(
                project_id=self.project.id,
                keyword=None,
                case_status=None,
                environment_id=None,
                page=1,
                page_size=20,
                current_user=outsider,
            )
        self.assertEqual(forbidden.exception.status_code, 403)

        created = self.create_case()
        with self.assertRaises(HTTPException) as cross_project:
            self.execution_service.create_execution(
                project_id=self.project.id,
                case_public_id=created.case_id,
                payload=UiExecutionCreateRequest(
                    client_request_id="cross-project-env-001",
                    version=1,
                    environment_id=self.other_environment.id,
                ),
                current_user=self.user,
            )
        self.assertEqual(cross_project.exception.status_code, 404)

    def test_metadata_update_does_not_mutate_current_version(self):
        created = self.create_case()
        updated = self.case_service.update_case(
            case_public_id=created.case_id,
            payload=UiTestCaseUpdateRequest(name="Renamed UI"),
            current_user=self.user,
        )

        self.assertEqual(updated.name, "Renamed UI")
        self.assertEqual(updated.current_version, 1)
        self.assertEqual(self.db.query(UiTestCaseVersion).count(), 1)

    def test_execution_creation_snapshots_case_is_idempotent_and_projects_to_unified_index(self):
        created = self.create_case(secret=True)
        request = UiExecutionCreateRequest(
            client_request_id="desktop-request-001",
            version=1,
            environment_id=self.environment.id,
        )

        accepted, notified_device, first_replay = self.execution_service.create_execution(
            project_id=self.project.id,
            case_public_id=created.case_id,
            payload=request,
            current_user=self.user,
        )
        replay, replay_device, second_replay = self.execution_service.create_execution(
            project_id=self.project.id,
            case_public_id=created.case_id,
            payload=request,
            current_user=self.user,
        )

        self.assertTrue(accepted.execution_id.startswith("ui_exec_"))
        self.assertFalse(first_replay)
        self.assertTrue(second_replay)
        self.assertEqual(replay.execution_id, accepted.execution_id)
        self.assertIsNone(notified_device)
        self.assertIsNone(replay_device)
        self.assertEqual(self.db.query(UiExecution).count(), 1)
        self.assertEqual(self.db.query(ExecutionRecordIndex).count(), 1)

        execution = self.db.scalar(select(UiExecution))
        snapshot_text = str(execution.case_snapshot_json)
        self.assertNotIn("encrypted-value-must-not-enter-snapshot", snapshot_text)
        self.assertEqual(execution.required_secret_refs_json, ["password"])
        self.assertEqual(
            execution.case_snapshot_json["environment"]["variables"],
            {"tenant": "qa"},
        )

        rows, total = ExecutionRecordRepository(self.db).list_records(
            project_id=self.project.id,
            execution_type="ui",
            status=None,
            environment_id=None,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            page=1,
            page_size=20,
        )
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["execution_type"], "ui")

        self.execution_service.create_execution(
            project_id=self.project.id,
            case_public_id=created.case_id,
            payload=request.model_copy(update={"client_request_id": "desktop-request-001-b"}),
            current_user=self.user,
        )
        cursor_page = ExecutionRecordService(self.db).list_records_cursor(
            project_id=self.project.id,
            current_user=self.user,
            execution_type="ui",
            status_filter="running",
            environment_id=None,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            cursor=None,
            limit=1,
            include_total=True,
        )
        self.assertEqual(cursor_page.total, 2)
        self.assertTrue(cursor_page.has_more)
        self.assertEqual(cursor_page.items[0].execution_type, "ui")
        next_page = ExecutionRecordService(self.db).list_records_cursor(
            project_id=self.project.id,
            current_user=self.user,
            execution_type="ui",
            status_filter="running",
            environment_id=None,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            cursor=cursor_page.next_cursor,
            limit=1,
            include_total=False,
        )
        self.assertEqual(len(next_page.items), 1)

    def test_unassigned_execution_notifies_all_compatible_accepting_project_devices(self):
        compatible = DesktopDevice(
            public_id="dev_notification_compatible",
            owner_id=self.user.id,
            installation_id_hash="notification-compatible-hash",
            name="Compatible Desktop",
            registration_status="active",
            accepting_jobs=True,
            concurrency_limit=1,
            desktop_version="0.3.0-dev",
            os_name="Windows",
            os_version="11",
            architecture="x86_64",
            supported_protocols_json={
                "dsl": ["ui-case-v1"],
                "ipc": ["desktop-ipc-v1"],
            },
            capabilities_json={"browsers": ["chromium"]},
            runtime_state_json={},
        )
        incompatible = DesktopDevice(
            public_id="dev_notification_incompatible",
            owner_id=self.user.id,
            installation_id_hash="notification-incompatible-hash",
            name="Legacy Desktop",
            registration_status="active",
            accepting_jobs=True,
            concurrency_limit=1,
            desktop_version="0.1.0",
            os_name="Windows",
            os_version="11",
            architecture="x86_64",
            supported_protocols_json={"dsl": ["ui-case-v1"], "ipc": ["legacy-ipc"]},
            capabilities_json={"browsers": ["chromium"]},
            runtime_state_json={},
        )
        self.db.add_all([compatible, incompatible])
        self.db.flush()
        for device in (compatible, incompatible):
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

        targets = _execution_notification_targets(
            self.db,
            project_id=self.project.id,
            requested_device_id=None,
        )

        self.assertEqual(targets, [compatible.public_id])
        self.assertEqual(
            _execution_notification_targets(
                self.db,
                project_id=self.project.id,
                requested_device_id="dev_requested",
            ),
            ["dev_requested"],
        )

    def test_execution_client_request_payload_conflict_and_inactive_case(self):
        active = self.create_case()
        request = UiExecutionCreateRequest(
            client_request_id="desktop-request-002",
            version=1,
            environment_id=self.environment.id,
        )
        self.execution_service.create_execution(
            project_id=self.project.id,
            case_public_id=active.case_id,
            payload=request,
            current_user=self.user,
        )
        with self.assertRaises(HTTPException) as idempotency_conflict:
            self.execution_service.create_execution(
                project_id=self.project.id,
                case_public_id=active.case_id,
                payload=request.model_copy(update={"source": "local_debug"}),
                current_user=self.user,
            )
        self.assertEqual(idempotency_conflict.exception.status_code, 409)

        draft = self.create_case(active=False)
        with self.assertRaises(HTTPException) as inactive:
            self.execution_service.create_execution(
                project_id=self.project.id,
                case_public_id=draft.case_id,
                payload=request.model_copy(update={"client_request_id": "draft-request"}),
                current_user=self.user,
            )
        self.assertEqual(inactive.exception.status_code, 409)

    def test_requested_device_must_be_active_accepting_and_bound_to_project(self):
        created = self.create_case()
        device = DesktopDevice(
            public_id="dev_requested",
            owner_id=self.user.id,
            installation_id_hash="a" * 64,
            name="QA Desktop",
            desktop_version="0.2.0",
            os_name="Windows",
            os_version="11",
            architecture="x86_64",
            supported_protocols_json={"dsl": ["ui-case-v1"]},
            capabilities_json={"browsers": ["chromium"]},
            runtime_state_json={},
        )
        self.db.add(device)
        self.db.flush()
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

        accepted, notify_device, idempotent_replay = self.execution_service.create_execution(
            project_id=self.project.id,
            case_public_id=created.case_id,
            payload=UiExecutionCreateRequest(
                client_request_id="requested-device-001",
                version=1,
                environment_id=self.environment.id,
                requested_device_id=device.public_id,
            ),
            current_user=self.user,
        )
        self.assertEqual(notify_device, device.public_id)
        self.assertFalse(idempotent_replay)
        self.assertEqual(accepted.delivery_status, "pending")

        device.accepting_jobs = False
        self.db.commit()
        with self.assertRaises(HTTPException) as unavailable:
            self.execution_service.create_execution(
                project_id=self.project.id,
                case_public_id=created.case_id,
                payload=UiExecutionCreateRequest(
                    client_request_id="requested-device-002",
                    version=1,
                    environment_id=self.environment.id,
                    requested_device_id=device.public_id,
                ),
                current_user=self.user,
            )
        self.assertEqual(unavailable.exception.status_code, 409)

    def test_environment_and_project_physical_deletion_clean_ui_references(self):
        created = self.create_case()
        accepted, _, _ = self.execution_service.create_execution(
            project_id=self.project.id,
            case_public_id=created.case_id,
            payload=UiExecutionCreateRequest(
                client_request_id="delete-lifecycle-001",
                version=1,
                environment_id=self.environment.id,
            ),
            current_user=self.user,
        )
        case_model = self.db.scalar(select(UiTestCase))
        execution = self.db.scalar(
            select(UiExecution).where(UiExecution.public_id == accepted.execution_id)
        )

        ProjectRepository(self.db).delete_environment(self.environment)
        self.db.refresh(case_model)
        self.db.refresh(execution)
        self.assertIsNone(case_model.default_environment_id)
        self.assertIsNone(execution.environment_id)
        self.assertIsNone(self.db.scalar(select(ExecutionRecordIndex)).environment_id)

        ProjectRepository(self.db).delete_project(self.project)
        self.assertEqual(self.db.query(UiExecution).count(), 0)
        self.assertEqual(self.db.query(UiTestCaseVersion).count(), 0)
        self.assertEqual(self.db.query(UiTestCase).count(), 0)
        self.assertIsNotNone(self.db.get(Project, self.other_project.id))


class UiTestCaseApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        db = self.session_factory()
        self.user = User(
            username="ui-api-admin",
            account="ui-api-admin",
            password_hash="hash",
            phone="18800002002",
            email="ui-api-admin@example.com",
            is_admin=True,
        )
        db.add(self.user)
        db.flush()
        project = Project(name="UI API project", created_by_id=self.user.id)
        db.add(project)
        db.flush()
        environment = ProjectEnvironment(
            project_id=project.id,
            name="Test",
            base_url="https://test.example.com",
            created_by_id=self.user.id,
        )
        db.add(environment)
        db.commit()
        self.project_id = project.id
        self.environment_id = environment.id
        db.close()

        application = FastAPI()
        application.include_router(ui_test_cases.router, prefix="/ui-test-cases")

        def override_db():
            session = self.session_factory()
            try:
                yield session
            finally:
                session.close()

        application.dependency_overrides[get_db] = override_db
        application.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(application)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_create_get_version_and_execute_http_contract(self):
        created = self.client.post(
            f"/ui-test-cases?project_id={self.project_id}",
            json={
                "name": "HTTP UI case",
                "status": "active",
                "default_environment_id": self.environment_id,
                "dsl": flat_dsl(),
            },
        )
        self.assertEqual(created.status_code, 201)
        case_id = created.json()["data"]["case_id"]

        version = self.client.get(f"/ui-test-cases/{case_id}/versions/1")
        self.assertEqual(version.status_code, 200)
        self.assertEqual(version.json()["data"]["version"], 1)

        execution = self.client.post(
            f"/ui-test-cases/{case_id}/execute?project_id={self.project_id}",
            json={
                "client_request_id": "api-execution-001",
                "version": 1,
                "environment_id": self.environment_id,
            },
        )
        self.assertEqual(execution.status_code, 202)
        self.assertEqual(execution.json()["message"], "UI execution accepted")
        self.assertTrue(execution.json()["data"]["execution_id"].startswith("ui_exec_"))


class UiTestCaseContractTests(unittest.TestCase):
    def test_execution_available_control_message_matches_desktop_contract(self):
        message = ui_test_cases._execution_available_message(
            device_id="desktop_qa_1",
            execution_id="ui_exec_1",
        )

        self.assertEqual(message["schema_version"], "desktop-control-v1")
        self.assertEqual(message["type"], "execution.available")
        self.assertEqual(message["device_id"], "desktop_qa_1")
        self.assertEqual(message["execution_id"], "ui_exec_1")
        self.assertEqual(message["authoritative_transport"], "rest")

    def test_migrations_are_linear_and_additive(self):
        migration_47 = importlib.import_module("migrations.versions.0047_ui_test_cases")
        migration_48 = importlib.import_module(
            "migrations.versions.0048_ui_execution_runtime"
        )

        self.assertEqual(migration_47.down_revision, "0046_desktop_devices")
        self.assertEqual(migration_48.down_revision, "0047_ui_test_cases")
        self.assertNotIn("drop_table", inspect.getsource(migration_47.upgrade))
        self.assertNotIn("drop_table", inspect.getsource(migration_48.upgrade))

    def test_routes_and_202_contract_are_registered(self):
        routes = {
            (route.path, method): route.status_code
            for route in api_router.routes
            for method in getattr(route, "methods", set())
        }
        self.assertEqual(routes[("/ui-test-cases", "POST")], 201)
        self.assertEqual(routes[("/ui-test-cases/{case_id}/versions", "POST")], 201)
        self.assertEqual(routes[("/ui-test-cases/{case_id}/execute", "POST")], 202)


if __name__ == "__main__":
    unittest.main()
