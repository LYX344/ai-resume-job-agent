from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.services.mysql_client import SQLQueryResult


class DatabaseStore(Protocol):
    async def execute_select(self, sql: str) -> SQLQueryResult:
        ...


@dataclass(frozen=True)
class DatabaseQueryPlan:
    sql: str
    title: str


@dataclass(frozen=True)
class DatabaseToolResult:
    query: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    markdown: str

    @property
    def row_count(self) -> int:
        return len(self.rows)


APPLICATION_KEYWORDS = (
    "投递",
    "投了",
    "投过",
    "简历",
    "岗位",
    "公司",
    "面试",
    "offer",
    "Offer",
    "HR",
    "hr",
    "内推",
)
DATA_QUERY_KEYWORDS = (
    "哪些",
    "哪家",
    "什么岗位",
    "多少",
    "几个",
    "统计",
    "状态",
    "进展",
    "渠道",
    "记录",
    "列表",
    "有没有",
    "本月",
    "最近",
)


def is_job_application_query(query: str) -> bool:
    return any(keyword in query for keyword in APPLICATION_KEYWORDS) and any(
        keyword in query for keyword in DATA_QUERY_KEYWORDS
    )


async def query_database(
    query: str,
    *,
    database_store: DatabaseStore,
) -> DatabaseToolResult:
    plan = build_job_application_query_plan(query)
    result = await database_store.execute_select(plan.sql)
    return DatabaseToolResult(
        query=query,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        markdown=format_database_result(plan.title, result),
    )


def build_job_application_query_plan(query: str) -> DatabaseQueryPlan:
    where_clause = _time_filter_clause(query)
    where_prefix = f"{where_clause} " if where_clause else ""

    if "渠道" in query:
        return DatabaseQueryPlan(
            sql=(
                "SELECT channel, COUNT(*) AS application_count "
                "FROM job_applications "
                f"{where_prefix}"
                "GROUP BY channel "
                "ORDER BY application_count DESC, channel ASC"
            ),
            title="投递渠道统计",
        )

    if any(keyword in query for keyword in ("多少", "几个", "统计", "总数")):
        return DatabaseQueryPlan(
            sql=(
                "SELECT COUNT(*) AS application_count "
                "FROM job_applications "
                f"{where_clause}"
            ),
            title="投递数量统计",
        )

    if "面试" in query or "offer" in query or "Offer" in query:
        sql = (
            "SELECT company, role, status, applied_at, city, channel "
            "FROM job_applications "
            "WHERE (status IN ('interview', 'offer') OR status LIKE '%面试%') "
        )
        if where_clause:
            sql += "AND applied_at >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01') "
        sql += "ORDER BY applied_at DESC, id DESC"
        return DatabaseQueryPlan(sql=sql, title="面试和 Offer 相关投递")

    if "状态" in query or "进展" in query:
        return DatabaseQueryPlan(
            sql=(
                "SELECT company, role, status, applied_at, channel "
                "FROM job_applications "
                f"{where_prefix}"
                "ORDER BY applied_at DESC, id DESC"
            ),
            title="投递状态列表",
        )

    if "城市" in query or "地点" in query:
        return DatabaseQueryPlan(
            sql=(
                "SELECT company, role, city, status, applied_at "
                "FROM job_applications "
                f"{where_prefix}"
                "ORDER BY applied_at DESC, id DESC"
            ),
            title="投递城市列表",
        )

    if "薪资" in query or "工资" in query:
        return DatabaseQueryPlan(
            sql=(
                "SELECT company, role, salary_min, salary_max, status, applied_at "
                "FROM job_applications "
                f"{where_prefix}"
                "ORDER BY applied_at DESC, id DESC"
            ),
            title="投递薪资范围列表",
        )

    return DatabaseQueryPlan(
        sql=(
            "SELECT company, role, channel, applied_at, status "
            "FROM job_applications "
            f"{where_prefix}"
            "ORDER BY applied_at DESC, id DESC"
        ),
        title="简历投递记录",
    )


def _time_filter_clause(query: str) -> str:
    if "本月" in query or "这个月" in query:
        return "WHERE applied_at >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')"
    return ""


def format_database_result(title: str, result: SQLQueryResult) -> str:
    lines = [f"{title}：", "", f"SQL：`{result.sql}`", ""]
    if not result.rows:
        lines.append("没有查到匹配的投递记录。")
        return "\n".join(lines)

    lines.append(_format_markdown_table(result.columns, result.rows))
    lines.append("")
    lines.append(f"共返回 {len(result.rows)} 条记录。")
    return "\n".join(lines)


def _format_markdown_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = [
        "| "
        + " | ".join(_format_cell(row.get(column)) for column in columns)
        + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value).replace("|", "\\|").replace("\n", " ")
