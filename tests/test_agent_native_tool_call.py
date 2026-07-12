import json
import unittest

from app.services.agent_capability_plan_service import provider_tool_alias


class AgentNativeToolCallTests(unittest.TestCase):
    def test_native_definitions_always_include_runtime_capability_request(self):
        from app.services.agent_native_tool_call import (
            RUNTIME_REQUEST_CAPABILITY_ALIAS,
            build_native_tool_definitions,
        )

        definitions = build_native_tool_definitions(
            allowed_tools=[],
            tool_aliases={},
            runtime_tools=[],
        )

        self.assertIn(
            RUNTIME_REQUEST_CAPABILITY_ALIAS,
            [item.function.name for item in definitions],
        )

    def test_native_accumulator_parses_internal_capability_request(self):
        from app.services.agent_native_tool_call import (
            RUNTIME_REQUEST_CAPABILITY_ALIAS,
            NativeCapabilityRequest,
            NativeToolCallAccumulator,
        )

        arguments = json.dumps({
            "tool_names": ["scenario.compose_draft"],
            "reason": "The authoritative test-case artifact is available.",
        })
        accumulator = NativeToolCallAccumulator(tool_aliases={})
        accumulator.feed({
            "index": 0,
            "id": "capability-call-1",
            "type": "function",
            "function": {
                "name": RUNTIME_REQUEST_CAPABILITY_ALIAS,
                "arguments": arguments,
            },
        })

        request = accumulator.finalize()

        self.assertIsInstance(request, NativeCapabilityRequest)
        self.assertEqual(request.tool_names, ("scenario.compose_draft",))
        self.assertEqual(request.provider_tool_call_id, "capability-call-1")

    def test_native_arguments_preserve_html_nested_json_quotes_and_newlines(self):
        from app.services.agent_native_tool_call import NativeToolCallAccumulator

        canonical_name = "defect.create_saved"
        alias = provider_tool_alias(canonical_name)
        expected_html = '<pre>{"code": 90001}\n"quoted"\\path</pre>'
        arguments = json.dumps(
            {
                "input": {
                    "project_id": 1,
                    "defect": {
                        "title": "Unicode 缺陷",
                        "bug_type": "functional",
                        "urgency": "medium",
                        "content_html": expected_html,
                    },
                },
                "reason": "create from failed execution",
                "evidence_refs": [],
            },
            ensure_ascii=False,
        )
        accumulator = NativeToolCallAccumulator(tool_aliases={alias: canonical_name})
        boundaries = [1, 7, 19, 53, 101, len(arguments)]
        start = 0
        for index, end in enumerate(boundaries):
            accumulator.feed({
                "index": 0,
                "id": "call-native-1" if index == 0 else None,
                "type": "function" if index == 0 else None,
                "function": {
                    "name": alias if index == 0 else "",
                    "arguments": arguments[start:end],
                },
            })
            start = end

        request = accumulator.finalize()

        self.assertEqual(request.tool_name, canonical_name)
        self.assertEqual(
            request.tool_input["defect"]["content_html"],
            expected_html,
        )
        self.assertEqual(request.reason, "create from failed execution")

    def test_unexpected_parallel_native_calls_are_rejected(self):
        from app.services.agent_native_tool_call import NativeToolCallAccumulator, NativeToolCallError

        alias = provider_tool_alias("project.read_context")
        accumulator = NativeToolCallAccumulator(tool_aliases={alias: "project.read_context"})
        accumulator.feed({
            "index": 0,
            "id": "call-1",
            "type": "function",
            "function": {"name": alias, "arguments": '{"input":{}}'},
        })

        with self.assertRaises(NativeToolCallError):
            accumulator.feed({
                "index": 1,
                "id": "call-2",
                "type": "function",
                "function": {"name": alias, "arguments": '{"input":{}}'},
            })


if __name__ == "__main__":
    unittest.main()
