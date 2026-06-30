---
name: visual-flow-design
description: Use when the user asks to design, review, troubleshoot, or explain TestAuto visual flows, DAG nodes, HTTP/WebSocket nodes, conditions, delays, data binding, node execution, flow reports, or visual flow execution records.
triggers:
  - visual flow
  - flow
  - DAG
  - node
  - nodes
  - condition
  - delay
  - 可视化流程
  - 流程
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
2. For real execution or report facts, use `report.read_summary` when the user asks about completed flow reports, failures, or pass rate.
3. Use `project.read_context` when the flow advice depends on environments or project resources.
4. Do not claim that a flow, node, edge, version, or execution was created, updated, saved, deleted, or started unless a dedicated backend tool succeeds.

## Design Rules

- Model flows as a versioned DAG with explicit node ids, protocol type, input bindings, conditions, delays, and failure strategy.
- Keep request data, extracted variables, environment variables, and dataset overrides distinct.
- Conditions should depend on explicit prior outputs, not hidden UI state.
- For failure diagnosis, identify the first failing node, upstream variable source, rendered request, assertion result, extractor output, and retry behavior.

## Final Reply

- Say whether the answer is a design review, execution diagnosis, or unsupported persistence action.
- Keep node-level recommendations concrete and auditable.
