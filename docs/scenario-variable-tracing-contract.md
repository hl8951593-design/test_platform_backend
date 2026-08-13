# 场景变量追踪契约

变量可来自 dataset、HTTP/WebSocket 提取器、数据库动作取值、`random`、`fixed_value` 和 `script` 动作。动作只
读取执行到当前位置时已存在的变量：随机和固定值通过 `config.output` 写入，脚本只读取
`config.inputs` 并只写回 `config.outputs`。JSON 值保持原始类型。

`database_query` / `database_execute` 使用 `config.extractors[]` 从 `rows.0.id`、`scalar`、
`affected_rows` 等路径提取变量。数据库运行时原始值可继续参与模板渲染；`masked=true` 的值只在
执行线程内传递，数据库动作审计、场景步骤结果和 run 变量快照统一显示 `***`。

步骤结果通过 `resolved_bindings` 记录变量来源与目标，通过 `extracted_variables` 记录写入。
敏感变量的追踪值和 run 变量快照显示为 `***`；来源仍保留稳定的 step/extraction ID，便于前端
在断线后用运行详情重建变量连线。

保存场景时，后端先固化引用用例的 `case_snapshot`，再从快照与节点覆盖配置的最终合并视图中
发现模板。`/companies/{{companyId}}` 这类嵌入式模板以及 header、query、body 中的模板都生成
稳定 binding；绑定元数据必须写回场景版本定义，不能只存在于执行时的扁平步骤副本。运行时
`resolved_bindings.value` 记录渲染后的最终目标值，敏感值仍统一显示为 `***`。

HTTP 响应中的敏感字段在执行记录入库前脱敏，但同一场景运行可以从仅存在于执行线程内存中的
原始响应提取敏感变量并传给后续步骤。原始值不会写入 HTTP 执行快照、场景步骤结果、事件或运行
变量快照；上述持久化与查询接口只返回 `***`。
