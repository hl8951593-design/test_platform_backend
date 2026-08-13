import importlib
import inspect
import unittest
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

import app.models  # noqa: F401
from app.api.v1.deps import get_current_user, get_db
from app.api.v1.api import api_router
from app.api.v1.routers import desktop_devices
from app.api.v1.routers.desktop_devices import (
    _control_message,
    _handle_control_message,
)
from app.core.security import create_access_token
from app.db.base import Base
from app.models.desktop_device import (
    DesktopDevice,
    DesktopDeviceCredential,
    DesktopDeviceProjectBinding,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.desktop_device import (
    DesktopDeviceHeartbeatRequest,
    DesktopDeviceProjectBindingUpdateRequest,
    DesktopDeviceRegisterRequest,
    DesktopDeviceUpdateRequest,
)
from app.services.desktop_control_hub import DesktopControlHub
from app.services.desktop_device_service import DesktopDeviceService


class FakePresenceService:
    def __init__(self):
        self.devices: dict[str, dict] = {}

    def mark_online(self, *, device_public_id, observed_at, runtime_state):
        self.devices[device_public_id] = {
            "observed_at": observed_at,
            "runtime_state": runtime_state,
        }
        return True

    def is_online(self, device_public_id):
        return device_public_id in self.devices

    def forget(self, device_public_id):
        self.devices.pop(device_public_id, None)


class DesktopDeviceServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            username="desktop-owner",
            account="desktop-owner",
            password_hash="hash",
            phone="18800001001",
            email="desktop-owner@example.com",
        )
        self.other_user = User(
            username="other-user",
            account="other-user",
            password_hash="hash",
            phone="18800001002",
            email="other-user@example.com",
        )
        self.db.add_all([self.user, self.other_user])
        self.db.flush()
        self.project = Project(
            name="Desktop project",
            created_by_id=self.user.id,
        )
        self.db.add(self.project)
        self.db.commit()
        self.presence = FakePresenceService()
        self.service = DesktopDeviceService(
            self.db,
            presence_service=self.presence,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def register(self, *, installation_id="installation-0000000001"):
        return self.service.register_device(
            payload=DesktopDeviceRegisterRequest(
                installation_id=installation_id,
                name="DESKTOP-QA-01",
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

    def test_registration_uses_public_id_and_hashed_rotatable_credential(self):
        registered = self.register()

        self.assertTrue(registered.device.device_id.startswith("dev_"))
        self.assertFalse(registered.device.online)
        credential = self.db.scalar(select(DesktopDeviceCredential))
        self.assertIsNotNone(credential)
        self.assertEqual(len(credential.refresh_secret_hash), 64)
        self.assertNotIn(
            registered.credential.refresh_token,
            credential.refresh_secret_hash,
        )

        rotated = self.service.refresh_device_credential(
            registered.credential.refresh_token
        )
        self.assertNotEqual(
            registered.credential.refresh_token,
            rotated.refresh_token,
        )
        with self.assertRaises(HTTPException) as error:
            self.service.refresh_device_credential(
                registered.credential.refresh_token
            )
        self.assertEqual(error.exception.status_code, 401)

    def test_same_installation_reregistration_keeps_device_and_revokes_old_token(self):
        first = self.register()
        second = self.register()

        self.assertEqual(first.device.device_id, second.device.device_id)
        self.assertEqual(self.db.query(DesktopDevice).count(), 1)
        self.assertEqual(self.db.query(DesktopDeviceCredential).count(), 2)
        with self.assertRaises(HTTPException):
            self.service.authenticate_device_access_token(
                first.credential.access_token
            )
        principal = self.service.authenticate_device_access_token(
            second.credential.access_token
        )
        self.assertEqual(principal.device.public_id, second.device.device_id)

    def test_user_access_token_is_not_a_device_access_token(self):
        with self.assertRaises(HTTPException) as error:
            self.service.authenticate_device_access_token(
                create_access_token(self.user.id)
            )
        self.assertEqual(error.exception.status_code, 401)

    def test_device_access_token_authentication_uses_one_query(self):
        registered = self.register()
        statements = []

        def record_statement(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            principal = self.service.authenticate_device_access_token(
                registered.credential.access_token
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(principal.owner.id, self.user.id)
        self.assertEqual(len(statements), 1)

    def test_project_binding_is_opt_in_and_owner_scoped(self):
        registered = self.register()
        self.assertEqual(
            self.service.list_devices(
                current_user=self.user,
                project_id=self.project.id,
            ),
            [],
        )

        device = self.service.bind_project(
            device_public_id=registered.device.device_id,
            project_id=self.project.id,
            payload=DesktopDeviceProjectBindingUpdateRequest(
                enabled=True,
                accepting_jobs=True,
                concurrency_limit=2,
            ),
            current_user=self.user,
        )
        self.assertEqual(device.project_bindings[0].project_id, self.project.id)
        self.assertEqual(self.db.query(DesktopDeviceProjectBinding).count(), 1)
        self.assertEqual(
            len(
                self.service.list_devices(
                    current_user=self.user,
                    project_id=self.project.id,
                )
            ),
            1,
        )

        with self.assertRaises(HTTPException) as error:
            self.service.update_device(
                device_public_id=registered.device.device_id,
                payload=DesktopDeviceUpdateRequest(name="stolen"),
                current_user=self.other_user,
            )
        self.assertEqual(error.exception.status_code, 403)

    def test_heartbeat_marks_presence_and_applies_runtime_compatibility(self):
        registered = self.register()
        principal = self.service.authenticate_device_access_token(
            registered.credential.access_token
        )
        heartbeat = self.service.heartbeat(
            principal=principal,
            payload=DesktopDeviceHeartbeatRequest(
                desktop_version="0.0.9",
                supported_protocols={"dsl": ["ui-case-v1"]},
                capabilities={"browsers": []},
                active_execution_ids=["ui_exec_1"],
                local_outbox_events=3,
                current_load=1,
            ),
        )

        self.assertFalse(heartbeat.runtime_compatible)
        self.assertFalse(heartbeat.accepting_jobs)
        detail = self.service.get_device(
            device_public_id=registered.device.device_id,
            current_user=self.user,
        )
        self.assertTrue(detail.online)
        self.assertEqual(detail.runtime_state["active_execution_ids"], ["ui_exec_1"])
        self.assertIsInstance(detail.last_heartbeat_at, datetime)

    def test_revocation_invalidates_credential_and_presence(self):
        registered = self.register()
        principal = self.service.authenticate_device_access_token(
            registered.credential.access_token
        )
        self.service.heartbeat(
            principal=principal,
            payload=DesktopDeviceHeartbeatRequest(desktop_version="0.1.0"),
        )
        self.service.revoke_device(
            device_public_id=registered.device.device_id,
            current_user=self.user,
        )

        self.assertNotIn(registered.device.device_id, self.presence.devices)
        with self.assertRaises(HTTPException) as error:
            self.service.authenticate_device_access_token(
                registered.credential.access_token
            )
        self.assertEqual(error.exception.status_code, 401)

    def test_runtime_policy_exposes_supported_contract_versions(self):
        policy = self.service.get_runtime_policy()

        self.assertIn("ui-case-v1", policy.supported_dsl_versions)
        self.assertIn("desktop-ipc-v1", policy.supported_ipc_versions)
        self.assertGreater(policy.offline_after_seconds, policy.heartbeat_interval_seconds)


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.closed = False

    async def accept(self):
        return None

    async def send_json(self, message):
        self.messages.append(message)

    async def close(self, code=1000):
        self.closed = True


class DesktopControlProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_and_resync_messages_use_versioned_envelope(self):
        websocket = FakeWebSocket()

        await _handle_control_message(
            websocket=websocket,
            device_id="dev_1",
            incoming={"type": "control.ping", "message_id": "request_1"},
        )
        await _handle_control_message(
            websocket=websocket,
            device_id="dev_1",
            incoming={"type": "control.resync", "message_id": "request_2"},
        )

        self.assertEqual(websocket.messages[0]["type"], "control.pong")
        self.assertEqual(websocket.messages[0]["reply_to"], "request_1")
        self.assertEqual(
            websocket.messages[1]["authoritative_transport"],
            "rest",
        )
        self.assertEqual(websocket.messages[1]["schema_version"], "desktop-control-v1")

    async def test_control_hub_routes_only_to_target_device(self):
        hub = DesktopControlHub()
        target = FakeWebSocket()
        other = FakeWebSocket()
        await hub.connect("dev_target", target)
        await hub.connect("dev_other", other)

        message = _control_message("execution.available", device_id="dev_target")
        await hub.send_local("dev_target", message)

        self.assertEqual(target.messages, [message])
        self.assertEqual(other.messages, [])


class DesktopDeviceContractTests(unittest.TestCase):
    def test_migration_is_additive_and_points_to_0045(self):
        migration = importlib.import_module(
            "migrations.versions.0046_desktop_devices"
        )

        self.assertEqual(migration.down_revision, "0045_database_test_actions")
        upgrade_source = inspect.getsource(migration.upgrade)
        for table_name in (
            "desktop_devices",
            "desktop_device_credentials",
            "desktop_device_project_bindings",
        ):
            self.assertIn(table_name, upgrade_source)
        self.assertNotIn("drop_table", upgrade_source)

    def test_rest_and_websocket_routes_are_registered(self):
        paths = {route.path for route in api_router.routes}
        control_paths = {route.path for route in desktop_devices.control_router.routes}

        self.assertIn("/desktop/devices/register", paths)
        self.assertIn("/desktop/devices/{device_id}/heartbeat", paths)
        self.assertIn("/devices/{device_id}/control", control_paths)


class DesktopDeviceApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        db = self.session_factory()
        self.user = User(
            username="api-owner",
            account="api-owner",
            password_hash="hash",
            phone="18800001003",
            email="api-owner@example.com",
        )
        db.add(self.user)
        db.commit()
        db.refresh(self.user)
        db.close()

        application = FastAPI()
        application.include_router(desktop_devices.router, prefix="/desktop")
        application.include_router(
            desktop_devices.control_router,
            prefix="/desktop",
        )

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

    def register(self):
        response = self.client.post(
            "/desktop/devices/register",
            json={
                "installation_id": "api-installation-00000001",
                "name": "DESKTOP-API-01",
                "desktop_version": "0.1.0",
                "os_name": "Windows",
                "os_version": "11",
                "architecture": "x86_64",
                "supported_protocols": {"dsl": ["ui-case-v1"]},
                "capabilities": {"browsers": ["chromium"]},
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]

    def test_register_refresh_and_heartbeat_http_contract(self):
        registered = self.register()
        device_id = registered["device"]["device_id"]
        credential = registered["credential"]

        heartbeat = self.client.post(
            f"/desktop/devices/{device_id}/heartbeat",
            headers={"Authorization": f"Bearer {credential['access_token']}"},
            json={
                "desktop_version": "0.1.0",
                "active_execution_ids": [],
            },
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(heartbeat.json()["data"]["runtime_compatible"])

        refreshed = self.client.post(
            "/desktop/devices/token/refresh",
            json={"refresh_token": credential["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(
            refreshed.json()["data"]["refresh_token"],
            credential["refresh_token"],
        )

    def test_control_websocket_requires_device_token_and_supports_ping(self):
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect(
                "/desktop/devices/dev_missing/control"
            ):
                pass
        self.assertEqual(error.exception.code, 4401)

        registered = self.register()
        device_id = registered["device"]["device_id"]
        access_token = registered["credential"]["access_token"]
        with self.client.websocket_connect(
            f"/desktop/devices/{device_id}/control",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as websocket:
            ready = websocket.receive_json()
            self.assertEqual(ready["type"], "control.ready")
            websocket.send_json(
                {"type": "control.ping", "message_id": "api_ping_1"}
            )
            pong = websocket.receive_json()
            self.assertEqual(pong["type"], "control.pong")
            self.assertEqual(pong["reply_to"], "api_ping_1")


if __name__ == "__main__":
    unittest.main()
