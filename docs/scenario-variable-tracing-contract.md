# 场景变量追踪契约

变量可来自 dataset、HTTP/WebSocket 提取器、`random`、`fixed_value` 和 `script` 动作。动作只
读取执行到当前位置时已存在的变量：随机和固定值通过 `config.output` 写入，脚本只读取
`config.inputs` 并只写回 `config.outputs`。JSON 值保持原始类型。

步骤结果通过 `resolved_bindings` 记录变量来源与目标，通过 `extracted_variables` 记录写入。
敏感变量的追踪值和 run 变量快照显示为 `***`；来源仍保留稳定的 step/extraction ID，便于前端
在断线后用运行详情重建变量连线。
