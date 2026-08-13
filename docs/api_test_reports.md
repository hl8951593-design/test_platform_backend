# 测试报告接口文档

状态：当前实现
最后核验：2026-07-18

本文档说明测试计划运行和可视化 Flow 执行产生的报告读模型、脱敏明细、规则洞察与
HTML 导出。基础路径：`/api/v1`。

## 设计边界

- 报告继续以 `test_plan_runs`、`visual_flow_executions` 及其子执行为事实源，不复制报告正文。
- `GET /reports/{source_type}/{source_id}` 只返回可直接展示的轻量标准明细，不返回原始请求、
  响应、变量或场景快照。
- 原始执行明细只能通过单条明细接口按需读取，并在 Service 层执行大小写不敏感的递归脱敏。
- 直接 HTML 下载使用 Bearer Token；浏览器新窗口场景使用持久化、短时、一次性导出凭证。
- 洞察和补充用例草稿当前均由确定性规则生成，明确返回 `generated_by=rules`，不伪装为模型结果。
- 除一次性导出下载外，读取接口要求项目 `report:view` 权限和项目归属校验；删除接口要求
  `report:delete` 权限。

## 报告列表

```http
GET /reports?project_id=1&environment_id=4&source_type=flow&status=passed
    &started_from=2026-07-01T00:00:00&started_to=2026-07-15T23:59:59
    &page=1&page_size=20
Authorization: Bearer <token>
```

响应 `data` 为 `{items,total,page,page_size}`。摘要统一包含：

- `id/source_type/source_id/project_id/name/status`；
- `trigger_type/trigger_user_id/trigger_user_name`，并保留 `user_name` 兼容字段；
- `environment_id/environment_name`；
- `total_count/passed_count/failed_count/skipped_count/pass_rate`；
- `duration_ms/started_at/finished_at/created_at`。

计划名称、计划版本和环境名称来自不可变 `TestPlanRun` 快照。新 Flow 执行会在
`context_snapshot.sourceName/sourceVersion` 保存来源名称和版本；旧数据依次兼容读取现有来源快照、
`definition.name` 和当前 Flow 名称。删除或重命名资产不会改变新执行报告的名称。

## 结构化报告详情

```http
GET /reports/flow/2?project_id=1
Authorization: Bearer <token>
```

响应由 `summary`、`metrics`、`items`、`source_snapshot` 组成。计划目标和 Flow 节点使用同一套
`items[]` 展示契约：

```json
{
  "id": "node-execution:8",
  "sequence": 2,
  "item_type": "flow_node",
  "node_id": "node-1782307244777-v2l25",
  "reference_id": 7,
  "name": "获取企业列表",
  "kind": "api_case",
  "method": "POST",
  "path": "/api/enterprise/list",
  "status": "passed",
  "status_label": "通过",
  "attempt": 1,
  "total_count": 1,
  "passed_count": 1,
  "failed_count": 0,
  "skipped_count": 0,
  "pass_rate": 100,
  "assertion_count": 0,
  "passed_assertion_count": 0,
  "failed_assertion_count": 0,
  "response_status_code": 514,
  "duration_ms": 4779,
  "error_code": null,
  "error_message": null,
  "warning_flags": ["no_assertion", "non_2xx_response"],
  "started_at": "2026-06-24 13:22:58",
  "finished_at": "2026-06-24 13:23:03",
  "detail_available": true
}
```

Flow 节点元数据按 `node_id` 从执行时 `definition.nodes` 和 `referencedCases` 合并；计划目标则从
`plan_snapshot.targets`、`target_results` 和关联 dataset record 场景运行聚合。详情首页不会返回
`request_snapshot`、`response_snapshot`、`scenario_snapshot` 或完整 `step_results`。

## 单条脱敏明细

```http
GET /reports/{source_type}/{source_id}/items/{item_id}?project_id=1
Authorization: Bearer <token>
```

响应 `data` 固定为：

```json
{
  "item": {},
  "request": {
    "method": "POST",
    "url": "https://example.com/orders?token=%2A%2A%2A",
    "path": "/orders",
    "headers": {"Authorization": "***"},
    "query": {},
    "body": {"password": "***"}
  },
  "response": {
    "status_code": 200,
    "headers": {"Set-Cookie": "***"},
    "body": {"access_token": "***"}
  },
  "assertions": [],
  "attempts": []
}
```

以下字段及其大小写、连字符/下划线变体会递归脱敏：`Authorization`、`Lingxi-Auth`、
`Cookie`、`Set-Cookie`、`X-API-Key`、`token`、`access_token`、`refresh_token`、`password`、
`secret`、`api_key` 等。URL 中对应查询参数也会脱敏。HTML 导出只使用轻量 `items[]`，不会重新
嵌入原始明细。

## 规则洞察

```http
GET /reports/intelligence-overview?project_id=1&environment_id=4&range=7d
Authorization: Bearer <token>
```

`range` 只允许 `today`、`7d`、`30d`。响应包含：

- `generated_at/generated_by/scope`；
- 当前与上一周期通过率、稳定性和慢执行数量；
- 带日期、通过/失败计数的 `pass_rate_trend[]`；
- 相互独立的执行失败、慢执行、未关闭缺陷风险；
- 真实 `failure_clusters[]`，没有失败时返回空数组，不生成占位聚类；
- 带 `execution_id/name/owner_name/last_executed_at` 的 `slow_tests[]`；
- `stability_heatmap={labels,rows}`；
- 带结构化 `action` 的 `recommendations[]`。

当前建议是规则结果，`generated_by` 固定为 `rules`。后续真正使用模型时才允许返回 `model`。

## 历史趋势

```http
GET /reports/trends?project_id=1&source_type=flow&started_from=2026-07-01&started_to=2026-07-15
Authorization: Bearer <token>
```

默认查询最近 30 天，最长 366 天，按一次计划运行或一次 Flow 执行聚合。每个点返回总数、
通过数、失败数、其他状态数、通过率和平均耗时。

## HTML 下载

### Bearer 下载

```http
GET /reports/{source_type}/{source_id}/html?project_id=1
Authorization: Bearer <token>
```

适用于前端通过带鉴权 `fetch` 获取 Blob。不要用不携带 Authorization 的 `window.open()` 直接调用。

### 一次性下载地址

```http
POST /reports/{source_type}/{source_id}/exports
Authorization: Bearer <token>
Content-Type: application/json

{"project_id": 1, "format": "html"}
```

响应：

```json
{
  "export_id": "export-xxx",
  "download_url": "/api/v1/reports/exports/export-xxx/download?token=...",
  "expires_at": "2026-07-15 10:21:00"
}
```

`GET /reports/exports/{export_id}/download?token=...` 不使用 Bearer Token，而是验证随机凭证的 SHA-256
摘要、有效期和消费状态。凭证默认 300 秒过期，首次成功下载后立即标记 `consumed_at`；重复下载或
过期返回 HTTP `410`。凭证只保存摘要，不保存明文。有效期可通过
`TEST_REPORT_EXPORT_EXPIRE_SECONDS` 配置；统一请求日志会在写日志前将 `token` 查询参数脱敏。
创建新凭证时会顺带清理已过期或已消费超过 24 小时的凭证记录，报告正文不受影响。

## 生成补充用例草稿

```http
POST /reports/{source_type}/{source_id}/supplement-case-drafts
Authorization: Bearer <token>
Content-Type: application/json

{
  "project_id": 1,
  "environment_id": 4,
  "scope": "risk_gaps",
  "target_case_type": "system_case",
  "item_ids": []
}
```

该接口根据失败、非 2xx、缺少断言和重试等报告事实生成系统测试用例草稿，只返回提案，不直接写入
`system_test_cases`。`scope=selected` 时必须提供有效 `item_ids`；跨报告或不存在的明细 ID 返回
HTTP `400`。保存草稿仍应走系统测试用例现有创建接口和权限校验。

## 删除报告

```http
DELETE /reports/{source_type}/{source_id}?project_id=1
Authorization: Bearer <token>
```

删除要求 `report:delete` 权限。报告是执行事实的投影，因此该操作只在 `test_report_deletions` 写入报告中心
删除标记，并立即删除同一报告尚未消费的一次性 `test_report_exports`；不会删除对应的
`TestPlanRun`、`VisualFlowExecution`、Flow 节点或执行诊断记录。删除后报告不再进入列表、详情、趋势、
洞察或新导出读取，重复读取返回 HTTP `404`。对应执行处于 `queued/pending/running` 时返回 HTTP `409`。

## 数据库和兼容性

- `0043_test_report_contracts` 新增 `test_report_exports`，用于一次性导出凭证，不复制报告正文。
- `0051_test_report_deletions` 新增按 `project_id/source_type/source_id` 唯一的报告中心删除标记；项目物理
  删除会同时清理删除标记和一次性导出凭证。
- Flow 名称/版本使用现有 JSON 快照扩展，新写入包含 `sourceName/sourceVersion`；旧快照按兼容顺序读取，
  无需批量改写历史 JSON。
- 原有报告接口路径保持不变；`user_name` 保留用于旧前端，规范字段为 `trigger_user_name`。
- PDF 和长期报告归档仍未实现。
