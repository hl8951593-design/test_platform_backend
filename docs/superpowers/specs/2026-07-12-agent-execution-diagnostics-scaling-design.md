# Agent 执行诊断与海量结果渐进读取设计

## 1. 背景

Agent 执行场景“企业全景查询与关注管理”（场景 ID 45）后读取执行记录 220。该记录状态为
`failed`，完整工具输出约 235 KB，但通用工具结果策略只向模型提供前 2,400 个字符。第一步成功
响应占据绝大多数预览，真正失败的第三步未进入模型上下文，导致 Agent 根据历史信息推测为变量
绑定问题，而实际首个失败是目标接口返回业务码 `90001` 和“请求未授权”。

当前实现还存在两个随生产数据增长而放大的问题：

1. 场景运行将全部 `step_results`、`scenario_snapshot` 和 `variables_snapshot` 保存为运行行上的
   JSON；每个步骤开始或完成时会重新构造并写回逐渐增大的完整步骤数组。
2. 统一执行记录列表通过四种协议执行表的 `UNION ALL`、精确 `COUNT(*)` 和 `OFFSET` 分页提供，
   深分页和高频聚合难以扩展到千万级记录。

本设计不是单纯扩大截断阈值，而是建立可复用于 HTTP、WebSocket、场景、Flow 以及未来 Skill 的
执行数据存储、诊断投影、渐进读取和聚合查询边界。

## 2. 已确认事实

对执行记录 220 的当前数据库数据复核结果：

| 项目 | 大小/数量 |
| --- | ---: |
| `step_results` | 174,662 字符 |
| `scenario_snapshot` | 17,698 字符 |
| `variables_snapshot` | 41,415 字符 |
| 步骤数 | 11 |
| 第一个成功步骤 | 167,646 字符 |
| 首个失败步骤 | 2,946 字符 |

首个失败步骤是“获取对应企业 CT 画像数”：

- HTTP 状态码为 `200`；
- JSON `code` 实际为 `90001`，期望为 `200`；
- JSON `success` 实际缺失，期望为 `true`；
- 响应消息为“请求未授权”；
- 没有已解析绑定或提取变量。

因此，原回复中的“变量绑定缺失”不是当前证据支持的根因。根因是通用前缀截断丢失了语义优先级，
不是模型上下文长度本身不足。

## 3. 目标与容量等级

### 3.1 功能目标

1. 超长执行详情仍能稳定向 Agent 提供首个失败节点及完整关键证据。
2. 完整请求、响应、日志和审计数据继续保留，不因模型预算而丢失。
3. Agent 可以按执行、失败步骤、指定步骤和原始片段逐层下钻。
4. 后续新增协议或 Skill 通过注册投影器扩展，不在 Runtime 中堆积工具名特判。
5. 海量执行记录通过统一索引、游标、失败聚类和时间聚合查询。
6. 保持现有业务功能、权限、状态机、SSE 和异步执行架构。

### 3.2 容量目标

按 B 档设计，并保留向 C 档扩展的结构边界：

- 单项目最多 100,000 条测试用例；
- 每日最多 10,000,000 条执行记录；
- 单次组合执行最多 10,000 个步骤；
- 存储和分片接口不绑定单库上限，可进一步扩展到百万用例和亿级日执行记录。

### 3.3 非目标

- 不通过单纯扩大模型上下文或截断阈值解决问题。
- 不改变现有执行语义、断言语义、重试语义和审批机制。
- 不要求一次性迁移全部历史执行数据。
- 不在首个交付阶段强制引入 Redis、消息队列或对象存储部署组件。
- 不让 LLM 逐条扫描海量原始执行记录或负责生成基础统计。

## 4. 核心原则

1. **LLM 是控制面，不是数据面。** LLM 决定下一步查什么；数据库、投影器和工具负责检索、
   聚合、脱敏、分页和预算控制。
2. **完整账本与模型视图分离。** 完整执行数据作为权威账本保存；模型只读取确定性诊断视图。
3. **语义裁剪优先于前缀截断。** 失败证据优先于成功大响应，省略必须可见且可继续读取。
4. **增量写入优先于整块重写。** 步骤完成后只写当前步骤和运行摘要，不重写全部历史步骤。
5. **兼容迁移优先。** 新读模型和步骤表先双写、回填和对比，验证后再停止旧 JSON 热写。
6. **统一协议优先于死规则。** Runtime 只认识视图、选择器、游标、预算、证据引用和完整性。

## 5. 总体架构

```text
协议执行器（HTTP / WebSocket / Scenario / Flow）
        │
        ├── 完整执行账本 ───────────────┐
        │                              │
        ├── 执行主索引                  │
        ├── 步骤诊断记录                │
        └── 大对象引用                  │
                                       ▼
                           ExecutionDiagnosticProjector
                                       │
                              有界诊断证据包
                                       │
                      execution.read_detail / diagnose
                                       │
                                     LLM
```

架构分为四层：

1. **执行主记录/统一索引**：保存身份、状态、时间、统计和首个失败节点。
2. **步骤执行/诊断记录**：每个步骤增量保存状态、摘要和原始数据引用。
3. **原始大数据层**：保存完整请求、响应、日志、重试和附件。
4. **Agent 诊断投影层**：根据视图和预算生成模型可消费的证据包。

## 6. 数据模型

### 6.1 `execution_record_index`

统一执行索引不替代现有协议执行表，只为列表、筛选、聚合和跨协议引用提供稳定读模型。

必需逻辑字段：

```text
id
project_id
execution_type
execution_id
object_ref
resource_id
resource_name
environment_id
status
trigger_type
trigger_user_id
duration_ms
total_steps
passed_steps
failed_steps
timeout_steps
skipped_steps
first_failed_step_id
failure_category
failure_signature
started_at
finished_at
source_updated_at
projection_version
created_at
updated_at
```

约束和索引：

```text
UNIQUE(project_id, execution_type, execution_id)
INDEX(project_id, started_at, execution_type, execution_id)
INDEX(project_id, status, started_at, execution_id)
INDEX(project_id, environment_id, started_at, execution_id)
INDEX(project_id, failure_signature, started_at, execution_id)
```

### 6.2 `execution_step_diagnostics`

该表是跨协议步骤诊断读模型。场景和 Flow 可以包含多行；HTTP、WebSocket 单次执行可表示为一个
逻辑步骤。

必需逻辑字段：

```text
id
project_id
execution_type
execution_id
step_id
step_index
node_id
node_phase
name
kind
status
duration_ms
error_code
error_message
assertion_summary_json
response_summary_json
binding_summary_json
extraction_summary_json
retry_summary_json
request_artifact_ref
response_artifact_ref
detail_artifact_ref
projection_version
created_at
updated_at
```

约束和索引：

```text
UNIQUE(project_id, execution_type, execution_id, step_id)
INDEX(project_id, execution_type, execution_id, step_index)
INDEX(project_id, execution_type, execution_id, status, step_index)
INDEX(project_id, status, error_code, created_at)
```

`execution_step_diagnostics` 在阶段 3 是现有协议记录的附加读模型；完成阶段 5 后，场景步骤以该表
为增量权威来源，兼容详情由该表组装。HTTP、WebSocket 和已有独立节点表的 Flow 继续以各自协议
执行表为权威来源，统一步骤表保持读模型身份。

### 6.3 `execution_payload_artifacts`

通过 `ExecutionPayloadStore` 抽象保存大型原始内容。首期提供数据库适配器，后续可增加对象存储
适配器而不改变调用方。

```text
artifact_ref
project_id
execution_type
execution_id
step_id
section
storage_backend
storage_locator
content_type
encoding
raw_size_bytes
stored_size_bytes
sha256
redaction_version
retention_tier
created_at
```

默认只有序列化后超过 64 KiB 的独立请求、响应、日志或重试片段才外置；配置可以覆盖该默认值，
但首期允许范围固定为 16 KiB 至 1 MiB。低于阈值的内容可以继续保存在协议记录中，但普通诊断
视图仍只返回摘要。

### 6.4 时间聚合

`execution_metrics_hourly` 和 `execution_metrics_daily` 保存：

```text
project_id
environment_id
execution_type
time_bucket
status
failure_signature
execution_count
duration_sum_ms
duration_max_ms
```

聚合数据是非权威读模型，响应必须携带 `watermark` 表明覆盖到的最后执行时间。

## 7. 统一渐进式读取协议

### 7.1 请求

扩展 `execution.read_detail`，现有参数继续有效，新增字段均为可选：

```json
{
  "project_id": 1,
  "execution_type": "scenario",
  "execution_id": 220,
  "view": "failures",
  "selector": {
    "statuses": ["failed", "timeout"],
    "first_failure": true,
    "step_ids": []
  },
  "include": [
    "assertions",
    "response_summary",
    "bindings",
    "upstream"
  ],
  "cursor": null,
  "limit": 20,
  "max_chars": 12000
}
```

支持的 `view`：

| 视图 | 用途 |
| --- | --- |
| `summary` | 身份、状态、统计、当前步骤、首个失败步骤 |
| `failures` | 失败/超时步骤、失败聚类、跳过链 |
| `steps` | 全部步骤的游标分页摘要 |
| `step` | 指定步骤的断言、响应摘要、绑定、提取、重试 |
| `artifact` | 指定原始数据引用的有界分块 |
| `full` | 现有前端详情和审计兼容，不默认进入模型 |

选择器验证规则：

- `view=step` 必须提供且只能提供一个 `step_id`；
- `view=artifact` 必须提供 `artifact_ref`，可选 `offset`；
- `view=failures` 默认选择 `failed` 和 `timeout`，可通过 `statuses` 缩小范围；
- `view=steps` 使用稳定步骤游标 `(step_index, step_id)`；
- selector 引用不属于当前项目或当前执行时返回 `404`，不泄露跨项目存在性。

默认值与兼容规则：

- 为保持现有工具契约，调用方省略 `view` 时后端仍按 `view=full` 返回完整脱敏 ledger 输出；
- Agent Planner 和 Skill 的新调用显式使用 `view=summary`；旧调用即使返回 `full`，模型消息也必须
  经过专属语义投影，不能进入通用前缀截断；
- `limit=20`，最大 200；
- `max_chars=12000`，Runtime 硬上限为 24,000 字符；
- 原始 artifact 默认分块 8 KiB，单次最大 64 KiB。

### 7.2 响应

```json
{
  "schema_version": "execution_diagnostic_v1",
  "projection_version": "execution_diagnostic_projection_v1",
  "resource_ref": "scenario:220",
  "view": "failures",
  "data": {},
  "evidence_refs": [],
  "omissions": [
    {
      "section": "response_body",
      "reason": "budget_exceeded",
      "reference": "artifact:abc123"
    }
  ],
  "page": {
    "next_cursor": null,
    "has_more": false
  },
  "diagnostic_complete": true,
  "recommended_next_views": []
}
```

禁止静默截断。任何未进入模型视图的内容都必须通过 `omissions` 或分页字段说明原因和继续读取
方式。

### 7.3 语义预算顺序

当内容超过预算时依次保留：

1. 执行身份、状态和统计；
2. 首个失败或超时步骤；
3. 失败断言的类型、路径、期望值和实际值；
4. 响应状态、业务码和错误消息；
5. 变量绑定、提取结果和上游来源；
6. 跳过原因和影响链；
7. 其他失败步骤摘要；
8. 通过步骤摘要；
9. 原始成功请求、响应和日志。

如果最高优先级的最小证据仍无法放入预算，工具返回 `EVIDENCE_BUDGET_TOO_SMALL`，不得返回
残缺的成功结果。

## 8. 诊断投影器

定义通用接口：

```text
ToolResultProjector
- supports(tool_name, output_type)
- project(view, selector, include, cursor, limit, budget)
- classify_evidence()
- produce_references()
```

协议适配器：

- `HttpExecutionDiagnosticProjector`
- `WebSocketExecutionDiagnosticProjector`
- `ScenarioExecutionDiagnosticProjector`
- `FlowExecutionDiagnosticProjector`

Runtime 不判断具体协议字段，也不根据工具名写失败规则。注册表根据输出类型选择投影器；未知协议
使用结构化有界兜底，并返回 `diagnostic_complete=false`。

`execution.read_detail`、`execution.diagnose` 和模型工具结果消息必须复用同一个投影结果，避免
三个位置产生不同结论。完整脱敏输出仍保留在 ToolCall ledger 中，但私有 `tool_result.read_full`
只作为诊断兜底，不作为正常 Agent 路径。

## 9. 失败分类与指纹

失败指纹由确定性字段生成，禁止把动态 ID、时间戳、完整消息或 LLM 文本直接纳入指纹。

规范化输入：

```text
execution_type
failure_category
transport_status
business_code
assertion_type
assertion_path
target_operation
normalized_error_code
```

示例：

```text
scenario
+ authorization
+ HTTP_200
+ BUSINESS_90001
+ json_equals
+ code
= AUTHORIZATION_HTTP200_CODE90001_JSON_EQUALS_CODE
```

聚类查询返回数量、受影响资源数、首次/最后出现时间和有限代表样本。LLM 对聚类进行解释和命名，
但不参与基础计数和逐条归类。

## 10. 海量记录查询

### 10.1 游标分页

Agent 和新高数据量页面使用 `(started_at, execution_type, execution_id)` 的稳定游标，不使用深度
`OFFSET`。现有前端页码接口在兼容期继续保留。

### 10.2 按需总数

`execution.query_records` 增加 `include_total`。Agent 默认 `false`，返回 `has_more`、
`next_cursor` 和 `returned`。只有明确需要精确总数时才执行计数。

### 10.3 统计与趋势

通过小时/天聚合表提供通过率、失败趋势、环境对比和失败签名分布。聚合更新不能阻塞执行状态
落库或 SSE；失败时可重试和按 watermark 重建。

## 11. 写入与异步边界

### 11.1 不改变现有调度模型

- 场景、HTTP、WebSocket 和 Flow 的现有执行入口、Future/worker、状态机和 SSE 保持不变。
- 执行主索引和当前步骤诊断使用执行过程中已经存在的数据，不触发额外详情回读。
- 当前步骤完成时进行幂等增量 upsert，不增加新的事务提交点。
- 时间聚合在执行事务完成后异步更新，不参与执行成功判定。

### 11.2 由整块重写迁移到增量步骤

兼容阶段：

1. 新步骤表与现有 `step_results` 双写。
2. 详情接口同时读取两种来源并进行结构对比，仍返回原公开 Schema。
3. 历史运行按需懒回填，也支持离线批量回填。
4. 当新路径覆盖率和一致性验证通过后，执行中不再每步重写完整 `step_results`。
5. 旧 JSON 字段保留为兼容快照；本设计及其实施计划不删除该字段。

### 11.3 读写一致性

- 刚完成执行的工具结果必须直接返回规范 `execution_ref`，Agent 不需要再查询列表猜测 ID。
- 指定 `execution_ref` 的详情读取始终回源权威协议表或步骤记录。
- 聚合和趋势允许延迟，但必须暴露 watermark。
- 双写不一致时以现有协议执行记录为权威，并记录可重放的投影失败状态。

## 12. 安全与错误处理

1. 请求头、Token、Cookie、密码、密钥和敏感环境变量在进入诊断投影前统一脱敏。
2. artifact 继承项目隔离和 `report:view` 权限；跨项目引用一律拒绝。
3. 投影不支持、版本不匹配或数据不完整时返回 `diagnostic_complete=false`。
4. artifact 缺失时保留摘要并返回 `artifact_missing`，不得伪造原始内容。
5. 投影落后时允许从权威记录临时重建，并记录需要补投影的引用。
6. 投影器异常不得改变原执行业务状态；工具返回明确诊断错误和安全下一步。
7. Agent 在证据不完整时必须调用 `recommended_next_views` 或报告缺失证据，不能输出推测根因。

## 13. 兼容性

- 原执行列表和完整详情路由继续可用。
- 原 `execution.read_detail` 参数继续有效；新增字段均可选。
- 前端完整详情继续获得原有 `summary + detail` 语义。
- ToolCall ledger 继续保存完整脱敏工具结果。
- 现有 Skill 名称和工具名不因本设计强制变更。
- SSE 事件名、sequence、终态和运行状态转换保持不变。
- migration 只新增表、索引和可空兼容字段，不在同一版本删除旧字段。

## 14. 分阶段交付

### 阶段 1：语义投影正确性

- 为 `execution.read_detail` 增加专属投影器。
- 运行 220 无论前置成功响应多大，都返回第三步失败证据。
- `execution.diagnose` 改为接收有界诊断证据包。

### 阶段 2：渐进读取协议

- 增加 `view/selector/include/cursor/limit/max_chars`。
- 增加 omissions、evidence refs 和 diagnostic completeness。
- 覆盖四种执行协议。

### 阶段 3：统一索引和步骤诊断表

- 新增 migration、模型、仓储和服务。
- 新执行双写，历史记录可重放回填。
- 详情兼容组装器保持公开契约。

### 阶段 4：大字段分层与聚合

- 引入 `ExecutionPayloadStore` 数据库适配器。
- 增加失败聚类、小时/天聚合和游标查询。
- 按测量结果决定是否启用对象存储适配器。

### 阶段 5：停止热路径整块重写

- 在一致性、回滚和负载门槛全部通过后，停止每步骤重写完整 `step_results`。
- 保留旧字段读取和回退能力至少一个发布周期。

## 15. 测试策略

### 15.1 投影单元测试

- 160 KB 成功步骤位于失败步骤之前，失败证据仍完整出现。
- 多失败、超时、重试、断言、绑定和提取失败。
- HTTP、WebSocket、场景和 Flow 投影结构一致。
- 任意输入下模型视图不超过声明预算。
- 未知协议返回有界兜底和 `diagnostic_complete=false`。
- 敏感字段不会进入摘要或 artifact 元数据。

### 15.2 服务与契约测试

- `summary/failures/steps/step/artifact/full` 全部视图。
- omissions、cursor、has_more 和 evidence refs 可继续读取。
- 老参数调用和完整详情响应兼容。
- `execution.diagnose` 不再发送完整超大详情。
- 跨项目读取、权限不足和不存在引用正确拒绝。

### 15.3 数据库测试

- summary 和 failures 查询不选择完整 payload 列。
- 游标在并发新增记录时不重复、不遗漏。
- 双写、回填、重试和重复消费幂等。
- migration upgrade/downgrade 对称，Alembic 保持单 head。
- 查询计划使用预期组合索引。

### 15.4 异步与兼容回归

- SSE sequence、事件名和终态不变。
- 执行 worker、Future 等待和取消/超时语义不变。
- 不增加每步骤事务提交次数。
- 新旧详情组装结果在兼容字段上等价。
- 投影失败不改变测试执行的业务终态。

### 15.5 规模验证

- 10,000 步执行写入量随步骤数线性增长，不发生历史步骤整块重复写入。
- 深度游标页查询计划与第一页使用相同索引路径。
- Agent 默认执行详情控制在 12,000 字符内。
- 聚类分析读取失败簇和有限样本，不随同类执行总数线性增加模型输入。

## 16. 验收门槛

1. 运行 220 回归准确识别“请求未授权 / 业务码 90001”，不再推测变量绑定缺失。
2. 超长成功响应不能挤掉首个失败步骤。
3. 所有模型视图严格满足预算并公开省略信息。
4. 完整数据、前端详情、审计和现有异步行为不丢失、不改变。
5. 四种协议和未来投影器共用统一接口，无 Runtime 工具名特判扩散。
6. 执行记录列表支持游标、按需总数、失败签名和聚合读模型。
7. 10,000 步写入达到线性复杂度目标。
8. 专项测试、完整仓库测试、迁移测试和查询计划检查全部通过。

## 17. 回滚

- 阶段 1 和阶段 2 可关闭新投影/渐进视图，恢复现有完整详情路径。
- 阶段 3 和阶段 4 的新表是附加读模型，回滚代码不需要修改原执行数据。
- 双写期始终保留现有协议表作为权威来源。
- 阶段 5 回滚时重新启用旧 `step_results` 写入，并从步骤表组装缺失兼容快照。
- migration downgrade 只删除本设计新增索引和表，不修改旧执行记录。

## 18. 已确认决策

- 采用方案 C：诊断读模型和渐进式读取作为目标架构。
- 采用“主记录 + 步骤记录 + 大对象引用 + 诊断投影”四层边界。
- 采用“视图 + 选择器 + 游标 + 预算 + 证据引用”的通用协议。
- 采用统一执行索引、按需总数、确定性失败聚类和时间聚合。
- 按 B 档设计并保留向 C 档扩展能力。
- 分阶段兼容迁移，不改变现有业务功能和异步执行架构。
