from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from app.core.config import settings


class MySQLClientError(Exception):
    """Base error for MySQL client operations."""


class MySQLConfigurationError(MySQLClientError):
    """Raised when MySQL client configuration is invalid."""


class MySQLQueryError(MySQLClientError):
    """Raised when MySQL query execution fails."""


class SQLSafetyError(ValueError):
    """Raised when a SQL statement violates the read-only safety policy."""


@dataclass(frozen=True)
class SQLQueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str


@dataclass(frozen=True)
class SchemaColumn:
    table_name: str
    column_name: str
    data_type: str
    column_comment: str


FORBIDDEN_SQL_RE = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"call|execute|merge|load|outfile|infile|lock|unlock"
    r")\b",
    re.IGNORECASE,
)
COMMENT_RE = re.compile(r"(--|#|/\*)")
TABLE_RE = re.compile(r"\b(?:from|join)\s+([`\"\[]?[\w.]+[`\"\]]?)", re.IGNORECASE)
LIMIT_RE = re.compile(r"\blimit\s+(\d+)(?:\s+offset\s+\d+)?\s*$", re.IGNORECASE)


class MySQLStore:
    def __init__(
        self,
        url: str,
        *,
        allowed_tables: list[str],
        connect_timeout_seconds: float = 3.0,
        query_timeout_seconds: float = 5.0,
        default_limit: int = 50,
        max_limit: int = 100,
    ) -> None:
        self.url = url
        self.allowed_tables = allowed_tables
        self.connect_timeout_seconds = connect_timeout_seconds
        self.query_timeout_seconds = query_timeout_seconds
        self.default_limit = default_limit
        self.max_limit = max_limit

    @classmethod
    def from_settings(cls) -> MySQLStore:
        return cls(
            settings.mysql_url,
            allowed_tables=settings.mysql_allowed_tables,
            connect_timeout_seconds=settings.mysql_connect_timeout_seconds,
            query_timeout_seconds=settings.mysql_query_timeout_seconds,
            default_limit=settings.mysql_default_limit,
            max_limit=settings.mysql_max_limit,
        )

    async def aclose(self) -> None:
        return None

    async def ping(self) -> bool:
        return await asyncio.to_thread(self._ping_sync)

    async def execute_select(self, sql: str) -> SQLQueryResult:
        safe_sql = prepare_safe_select(
            sql,
            allowed_tables=self.allowed_tables,
            default_limit=self.default_limit,
            max_limit=self.max_limit,
        )
        return await asyncio.to_thread(self._execute_select_sync, safe_sql)

    async def inspect_schema(self) -> list[SchemaColumn]:
        return await asyncio.to_thread(self._inspect_schema_sync)

    def _ping_sync(self) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return cursor.fetchone() is not None
        except Exception as exc:
            raise MySQLQueryError(str(exc)) from exc

    def _execute_select_sync(self, sql: str) -> SQLQueryResult:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    rows = list(cursor.fetchall())
                    columns = [item[0] for item in cursor.description or []]
        except SQLSafetyError:
            raise
        except Exception as exc:
            raise MySQLQueryError(str(exc)) from exc
        return SQLQueryResult(columns=columns, rows=[dict(row) for row in rows], sql=sql)

    def _inspect_schema_sync(self) -> list[SchemaColumn]:
        if not self.allowed_tables:
            raise MySQLConfigurationError("MYSQL_ALLOWED_TABLES must not be empty.")
        placeholders = ", ".join(["%s"] * len(self.allowed_tables))
        sql = (
            "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, "
            "DATA_TYPE AS data_type, COLUMN_COMMENT AS column_comment "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            f"AND TABLE_NAME IN ({placeholders}) "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, tuple(self.allowed_tables))
                    rows = cursor.fetchall()
        except Exception as exc:
            raise MySQLQueryError(str(exc)) from exc
        return [
            SchemaColumn(
                table_name=str(row["table_name"]),
                column_name=str(row["column_name"]),
                data_type=str(row["data_type"]),
                column_comment=str(row.get("column_comment") or ""),
            )
            for row in rows
        ]

    def _connect(self):
        pymysql = _import_pymysql()
        parsed = urlparse(self.url)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise MySQLConfigurationError(
                "MYSQL_URL must use mysql:// or mysql+pymysql://."
            )
        if not parsed.hostname:
            raise MySQLConfigurationError("MYSQL_URL must include a host.")
        database = parsed.path.lstrip("/") or None
        return pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=database,
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=max(1, int(self.connect_timeout_seconds)),
            read_timeout=max(1, int(self.query_timeout_seconds)),
            write_timeout=max(1, int(self.query_timeout_seconds)),
            cursorclass=pymysql.cursors.DictCursor,
        )


def prepare_safe_select(
    sql: str,
    *,
    allowed_tables: list[str],
    default_limit: int,
    max_limit: int,
) -> str:
    normalized = normalize_sql(sql)
    validate_readonly_select(normalized, allowed_tables=allowed_tables)
    return enforce_limit(normalized, default_limit=default_limit, max_limit=max_limit)


def normalize_sql(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        raise SQLSafetyError("SQL must not be empty.")
    if COMMENT_RE.search(normalized):
        raise SQLSafetyError("SQL comments are not allowed.")
    if ";" in normalized.rstrip(";"):
        raise SQLSafetyError("Multiple SQL statements are not allowed.")
    return normalized.rstrip(";").strip()


def validate_readonly_select(sql: str, *, allowed_tables: list[str]) -> None:
    if not re.match(r"^\s*select\b", sql, re.IGNORECASE):
        raise SQLSafetyError("Only SELECT statements are allowed.")
    if FORBIDDEN_SQL_RE.search(sql):
        raise SQLSafetyError("DDL/DML statements are not allowed.")
    tables = extract_table_names(sql)
    if not tables:
        raise SQLSafetyError("SQL must read from an allowed table.")
    disallowed = sorted(set(tables) - set(allowed_tables))
    if disallowed:
        raise SQLSafetyError(
            "SQL references disallowed tables: " + ", ".join(disallowed)
        )


def enforce_limit(sql: str, *, default_limit: int, max_limit: int) -> str:
    if re.search(r"\blimit\s+\d+\s*,", sql, re.IGNORECASE):
        raise SQLSafetyError("LIMIT offset,count syntax is not allowed.")
    match = LIMIT_RE.search(sql)
    if match is None:
        return f"{sql} LIMIT {default_limit}"
    requested_limit = int(match.group(1))
    if requested_limit <= max_limit:
        return sql
    return LIMIT_RE.sub(f"LIMIT {max_limit}", sql)


def extract_table_names(sql: str) -> list[str]:
    table_names: list[str] = []
    for raw_name in TABLE_RE.findall(sql):
        cleaned = raw_name.strip("`\"[]")
        if "." in cleaned:
            cleaned = cleaned.split(".")[-1]
        table_names.append(cleaned)
    return table_names


def _import_pymysql():
    try:
        import pymysql
    except ImportError as exc:
        raise MySQLConfigurationError(
            "PyMySQL is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return pymysql
