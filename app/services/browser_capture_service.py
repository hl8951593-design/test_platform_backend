from fastapi import HTTPException, status
from sqlalchemy import insert, or_, select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.browser_capture import BrowserCapture, BrowserCaptureEntry
from app.models.project import ProjectEnvironment
from app.models.user import User
from app.schemas.browser_capture import BrowserCaptureCreateRequest, BrowserCaptureEntryBatchRequest, BrowserCaptureEntryUpdateRequest, BrowserCaptureImportRequest, BrowserCaptureUpdateRequest
from app.schemas.scenario import ScenarioCreateRequest
from app.schemas.test_case import TestCaseCreateRequest
from app.schemas.websocket_test_case import WebSocketTestCaseCreateRequest
from app.services.permission_service import PermissionService
from app.services.scenario_service import ScenarioService
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class BrowserCaptureService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_captures(self, *, project_id: int, current_user: User):
        self._require_view(project_id, current_user)
        return list(self.db.scalars(select(BrowserCapture).where(
            BrowserCapture.project_id == project_id, BrowserCapture.is_deleted.is_(False)
        ).order_by(BrowserCapture.id.desc())).all())

    def create_capture(self, *, project_id: int, payload: BrowserCaptureCreateRequest, current_user: User):
        self._require_manage(project_id, current_user)
        self._require_environment(project_id, payload.environment_id)
        capture = BrowserCapture(project_id=project_id, environment_id=payload.environment_id, name=payload.name.strip(),
                                 source_url=payload.source_url, created_by_id=current_user.id)
        self.db.add(capture)
        self.db.commit()
        self.db.refresh(capture)
        return capture

    def update_capture(self, *, project_id: int, capture_id: int, payload: BrowserCaptureUpdateRequest, current_user: User):
        self._require_manage(project_id, current_user)
        capture = self._capture_or_404(project_id, capture_id)
        if payload.name is not None:
            capture.name = payload.name.strip()
        if payload.status is not None:
            capture.status = payload.status
        self.db.commit()
        self.db.refresh(capture)
        return capture

    def delete_capture(self, *, project_id: int, capture_id: int, current_user: User):
        self._require_manage(project_id, current_user)
        capture = self._capture_or_404(project_id, capture_id)
        capture.is_deleted = True
        self.db.commit()

    def list_entries(
        self,
        *,
        project_id: int,
        capture_id: int,
        current_user: User,
        status_filter: str | None = None,
        protocol: str | None = None,
        method: str | None = None,
        domain: str | None = None,
        keyword: str | None = None,
    ):
        self._require_view(project_id, current_user)
        self._capture_or_404(project_id, capture_id)
        conditions = [
            BrowserCaptureEntry.project_id == project_id,
            BrowserCaptureEntry.capture_id == capture_id,
        ]
        if status_filter:
            conditions.append(BrowserCaptureEntry.status == status_filter)
        if protocol:
            conditions.append(BrowserCaptureEntry.protocol == protocol.lower())
        if method:
            conditions.append(BrowserCaptureEntry.method == method.upper())
        if domain:
            conditions.append(BrowserCaptureEntry.source_url.ilike(f"%{domain.strip()}%"))
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(or_(
                BrowserCaptureEntry.name.ilike(pattern),
                BrowserCaptureEntry.path.ilike(pattern),
                BrowserCaptureEntry.source_url.ilike(pattern),
            ))
        return list(self.db.scalars(select(BrowserCaptureEntry).where(
            *conditions
        ).order_by(BrowserCaptureEntry.id.desc())).all())

    def get_entry(self, *, project_id: int, capture_id: int, entry_id: int, current_user: User, manage: bool = False):
        (self._require_manage if manage else self._require_view)(project_id, current_user)
        self._capture_or_404(project_id, capture_id)
        entry = self.db.scalar(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.project_id == project_id, BrowserCaptureEntry.capture_id == capture_id,
            BrowserCaptureEntry.id == entry_id,
        ))
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集草稿不存在")
        return entry

    def upsert_entries(self, *, project_id: int, capture_id: int, payload: BrowserCaptureEntryBatchRequest, current_user: User):
        self._require_manage(project_id, current_user)
        capture = self._capture_or_404(project_id, capture_id)
        requested_ids = [entry.client_entry_id for entry in payload.entries]
        existing = {item.client_entry_id: item for item in self.db.scalars(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.capture_id == capture_id,
            BrowserCaptureEntry.client_entry_id.in_(requested_ids),
        )).all()}
        new_values = []
        for entry_payload in payload.entries:
            values = entry_payload.model_dump()
            entry = existing.get(entry_payload.client_entry_id)
            if entry is None:
                new_values.append({
                    "capture_id": capture_id,
                    "project_id": project_id,
                    **values,
                })
            else:
                for key, value in values.items():
                    setattr(entry, key, value)
        if new_values:
            self.db.execute(insert(BrowserCaptureEntry), new_values)
        capture.status = "reviewing"
        self.db.commit()
        persisted = list(self.db.scalars(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.capture_id == capture_id,
            BrowserCaptureEntry.client_entry_id.in_(requested_ids),
        )).all())
        persisted_by_client_id = {entry.client_entry_id: entry for entry in persisted}
        return [persisted_by_client_id[client_id] for client_id in requested_ids]

    def update_entry(self, *, project_id: int, capture_id: int, entry_id: int, payload: BrowserCaptureEntryUpdateRequest, current_user: User):
        entry = self.get_entry(project_id=project_id, capture_id=capture_id, entry_id=entry_id, current_user=current_user, manage=True)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entry, key, value)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def import_entries(self, *, project_id: int, capture_id: int, payload: BrowserCaptureImportRequest, current_user: User):
        self._require_import(project_id, current_user)
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.MANAGE_CASE.value
        )
        self._require_environment(project_id, payload.environment_id)
        self._capture_or_404(project_id, capture_id)
        entries = self._entries_by_id(project_id=project_id, capture_id=capture_id, entry_ids=payload.entry_ids)

        results = []
        imported_assets = []
        for entry_id in payload.entry_ids:
            entry = entries.get(entry_id)
            if entry is None:
                results.append({"entry_id": entry_id, "ok": False, "status": "failed", "error": "采集草稿不存在"})
                continue
            if self._is_imported_duplicate(entry):
                result = {
                    "entry_id": entry.id,
                    "ok": False,
                    "status": "duplicate",
                    "asset_type": entry.import_result.get("asset_type"),
                    "asset_id": entry.import_result.get("asset_id"),
                    "message": "采集草稿已导入正式资产",
                }
                results.append(result)
                continue
            try:
                created = self._create_asset_from_entry(
                    project_id=project_id,
                    environment_id=payload.environment_id,
                    entry=entry,
                    current_user=current_user,
                )
                result = {
                    "entry_id": entry.id,
                    "ok": True,
                    "status": "success",
                    "asset_type": created["asset_type"],
                    "asset_id": created["asset_id"],
                    "name": created["name"],
                }
                entry.status = "imported"
                entry.import_result = result
                imported_assets.append(created)
                results.append(result)
            except HTTPException as exc:
                self.db.rollback()
                results.append({"entry_id": entry.id, "ok": False, "status": "failed", "error": str(exc.detail)})
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                results.append({"entry_id": entry.id, "ok": False, "status": "failed", "error": str(exc)})

        self.db.commit()
        scenario_result = None
        if payload.create_scenario and imported_assets:
            scenario_result = self._create_scenario_from_assets(
                project_id=project_id,
                capture_id=capture_id,
                environment_id=payload.environment_id,
                imported_assets=imported_assets,
                current_user=current_user,
            )
        return {
            "capture_id": capture_id,
            "environment_id": payload.environment_id,
            "scenario_draft_id": payload.scenario_draft_id,
            "create_environment_variables": payload.create_environment_variables,
            "environment_variables_created": 0,
            "results": results,
            "success_count": sum(1 for item in results if item["status"] == "success"),
            "failure_count": sum(1 for item in results if item["status"] == "failed"),
            "duplicate_count": sum(1 for item in results if item["status"] == "duplicate"),
            "scenario": scenario_result,
        }

    def _capture_or_404(self, project_id: int, capture_id: int):
        capture = self.db.scalar(select(BrowserCapture).where(
            BrowserCapture.id == capture_id, BrowserCapture.project_id == project_id, BrowserCapture.is_deleted.is_(False)
        ))
        if capture is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集批次不存在")
        return capture

    def _require_environment(self, project_id: int, environment_id: int):
        if self.db.scalar(select(ProjectEnvironment.id).where(
            ProjectEnvironment.id == environment_id, ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        )) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

    def _require_view(self, project_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.VIEW_CAPTURE.value)

    def _require_manage(self, project_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.MANAGE_CAPTURE.value)

    def _require_import(self, project_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.IMPORT_CAPTURE.value)

    def _entries_by_id(self, *, project_id: int, capture_id: int, entry_ids: list[int]) -> dict[int, BrowserCaptureEntry]:
        rows = self.db.scalars(select(BrowserCaptureEntry).where(
            BrowserCaptureEntry.project_id == project_id,
            BrowserCaptureEntry.capture_id == capture_id,
            BrowserCaptureEntry.id.in_(list(dict.fromkeys(entry_ids))),
        )).all()
        return {entry.id: entry for entry in rows}

    def _is_imported_duplicate(self, entry: BrowserCaptureEntry) -> bool:
        return (
            entry.status == "imported"
            and isinstance(entry.import_result, dict)
            and entry.import_result.get("status") == "success"
            and entry.import_result.get("asset_id") is not None
        )

    def _create_asset_from_entry(
        self,
        *,
        project_id: int,
        environment_id: int,
        entry: BrowserCaptureEntry,
        current_user: User,
    ) -> dict:
        if entry.protocol == "websocket":
            payload = self._websocket_payload_from_entry(entry=entry, environment_id=environment_id)
            test_case = WebSocketTestCaseService(self.db).create_case(
                project_id=project_id,
                payload=payload,
                current_user=current_user,
            )
            return {"asset_type": "websocket", "asset_id": test_case.id, "name": test_case.name}
        payload = self._http_payload_from_entry(entry=entry, environment_id=environment_id)
        test_case = TestCaseService(self.db).create_case(
            project_id=project_id,
            payload=payload,
            current_user=current_user,
        )
        return {"asset_type": "http", "asset_id": test_case.id, "name": test_case.name}

    def _http_payload_from_entry(self, *, entry: BrowserCaptureEntry, environment_id: int) -> TestCaseCreateRequest:
        request_data = entry.request_data or {}
        draft_data = entry.draft_data or {}
        response_data = entry.response_data or {}
        assertions = list(draft_data.get("assertions") or [])
        status_code = response_data.get("status_code")
        if isinstance(status_code, int) and not any(item.get("type") == "status_code" for item in assertions if isinstance(item, dict)):
            assertions.insert(0, {"type": "status_code", "expected": status_code})
        return TestCaseCreateRequest(
            environment_id=environment_id,
            environment_ids=[environment_id],
            name=entry.name[:128],
            description=f"由浏览器采集批次 {entry.capture_id} 导入",
            method=entry.method.upper(),
            path=entry.path[:512],
            headers=request_data.get("headers") or {},
            query_params=request_data.get("query_params") or None,
            body_type=self._http_body_type(request_data.get("body_type")),
            body=request_data.get("body"),
            assertions=assertions,
            extractors=list(draft_data.get("extractors") or []),
        )

    def _websocket_payload_from_entry(self, *, entry: BrowserCaptureEntry, environment_id: int) -> WebSocketTestCaseCreateRequest:
        request_data = entry.request_data or {}
        draft_data = entry.draft_data or {}
        return WebSocketTestCaseCreateRequest(
            environment_id=environment_id,
            environment_ids=[environment_id],
            name=entry.name[:128],
            description=f"由浏览器采集批次 {entry.capture_id} 导入",
            path=entry.path[:512],
            headers=request_data.get("headers") or {},
            subprotocols=list(draft_data.get("subprotocols") or []),
            messages=list(draft_data.get("messages") or []),
            receive_count=int(draft_data.get("receive_count") or 1),
            assertions=list(draft_data.get("assertions") or []),
            extractors=list(draft_data.get("extractors") or []),
        )

    def _create_scenario_from_assets(
        self,
        *,
        project_id: int,
        capture_id: int,
        environment_id: int,
        imported_assets: list[dict],
        current_user: User,
    ) -> dict:
        try:
            scenario = ScenarioService(self.db).create_scenario(
                project_id=project_id,
                payload=ScenarioCreateRequest(
                    name=f"浏览器采集场景 #{capture_id}",
                    description="由浏览器插件采集导入后自动生成。",
                    environment_id=environment_id,
                    tags=["browser-capture"],
                    nodes=[
                        {
                            "id": f"NODE-{index}",
                            "name": asset["name"],
                            "test_case": {
                                "id": f"STEP-{index}",
                                "kind": "websocket_case" if asset["asset_type"] == "websocket" else "api_case",
                                "reference_id": asset["asset_id"],
                                "name": asset["name"],
                            },
                        }
                        for index, asset in enumerate(imported_assets, start=1)
                    ],
                ),
                current_user=current_user,
            )
            return {"ok": True, "scenario_id": scenario["id"], "name": scenario["name"]}
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            return {"ok": False, "error": str(getattr(exc, "detail", exc))}

    def _http_body_type(self, value: str | None) -> str:
        allowed = {"none", "json", "form_urlencoded", "multipart", "raw_text", "raw_json"}
        normalized = (value or "json").strip().lower()
        return normalized if normalized in allowed else "json"
