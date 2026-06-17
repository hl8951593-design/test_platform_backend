import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.v1.routers import projects, scenarios, test_plans, visual_flows
from app.core.permissions import ProjectPermission
from app.services.visual_flow_service import VisualFlowService


def _methods_by_path(router) -> dict[str, set[str]]:
    return {
        route.path: set(route.methods or ())
        for route in router.routes
        if hasattr(route, "methods")
    }


class DeletionRouteTests(unittest.TestCase):
    def test_primary_resources_register_delete_routes(self):
        expected_routes = (
            (visual_flows.router, "/{flow_id}"),
            (scenarios.router, "/{scenario_id}"),
            (scenarios.run_router, "/{run_id}"),
            (test_plans.router, "/{plan_id}"),
            (projects.router, "/{project_id}"),
        )

        for router, path in expected_routes:
            with self.subTest(path=path):
                self.assertIn("DELETE", _methods_by_path(router).get(path, set()))


class VisualFlowDeletionTests(unittest.TestCase):
    def test_delete_flow_physically_deletes_existing_flow(self):
        service = VisualFlowService(MagicMock())
        service.permission_service.require_project_permission = MagicMock()
        service.repository = MagicMock()
        flow = SimpleNamespace(id=2, project_id=1)
        service.repository.get_flow.return_value = flow
        user = SimpleNamespace(id=5)

        service.delete_flow(project_id=1, flow_id=2, current_user=user)

        service.permission_service.require_project_permission.assert_called_once_with(
            user,
            1,
            ProjectPermission.MANAGE_FLOW.value,
        )
        service.repository.delete_flow.assert_called_once_with(flow=flow)


if __name__ == "__main__":
    unittest.main()
