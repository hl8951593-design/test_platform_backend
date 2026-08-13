import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.permissions import ProjectPermission
from app.core.sensitive_data import mask_sensitive, reveal_secret_text
from app.models.database_connection import (
    DatabaseActionExecution,
    ProjectDatabaseConnection,
)
from app.models.user import User
from app.repositories.database_connection_repository import DatabaseConnectionRepository
from app.schemas.database_connection import DatabaseActionConfig
from app.services.permission_service import PermissionService


_SQL_QUERY_TYPES = {"SELECT"}
_SQL_WRITE_TYPES = {"INSERT", "UPDATE", "DELETE"}
_MONGO_QUERY_OPERATIONS = {"find", "find_one", "count_documents", "aggregate"}
_MONGO_WRITE_OPERATIONS = {
    "insert_one",
    "insert_many",
    "update_one",
    "update_many",
    "delete_one",
    "delete_many",
}
_FORBIDDEN_MONGO_KEYS = {"$where", "$function", "$accumulator", "$out", "$merge"}
_MISSING = object()


@dataclass
class DatabaseActionResult:
    execution_id: int
    status: str
    runtime_output: dict[str, Any]
    stored_output: dict[str, Any]
    assertion_results: list[dict[str, Any]]
    extracted_variables: list[dict[str, Any]]
    extracted_values: dict[str, Any]
    attempt_history: list[dict[str, Any]]
    error_message: str
    duration_ms: int
    request_snapshot: dict[str, Any]


def validate_database_action(
    connection: ProjectDatabaseConnection,
    kind: str,
    config: DatabaseActionConfig,
) -> None:
    if kind == "database_execute" and config.retry_policy.max_attempts != 1:
        raise ValueError("数据库写操作禁止自动重试")
    if connection.provider in {"mysql", "postgresql"}:
        _validated_sql(config.sql, query=kind == "database_query")
        return
    operation = (
        config.operation
        or ("find" if kind == "database_query" else "")
    ).lower()
    allowed = (
        _MONGO_QUERY_OPERATIONS
        if kind == "database_query"
        else _MONGO_WRITE_OPERATIONS
    )
    if operation not in allowed:
        raise ValueError(f"MongoDB 操作不支持: {operation}")
    if not (config.collection or "").strip():
        raise ValueError("MongoDB 数据库动作必须提供 collection")
    for value in (
        config.filter,
        config.projection,
        config.pipeline,
        config.document,
        config.documents,
        config.update,
    ):
        _validate_mongo_document(value)
    if operation == "insert_one" and config.document is None:
        raise ValueError("insert_one 必须提供 document")
    if operation == "insert_many" and not config.documents:
        raise ValueError("insert_many 必须提供 documents")
    if operation in {"update_one", "update_many"} and not config.update:
        raise ValueError(f"{operation} 必须提供 update")


class DatabaseTargetClient:
    def __init__(self, connection: ProjectDatabaseConnection):
        self.connection = connection

    def test_connection(self) -> dict[str, Any]:
        if self.connection.provider == "mongodb":
            client = self._mongo_client()
            try:
                result = client.admin.command("ping")
                server_info = client.server_info()
                return {
                    "ok": bool(result.get("ok")),
                    "version": server_info.get("version"),
                }
            finally:
                client.close()
        engine = self._sql_engine()
        try:
            with engine.connect() as target:
                version_sql = (
                    "SELECT VERSION() AS version"
                    if self.connection.provider == "mysql"
                    else "SELECT version() AS version"
                )
                version = target.execute(text(version_sql)).scalar_one()
                return {"version": str(version)}
        finally:
            engine.dispose()

    def query(self, config: DatabaseActionConfig) -> dict[str, Any]:
        if self.connection.provider == "mongodb":
            return self._mongo_query(config)
        return self._sql_query(config)

    def execute(self, config: DatabaseActionConfig) -> dict[str, Any]:
        if self.connection.provider == "mongodb":
            return self._mongo_execute(config)
        return self._sql_execute(config)

    def _sql_engine(self):
        provider = self.connection.provider
        driver = "mysql+pymysql" if provider == "mysql" else "postgresql+psycopg"
        password = (
            reveal_secret_text(self.connection.password_encrypted)
            if self.connection.password_encrypted
            else None
        )
        query: dict[str, str] = {}
        options = self.connection.options_json or {}
        if provider == "mysql":
            query["charset"] = str(options.get("charset") or "utf8mb4")
        if provider == "postgresql" and options.get("ssl_mode"):
            query["sslmode"] = str(options["ssl_mode"])
        if options.get("ssl_root_cert"):
            query["sslrootcert"] = str(options["ssl_root_cert"])
        url = URL.create(
            driver,
            username=self.connection.username,
            password=password,
            host=self.connection.host,
            port=self.connection.port,
            database=self.connection.database_name,
            query=query,
        )
        timeout_seconds = max(1, int(self.connection.connect_timeout_ms / 1000))
        connect_args: dict[str, Any]
        if provider == "mysql":
            connect_args = {
                "connect_timeout": timeout_seconds,
                "read_timeout": max(1, int(self.connection.statement_timeout_ms / 1000)),
                "write_timeout": max(1, int(self.connection.statement_timeout_ms / 1000)),
            }
            if options.get("tls"):
                connect_args["ssl"] = (
                    {"ca": options["ssl_ca"]}
                    if options.get("ssl_ca")
                    else {}
                )
        else:
            connect_args = {"connect_timeout": timeout_seconds}
        try:
            return create_engine(
                url,
                poolclass=NullPool,
                pool_pre_ping=True,
                connect_args=connect_args,
                future=True,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(f"数据库驱动未安装: {driver}") from exc

    def _sql_query(self, config: DatabaseActionConfig) -> dict[str, Any]:
        sql = _validated_sql(config.sql, query=True)
        max_rows = min(config.max_rows or self.connection.max_rows, self.connection.max_rows)
        timeout_ms = min(
            config.timeout_ms or self.connection.statement_timeout_ms,
            self.connection.statement_timeout_ms,
        )
        engine = self._sql_engine()
        try:
            with engine.connect() as target:
                transaction = target.begin()
                try:
                    if self.connection.provider == "postgresql":
                        target.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                        target.exec_driver_sql("SET TRANSACTION READ ONLY")
                    elif self.connection.provider == "mysql":
                        target.exec_driver_sql(
                            f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_ms)}"
                        )
                    result = target.execute(text(sql), dict(config.parameters))
                    columns = list(result.keys())
                    raw_rows = result.mappings().fetchmany(max_rows + 1)
                    truncated = len(raw_rows) > max_rows
                    rows = [_json_value(dict(row)) for row in raw_rows[:max_rows]]
                finally:
                    transaction.rollback()
        finally:
            engine.dispose()
        scalar = rows[0].get(columns[0]) if rows and columns else None
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "scalar": scalar,
            "truncated": truncated,
        }

    def _sql_execute(self, config: DatabaseActionConfig) -> dict[str, Any]:
        sql = _validated_sql(config.sql, query=False)
        engine = self._sql_engine()
        try:
            with engine.begin() as target:
                if self.connection.provider == "postgresql":
                    timeout_ms = min(
                        config.timeout_ms or self.connection.statement_timeout_ms,
                        self.connection.statement_timeout_ms,
                    )
                    target.exec_driver_sql(
                        f"SET LOCAL statement_timeout = {int(timeout_ms)}"
                    )
                result = target.execute(text(sql), dict(config.parameters))
                affected_rows = max(0, int(result.rowcount or 0))
        finally:
            engine.dispose()
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "scalar": None,
            "affected_rows": affected_rows,
            "truncated": False,
        }

    def _mongo_client(self):
        try:
            from pymongo import MongoClient
        except ModuleNotFoundError as exc:
            raise RuntimeError("数据库驱动未安装: pymongo") from exc
        options = self.connection.options_json or {}
        password = (
            reveal_secret_text(self.connection.password_encrypted)
            if self.connection.password_encrypted
            else None
        )
        credentials = ""
        if self.connection.username:
            credentials = quote_plus(self.connection.username)
            if password is not None:
                credentials += f":{quote_plus(password)}"
            credentials += "@"
        use_srv = bool(options.get("use_srv"))
        scheme = "mongodb+srv" if use_srv else "mongodb"
        authority = self.connection.host
        if not use_srv and self.connection.port:
            authority += f":{self.connection.port}"
        uri = f"{scheme}://{credentials}{authority}/{quote_plus(self.connection.database_name)}"
        client_options: dict[str, Any] = {
            "serverSelectionTimeoutMS": self.connection.connect_timeout_ms,
            "connectTimeoutMS": self.connection.connect_timeout_ms,
            "socketTimeoutMS": self.connection.statement_timeout_ms,
        }
        if options.get("auth_source"):
            client_options["authSource"] = options["auth_source"]
        if options.get("replica_set"):
            client_options["replicaSet"] = options["replica_set"]
        if "tls" in options:
            client_options["tls"] = bool(options["tls"])
        return MongoClient(uri, **client_options)

    def _mongo_query(self, config: DatabaseActionConfig) -> dict[str, Any]:
        operation = (config.operation or "find").lower()
        if operation not in _MONGO_QUERY_OPERATIONS:
            raise ValueError(f"MongoDB 查询操作不支持: {operation}")
        if not (config.collection or "").strip():
            raise ValueError("MongoDB 查询必须提供 collection")
        _validate_mongo_document(config.filter)
        _validate_mongo_document(config.projection)
        _validate_mongo_document(config.pipeline)
        max_rows = min(config.max_rows or self.connection.max_rows, self.connection.max_rows)
        timeout_ms = min(
            config.timeout_ms or self.connection.statement_timeout_ms,
            self.connection.statement_timeout_ms,
        )
        client = self._mongo_client()
        try:
            collection = client[self.connection.database_name][config.collection]
            if operation == "find":
                cursor = collection.find(
                    config.filter,
                    config.projection,
                    max_time_ms=timeout_ms,
                )
                if config.sort:
                    cursor = cursor.sort(
                        [(str(item[0]), int(item[1])) for item in config.sort]
                    )
                raw_rows = list(cursor.limit(max_rows + 1))
                truncated = len(raw_rows) > max_rows
                rows = [_json_value(row) for row in raw_rows[:max_rows]]
            elif operation == "find_one":
                item = collection.find_one(
                    config.filter,
                    config.projection,
                    max_time_ms=timeout_ms,
                )
                rows = [] if item is None else [_json_value(item)]
                truncated = False
            elif operation == "count_documents":
                count = collection.count_documents(
                    config.filter, maxTimeMS=timeout_ms
                )
                rows = [{"count": int(count)}]
                truncated = False
            else:
                pipeline = [copy.deepcopy(item) for item in config.pipeline]
                pipeline.append({"$limit": max_rows + 1})
                raw_rows = list(collection.aggregate(pipeline, maxTimeMS=timeout_ms))
                truncated = len(raw_rows) > max_rows
                rows = [_json_value(row) for row in raw_rows[:max_rows]]
        finally:
            client.close()
        if operation == "count_documents":
            row_count = int(rows[0]["count"])
            scalar = row_count
        else:
            row_count = len(rows)
            scalar = next(iter(rows[0].values()), None) if rows else None
        columns = list(rows[0]) if rows else []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "scalar": scalar,
            "truncated": truncated,
        }

    def _mongo_execute(self, config: DatabaseActionConfig) -> dict[str, Any]:
        operation = (config.operation or "").lower()
        if operation not in _MONGO_WRITE_OPERATIONS:
            raise ValueError(f"MongoDB 写操作不支持: {operation}")
        if not (config.collection or "").strip():
            raise ValueError("MongoDB 写操作必须提供 collection")
        for value in (
            config.filter,
            config.document,
            config.documents,
            config.update,
        ):
            _validate_mongo_document(value)
        client = self._mongo_client()
        try:
            collection = client[self.connection.database_name][config.collection]
            if operation == "insert_one":
                if config.document is None:
                    raise ValueError("insert_one 必须提供 document")
                result = collection.insert_one(copy.deepcopy(config.document))
                affected_rows = 1
                extra = {"inserted_ids": [_json_value(result.inserted_id)]}
            elif operation == "insert_many":
                if not config.documents:
                    raise ValueError("insert_many 必须提供 documents")
                result = collection.insert_many(copy.deepcopy(config.documents))
                affected_rows = len(result.inserted_ids)
                extra = {"inserted_ids": [_json_value(item) for item in result.inserted_ids]}
            elif operation in {"update_one", "update_many"}:
                if not config.update:
                    raise ValueError(f"{operation} 必须提供 update")
                if not any(str(key).startswith("$") for key in config.update):
                    raise ValueError("MongoDB update 必须使用 $set 等更新操作符")
                method = getattr(collection, operation)
                result = method(
                    copy.deepcopy(config.filter),
                    copy.deepcopy(config.update),
                    upsert=config.upsert,
                )
                affected_rows = int(result.modified_count)
                extra = {
                    "matched_rows": int(result.matched_count),
                    "upserted_id": _json_value(result.upserted_id),
                }
            else:
                method = getattr(collection, operation)
                result = method(copy.deepcopy(config.filter))
                affected_rows = int(result.deleted_count)
                extra = {}
        finally:
            client.close()
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "scalar": None,
            "affected_rows": affected_rows,
            "truncated": False,
            **extra,
        }


class DatabaseActionExecutor:
    def __init__(self, db: Session):
        self.db = db
        self.repository = DatabaseConnectionRepository(db)
        self.permission_service = PermissionService(db)

    def execute(
        self,
        *,
        project_id: int,
        environment_id: int,
        scenario_run_id: int | None,
        step_id: str,
        kind: str,
        raw_config: dict[str, Any],
        current_user: User,
    ) -> DatabaseActionResult:
        config = DatabaseActionConfig.model_validate(raw_config)
        connection = self._resolve_connection(
            project_id=project_id,
            environment_id=environment_id,
            connection_id=config.connection_id,
            connection_key=config.connection_key,
        )
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.EXECUTE_DATABASE.value
        )
        if kind == "database_execute":
            self.permission_service.require_project_permission(
                current_user, project_id, ProjectPermission.WRITE_DATABASE.value
            )
            if not connection.allow_writes:
                raise ValueError("该数据库连接未开启写操作")
            if config.retry_policy.max_attempts != 1:
                raise ValueError("数据库写操作禁止自动重试")
        if not connection.is_enabled:
            raise ValueError("数据库连接已停用")
        from app.services.database_connection_service import DatabaseConnectionService

        DatabaseConnectionService._validate_target_host(connection.host, connection.port)
        validate_database_action(connection, kind, config)

        request_snapshot = self._request_snapshot(connection, config, kind)
        started_at = datetime.now(UTC).replace(tzinfo=None)
        execution = DatabaseActionExecution(
            project_id=project_id,
            environment_id=environment_id,
            connection_id=connection.id,
            scenario_run_id=scenario_run_id,
            step_id=step_id,
            action_kind=kind,
            provider=connection.provider,
            operation=self._operation(connection, config, kind),
            statement_fingerprint=self._statement_fingerprint(connection, config),
            request_snapshot=mask_sensitive(request_snapshot),
            status="running",
            triggered_by_id=current_user.id,
            started_at=started_at,
        )
        self.repository.add_execution(execution)
        self.db.commit()
        self.db.refresh(execution)

        attempts: list[dict[str, Any]] = []
        runtime_output: dict[str, Any] = {}
        assertion_results: list[dict[str, Any]] = []
        error_message = ""
        status_value = "failed"
        target = DatabaseTargetClient(connection)
        for attempt in range(1, config.retry_policy.max_attempts + 1):
            attempt_started = time.perf_counter()
            try:
                runtime_output = (
                    target.query(config)
                    if kind == "database_query"
                    else target.execute(config)
                )
                assertion_results = _run_assertions(config, runtime_output)
                passed = all(item["passed"] for item in assertion_results)
                error_message = "" if passed else "数据库断言失败"
                status_value = "passed" if passed else "failed"
            except Exception as exc:  # noqa: BLE001
                passed = False
                status_value = "failed"
                error_message = str(exc)
                runtime_output = {}
                assertion_results = []
            attempts.append(
                {
                    "attempt": attempt,
                    "status": status_value,
                    "duration_ms": max(
                        0, int((time.perf_counter() - attempt_started) * 1000)
                    ),
                    "assertion_results": copy.deepcopy(assertion_results),
                    "error_message": error_message,
                }
            )
            if passed:
                break
            if attempt < config.retry_policy.max_attempts:
                time.sleep(config.retry_policy.interval_ms / 1000)

        extracted_values: dict[str, Any] = {}
        extracted_variables: list[dict[str, Any]] = []
        if status_value == "passed":
            for extractor in config.extractors:
                found, value = _read_path(runtime_output, extractor.path)
                if not found and extractor.required:
                    status_value = "failed"
                    error_message = f"数据库取值路径不存在: {extractor.path}"
                    break
                if not found:
                    continue
                extracted_values[extractor.name] = copy.deepcopy(value)
                extracted_variables.append(
                    {
                        "extraction_id": f"database:{step_id}:{extractor.name}",
                        "name": extractor.name,
                        "path": extractor.path,
                        "value": "***" if extractor.masked else copy.deepcopy(value),
                        "masked": extractor.masked,
                    }
                )

        finished_at = datetime.now(UTC).replace(tzinfo=None)
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        stored_output = mask_sensitive(_json_value(runtime_output))
        execution.status = status_value
        execution.result_snapshot = stored_output
        execution.assertion_results = mask_sensitive(assertion_results)
        execution.attempt_history = mask_sensitive(attempts)
        execution.error_message = error_message or None
        execution.duration_ms = duration_ms
        execution.finished_at = finished_at
        self.db.commit()

        return DatabaseActionResult(
            execution_id=execution.id,
            status=status_value,
            runtime_output=runtime_output,
            stored_output=stored_output,
            assertion_results=mask_sensitive(assertion_results),
            extracted_variables=extracted_variables,
            extracted_values=extracted_values,
            attempt_history=mask_sensitive(attempts),
            error_message=error_message,
            duration_ms=duration_ms,
            request_snapshot=mask_sensitive(request_snapshot),
        )

    def _resolve_connection(
        self,
        *,
        project_id: int,
        environment_id: int,
        connection_id: int | None,
        connection_key: str | None,
    ) -> ProjectDatabaseConnection:
        item = None
        if connection_key:
            item = self.repository.get_connection_by_key(
                project_id=project_id,
                environment_id=environment_id,
                connection_key=connection_key,
            )
        if item is None and connection_id is not None:
            item = self.repository.get_connection(
                project_id=project_id,
                environment_id=environment_id,
                connection_id=connection_id,
            )
        if item is None:
            raise ValueError("当前执行环境中找不到数据库连接")
        return item

    @staticmethod
    def _request_snapshot(
        connection: ProjectDatabaseConnection,
        config: DatabaseActionConfig,
        kind: str,
    ) -> dict[str, Any]:
        payload = config.model_dump(mode="json")
        return {
            "connection": {
                "id": connection.id,
                "connection_key": connection.connection_key,
                "name": connection.name,
                "provider": connection.provider,
                "host": connection.host,
                "port": connection.port,
                "database_name": connection.database_name,
            },
            "kind": kind,
            "config": payload,
        }

    @staticmethod
    def _operation(
        connection: ProjectDatabaseConnection,
        config: DatabaseActionConfig,
        kind: str,
    ) -> str:
        if connection.provider == "mongodb":
            return (config.operation or ("find" if kind == "database_query" else "")).lower()
        return _sql_type(config.sql)

    @staticmethod
    def _statement_fingerprint(
        connection: ProjectDatabaseConnection, config: DatabaseActionConfig
    ) -> str:
        value: Any = config.sql if connection.provider != "mongodb" else {
            "collection": config.collection,
            "operation": config.operation,
            "filter": config.filter,
            "pipeline": config.pipeline,
            "document": config.document,
            "documents": config.documents,
            "update": config.update,
        }
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()


def _validated_sql(value: str | None, *, query: bool) -> str:
    sql = (value or "").strip()
    if not sql:
        raise ValueError("SQL 不能为空")
    if "{{" in sql or "}}" in sql:
        raise ValueError("SQL 文本禁止直接插入模板变量，请使用命名参数")
    try:
        import sqlparse
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQL 安全解析依赖未安装: sqlparse") from exc
    statements = [item for item in sqlparse.parse(sql) if str(item).strip()]
    if len(statements) != 1:
        raise ValueError("一次数据库动作只能执行一条 SQL")
    statement_type = statements[0].get_type().upper()
    allowed = _SQL_QUERY_TYPES if query else _SQL_WRITE_TYPES
    if statement_type not in allowed:
        expected = "SELECT" if query else "INSERT/UPDATE/DELETE"
        raise ValueError(f"该数据库动作只允许 {expected}")
    return sql


def _sql_type(value: str | None) -> str:
    raw = re.sub(r"^\s*(?:--[^\n]*\n|/\*.*?\*/\s*)*", "", value or "", flags=re.S)
    match = re.match(r"([A-Za-z]+)", raw)
    return match.group(1).upper() if match else "UNKNOWN"


def _validate_mongo_document(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_MONGO_KEYS:
                raise ValueError(f"MongoDB 操作符不允许使用: {key}")
            _validate_mongo_document(item)
    elif isinstance(value, list):
        for item in value:
            _validate_mongo_document(item)


def _run_assertions(
    config: DatabaseActionConfig, output: dict[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for assertion in config.assertions:
        if assertion.type == "row_count":
            actual = output.get("row_count", 0)
        elif assertion.type == "affected_rows":
            actual = output.get("affected_rows", 0)
        elif assertion.type == "exists":
            actual = output.get("row_count", 0) > 0
        elif assertion.type == "not_exists":
            actual = output.get("row_count", 0) == 0
        else:
            found, actual = _read_path(output, assertion.path or "")
            if not found:
                actual = None
        expected = (
            True
            if assertion.type in {"exists", "not_exists"} and assertion.expected is None
            else assertion.expected
        )
        passed = _compare(actual, expected, assertion.operator)
        results.append(
            {
                "assertion": assertion.model_dump(mode="json"),
                "actual": _json_value(actual),
                "expected": _json_value(expected),
                "passed": passed,
            }
        )
    return results


def _compare(actual: Any, expected: Any, operator: str) -> bool:
    try:
        if operator == "eq":
            return actual == expected
        if operator == "ne":
            return actual != expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "contains":
            return expected in actual
        if operator == "not_contains":
            return expected not in actual
    except (TypeError, ValueError):
        return False
    return False


def _read_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    if not path:
        return True, copy.deepcopy(current)
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, copy.deepcopy(current)


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
