# 数据库迁移

本目录用于 Alembic 数据库迁移。

常用命令：

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe revision --autogenerate -m "message"
```

数据库连接优先读取 `.env` 中的 `DATABASE_URL`。

