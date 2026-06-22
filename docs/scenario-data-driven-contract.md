# 场景数据驱动契约

场景只写入 `datasets[].records[]`。dataset 与 record 默认都必须启用才参与默认执行；显式
`datasetIds` 可选择停用 dataset，但仍只展开其中启用的 records。每条 record 创建独立 run，
并保留 `dataset_id/name` 与 `record_id/name`。

`request_overrides` 以 `step_id + target + path` 唯一定位主用例请求字段。执行顺序为：复制版本
中的用例快照、合并用例 config、应用 record overrides、解析变量模板、执行协议 Schema 校验。
`target` 支持 `path`、`headers`、`query_params`、`body`；WebSocket 只支持前两项。body 路径
支持对象段和数组索引，`value` 保留任意 JSON 类型。

兼容读取旧 dataset-level `request_overrides`：`values[]` 按索引展开 records，单个 `value`
生成一条 record。详情响应和新版本写入不再输出旧结构。
