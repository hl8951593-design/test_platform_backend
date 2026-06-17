# 测试报告接口文档

本文档说明基于现有测试计划运行和可视化 Flow 执行生成的结构化报告与 HTML 导出。
基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

## 设计边界

- 报告是现有不可变运行数据的只读投影，不复制执行快照，不新增报告表。
- 首版支持 `plan` 和 `flow` 两种 `source_type`。
- 所有接口要求项目 `report:view` 权限。
- 计划报告展开目标关联的全部 dataset record 场景运行。
- Flow 报告展开节点执行、请求、输出和错误明细。
- HTML 导出使用与结构化详情相同的数据，并对名称和 JSON 明细进行 HTML 转义。

## 查询报告历史

| 项目 | 内容 |
| --- | --- |
| 接口 | `/reports?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |
| 说明 | 分页查询测试计划和 Flow 产生的报告候选 |

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `source_type` | 空 | `plan` 或 `flow` |
| `status` | 空 | 精确匹配运行状态 |
| `environment_id` | 空 | 环境 ID |
| `started_from` | 空 | ISO 8601 开始时间下界 |
| `started_to` | 空 | ISO 8601 开始时间上界 |
| `page` | `1` | 页码 |
| `page_size` | `20` | 每页数量，最大 200 |

响应 `data` 使用 `{items,total,page,page_size}`。每条摘要包含来源、名称、状态、触发方式、
环境、执行用户、通过/失败/跳过数量、通过率和耗时。计划列表指标按目标计算；Flow 列表指标
按节点计算。总数为零时通过率为 `0.0`。

## 查询结构化报告

| 项目 | 内容 |
| --- | --- |
| 接口 | `/reports/{source_type}/{source_id}?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |

响应由四部分组成：

| 字段 | 说明 |
| --- | --- |
| `summary` | 公共名称、状态、来源、环境、用户、计数、通过率和耗时 |
| `metrics` | 来源专属指标 |
| `items` | 计划目标或 Flow 节点明细 |
| `source_snapshot` | 计划版本快照或 Flow 执行上下文快照 |

计划报告的 `items[].scenario_runs` 包含目标产生的全部场景运行，可继续定位 dataset/record
身份、场景快照、变量快照、步骤结果、请求、响应、断言和 attempt 历史。计划报告同时提供
目标级和 record 运行级计数。Flow 报告提供节点总数、通过、失败、跳过和通过率。

## 下载 HTML 报告

| 项目 | 内容 |
| --- | --- |
| 接口 | `/reports/{source_type}/{source_id}/html?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |
| Content-Type | `text/html; charset=utf-8` |
| Content-Disposition | `attachment; filename="test-report-{type}-{id}.html"` |

HTML 文件包含报告标题、状态、通过率、指标卡片和可展开的完整项目明细，可离线查看。

## 查询历史趋势

| 项目 | 内容 |
| --- | --- |
| 接口 | `/reports/trends?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |

可选参数为 `source_type`、`environment_id`、`started_from` 和 `started_to`。默认查询截至
当天的最近 30 天，最长允许 366 天。当前固定按日聚合，每个点返回：

- `total_count`；
- `passed_count`；
- `failed_count`，包含 `failed` 和 `timeout`；
- `other_count`；
- `pass_rate`；
- `avg_duration_ms`。

趋势统计以一次测试计划运行或一次 Flow 执行为单位，不以计划目标或 Flow 节点为单位。

## 错误和兼容性

- `source_type` 不合法时返回 HTTP `422`。
- 时间范围逆序时返回 HTTP `400`。
- 来源不存在、已删除的计划运行或不属于当前项目时返回 HTTP `404`。
- 原测试计划运行和 Flow 执行接口保持不变。
- 本功能不新增表或字段；当前全局 Alembic head 以 [文档索引与维护规范](README.md) 为准。
- PDF 导出和长期报告归档尚未实现。
