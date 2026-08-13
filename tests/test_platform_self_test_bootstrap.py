import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path("scripts/bootstrap_platform_self_test.py")
SPEC = importlib.util.spec_from_file_location("bootstrap_platform_self_test", SCRIPT_PATH)
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = BOOTSTRAP
SPEC.loader.exec_module(BOOTSTRAP)


class RecordingClient:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        body = kwargs["body"]
        return 201, {"data": {"id": 108, **body}}, {}


class PlatformSelfTestBootstrapTests(unittest.TestCase):
    @staticmethod
    def case(case_id: int, name: str) -> dict[str, Any]:
        return {
            "id": case_id,
            "name": name,
            "method": "GET",
            "path": f"/api/v1/self-test/{case_id}",
            "extractors": [],
        }

    def test_mega_full_scenario_contains_all_contract_and_business_cases(self):
        client = RecordingClient()
        login_case = self.case(1, "SUT-01 登录并提取访问令牌")
        cases_by_tag = {
            "项目权限": [self.case(index, f"COV-{index:03d}") for index in range(2, 102)],
            "基础路由": [self.case(index, f"COV-{index:03d}") for index in range(102, 166)],
        }
        business_cases = [
            self.case(index, f"BIZ-{index:03d}")
            for index in range(166, 305)
        ]
        business_cases[0]["_before_actions"] = [{"id": "ACTION-BIZ-SUFFIX", "kind": "random"}]
        business_cases[-1]["_after_actions"] = [{"id": "ACTION-BIZ-CLEANUP", "kind": "delay"}]

        created = BOOTSTRAP.create_mega_full_scenario(
            client,
            project_id=10,
            environment_id=13,
            login_case=login_case,
            cases_by_tag=cases_by_tag,
            business_cases=business_cases,
        )

        self.assertEqual(created["id"], 108)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/scenarios?project_id=10")
        self.assertEqual(call["timeout"], 60)

        payload = call["body"]
        nodes = payload["nodes"]
        self.assertEqual(payload["name"], BOOTSTRAP.MEGA_SCENARIO_NAME)
        self.assertEqual(payload["environment_id"], 13)
        self.assertIn("100-plus-cases", payload["tags"])
        self.assertIn("business-lifecycle", payload["tags"])
        self.assertEqual(len(nodes), 304)
        self.assertEqual(nodes[0]["id"], "NODE-LOGIN")
        self.assertFalse(nodes[0]["test_case"]["continue_on_failure"])
        self.assertTrue(all(node["test_case"]["continue_on_failure"] for node in nodes[1:]))
        self.assertEqual(len({node["id"] for node in nodes}), 304)
        self.assertEqual(len({node["test_case"]["id"] for node in nodes}), 304)
        self.assertEqual(
            {node["test_case"]["reference_id"] for node in nodes[1:]},
            set(range(2, 305)),
        )
        self.assertEqual(nodes[1]["before_actions"], business_cases[0]["_before_actions"])
        self.assertEqual(nodes[139]["after_actions"], business_cases[-1]["_after_actions"])

    def test_e2e_lifecycle_definitions_model_failure_repair_and_cleanup(self):
        definitions = BOOTSTRAP.end_to_end_lifecycle_definitions(10, 13)

        self.assertEqual(len(definitions), 33)
        self.assertEqual(
            [item["code"] for item in definitions],
            [f"E2E-{index:02d}" for index in range(1, 34)],
        )
        by_code = {item["code"]: item for item in definitions}

        self.assertEqual(
            [action["kind"] for action in by_code["E2E-01"]["before_actions"]],
            ["random", "fixed_value", "script", "condition"],
        )
        self.assertEqual(
            [action["kind"] for action in by_code["E2E-01"]["after_actions"]],
            ["script", "condition"],
        )
        child_node = by_code["E2E-03"]["body"]["nodes"][0]
        self.assertEqual(child_node["test_case"]["reference_id"], "{{e2e_case_id}}")
        self.assertEqual(child_node["before_actions"][0]["kind"], "fixed_value")
        self.assertEqual(child_node["after_actions"][0]["kind"], "script")

        failed_run_assertions = by_code["E2E-06"]["assertions"]
        self.assertTrue(any(item.get("path") == "data.status" and item.get("expected") == "failed" for item in failed_run_assertions))
        self.assertTrue(any(item.get("path") == "data.step_results.1.status" and item.get("expected") == "failed" for item in failed_run_assertions))
        self.assertTrue(any(item.get("path") == "data.step_results.2.status" and item.get("expected") == "passed" for item in failed_run_assertions))

        repaired_assertion = by_code["E2E-10"]["body"]["assertions"][0]
        self.assertEqual(repaired_assertion, {"type": "status_code", "expected": 200})
        self.assertEqual(by_code["E2E-18"]["assertions"][0]["path"], "data.item.status")
        self.assertEqual(by_code["E2E-11"]["body"]["version"], 1)
        self.assertEqual(
            [by_code[code]["body"]["status"] for code in ("E2E-09", "E2E-20", "E2E-21", "E2E-22")],
            ["confirmed", "fixed", "verified", "closed"],
        )
        self.assertEqual(
            [by_code[f"E2E-{index:02d}"]["method"] for index in range(24, 31)],
            ["DELETE"] * 7,
        )
        self.assertEqual(
            [by_code[f"E2E-{index:02d}"]["status"] for index in range(31, 34)],
            [200, 404, 404],
        )
        self.assertEqual(by_code["E2E-02"]["path"], "/test-cases")
        self.assertEqual(by_code["E2E-31"]["assertions"][0]["expected"], 0)


if __name__ == "__main__":
    unittest.main()
