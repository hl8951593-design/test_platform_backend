# 媒体存储接口文档

媒体模块使用私有 MinIO/S3 桶保存缺陷截图，MySQL 的 `media_objects` 只保存对象键、归属和
文件元数据。接口基础路径为 `/api/v1/media`，成功响应统一为 `{code,message,data}`。

## 上传与绑定流程

```text
POST /media/images 上传图片
-> 返回 media id 和短期 download_url
-> POST /defects 或 PUT /defects/{id} 提交 media_ids
-> GET 缺陷时 attachments 返回新生成的 download_url
```

预签名 URL 会过期，前端不能把它持久化到 `content_html`。过期后通过 URL 刷新接口获取新地址。

## 上传图片

| 项目 | 内容 |
| --- | --- |
| 接口 | `POST /media/images?project_id={project_id}` |
| Content-Type | `multipart/form-data`，文件字段名为 `file` |
| 权限 | `defect:create` 或 `defect:update` |
| 成功状态 | HTTP `201` |

支持 PNG、JPEG、GIF、WebP，默认最大 10 MiB。后端同时校验声明 MIME 与文件头签名；空文件、
伪造类型返回 `400`，超限返回 `413`，不支持格式返回 `415`，MinIO 不可用返回 `503`。

响应 `data` 示例：

```json
{
  "id": 12,
  "original_filename": "checkout.png",
  "content_type": "image/png",
  "size_bytes": 183024,
  "download_url": "http://minio.example/testplatform/...?X-Amz-Signature=...",
  "created_at": "2026-06-17 08:00:00"
}
```

## 刷新访问地址

`GET /media/{media_id}/url?project_id={project_id}` 需要 `defect:view`，返回：

```json
{
  "url": "http://minio.example/testplatform/...?X-Amz-Signature=...",
  "expires_in": 3600
}
```

## 删除媒体

`DELETE /media/{media_id}?project_id={project_id}` 允许上传者删除自己的媒体；项目中具备
`defect:update` 的用户也可删除。接口先删除 MinIO 对象，再删除元数据。存储不可用时返回
`503` 并保留元数据，客户端可重试。

删除缺陷会删除其已绑定对象；删除项目会先删除项目下全部媒体对象，再物理清理业务数据。

## 归属与安全规则

- 媒体只能绑定到同一项目的缺陷；
- 默认只能绑定自己上传且尚未被其他缺陷占用的媒体；
- 对象键使用 `projects/{project_id}/defects/{uuid}.{ext}`，不使用原始文件名；
- 桶必须保持私有，对外读取使用 S3 V4 预签名 URL；
- SVG 当前不支持，避免主动内容进入富文本展示链路；
- `MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY` 只能由后端读取，不能下发前端或写入数据库。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MINIO_ENDPOINT_URL` | `http://127.0.0.1:9000` | 后端访问地址 |
| `MINIO_PUBLIC_ENDPOINT_URL` | 空 | 浏览器可访问的签名 URL 地址；空时复用内部地址 |
| `MINIO_ACCESS_KEY` | 空 | S3 access key，必填 |
| `MINIO_SECRET_KEY` | 空 | S3 secret key，必填 |
| `MINIO_BUCKET` | `testplatform` | 已预先创建的私有桶 |
| `MINIO_REGION` | `us-east-1` | S3 签名区域 |
| `MINIO_SECURE` | `false` | 地址未写 scheme 时是否补 `https` |
| `MEDIA_MAX_IMAGE_BYTES` | `10485760` | 图片最大字节数 |
| `MEDIA_PRESIGNED_URL_EXPIRE_SECONDS` | `3600` | 临时地址有效期 |

`MINIO_ENDPOINT_URL` 必须从后端进程所在主机可访问；只有 MinIO 与后端运行在同一台主机时才能使用
`127.0.0.1`/`localhost`。跨主机部署时应填写 MinIO 的局域网或公网地址。
`MINIO_PUBLIC_ENDPOINT_URL` 则必须从用户浏览器可访问；通过统一公网域名访问 MinIO 时，两个端点可以配置为
同一个 HTTPS 地址，例如 `https://minio.example.com`。

服务账号至少需要对 `testplatform/projects/*` 执行 `s3:PutObject`、`s3:GetObject` 和
`s3:DeleteObject`。桶创建、生命周期、版本控制和管理员权限不属于应用运行时账号职责。

## 迁移与运维

- Alembic revision：`0019_media_objects`；部署前执行 `alembic upgrade head`。
- 应用不会自动创建桶，部署时应预建私有 `testplatform` 桶并验证服务账号权限。
- MinIO 与 MySQL 不支持跨系统事务；建议生产环境增加未绑定对象生命周期、孤儿对象巡检和
  删除 outbox。当前上传元数据失败时会立即补偿删除对象。
