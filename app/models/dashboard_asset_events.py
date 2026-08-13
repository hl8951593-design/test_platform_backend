from datetime import datetime

from sqlalchemy import event, inspect

from app.models.dashboard import DashboardAssetEvent
from app.models.defect import Defect
from app.models.scenario import TestScenario
from app.models.system_test_case import SystemTestCase
from app.models.test_case import TestCase
from app.models.websocket_test_case import WebSocketTestCase


CLOSED_DEFECT_STATUSES = {"closed", "resolved", "done", "已关闭", "已解决"}
ASSET_MODELS = {
    TestCase: "http_test_case",
    WebSocketTestCase: "websocket_test_case",
    SystemTestCase: "system_test_case",
    TestScenario: "scenario",
    Defect: "defect",
}


def _record(connection, target, asset_type: str, event_type: str) -> None:
    connection.execute(
        DashboardAssetEvent.__table__.insert().values(
            project_id=target.project_id,
            environment_id=getattr(target, "environment_id", None),
            asset_type=asset_type,
            resource_id=str(target.id),
            event_type=event_type,
            occurred_at=datetime.now(),
        )
    )


def _after_insert(_mapper, connection, target) -> None:
    _record(connection, target, ASSET_MODELS[type(target)], "created")


def _after_delete(_mapper, connection, target) -> None:
    _record(connection, target, ASSET_MODELS[type(target)], "deleted")


def _after_defect_update(_mapper, connection, target: Defect) -> None:
    history = inspect(target).attrs.status.history
    if not history.has_changes() or not history.deleted:
        return
    was_closed = str(history.deleted[0]).strip().lower() in CLOSED_DEFECT_STATUSES
    is_closed = str(target.status).strip().lower() in CLOSED_DEFECT_STATUSES
    if was_closed != is_closed:
        _record(connection, target, "defect", "closed" if is_closed else "reopened")


def _after_scenario_update(_mapper, connection, target: TestScenario) -> None:
    history = inspect(target).attrs.is_deleted.history
    if not history.has_changes() or not history.deleted:
        return
    was_deleted = bool(history.deleted[0])
    is_deleted = bool(target.is_deleted)
    if was_deleted != is_deleted:
        _record(connection, target, "scenario", "deleted" if is_deleted else "created")


for _model in ASSET_MODELS:
    event.listen(_model, "after_insert", _after_insert)
    event.listen(_model, "after_delete", _after_delete)

event.listen(Defect, "after_update", _after_defect_update)
event.listen(TestScenario, "after_update", _after_scenario_update)
