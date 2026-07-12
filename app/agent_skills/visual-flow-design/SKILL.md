---
name: visual-flow-design
description: Use when the user asks to design, review, troubleshoot, or explain TestAuto visual flows, DAG nodes, HTTP/WebSocket nodes, conditions, delays, data binding, node execution, flow reports, or visual flow execution records.
capabilities:
  - visual_flow.design
  - visual_flow.review
  - visual_flow.diagnose
required_context:
  - project_context
  - visual_flow_inventory
tools:
  - project.read_context
  - testcase.query_project_cases
  - flow.query_project_flows
  - flow.validate_graph
  - flow.create_saved
  - flow.update_saved
  - flow.execute_saved
  - execution.read_detail
  - report.read_summary
owns:
  - visual_flow
consumes:
  - test_case
  - scenario
  - execution
  - report
produces:
  - visual_flow
artifacts:
  - visual_flow
  - flow_report
examples:
  - review a visual flow DAG
  - diagnose a flow report
  - explain node data binding
triggers:
  - visual flow
  - flow
  - DAG
  - node
  - nodes
  - condition
  - delay
  - 可视化流程
  - 节点
  - 条件
  - 延迟
  - 连线
routing_requires_tool:
  - current project flow
  - real flow execution
  - flow report
  - 当前项目流程
  - 真实流程执行
  - 流程报告
---

# Visual Flow Design

## Workflow

1. For conceptual flow design and troubleshooting advice, answer directly.
2. For current Flow inventory, call `flow.query_project_flows`. Use its latest `object_ref` for update or execution.
3. Before creating or changing a Flow, use `project.read_context` and `testcase.query_project_cases` for real environments and HTTP/WebSocket case ids.
4. Always call `flow.validate_graph` before `flow.create_saved` or `flow.update_saved`; repair every returned issue before requesting approval.
5. `flow.create_saved` and `flow.update_saved` persist a version and require approval. Do not claim a save before approval and tool success.
6. `flow.execute_saved` queues an asynchronous execution. Use `execution.read_detail` or `report.read_summary` for the resulting evidence instead of immediately rerunning it.
7. Do not claim that a flow, node, edge, version, or execution was created, updated, saved, or started unless the dedicated tool succeeds.

## Design Rules

- Model flows as a versioned DAG with explicit node ids, protocol type, input bindings, conditions, delays, and failure strategy.
- Keep request data, extracted variables, environment variables, and dataset overrides distinct.
- Conditions should depend on explicit prior outputs, not hidden UI state.
- For failure diagnosis, identify the first failing node, upstream variable source, rendered request, assertion result, extractor output, and retry behavior.

## Final Reply

- Say whether the answer is a design review, execution diagnosis, or unsupported persistence action.
- Keep node-level recommendations concrete and auditable.
