import pytest

from app.services.mysql_client import SQLQueryResult
from app.tools.query_database import (
    build_job_application_query_plan,
    is_job_application_query,
    query_database,
)

pytestmark = pytest.mark.anyio


class FakeDatabaseStore:
    def __init__(self) -> None:
        self.executed_sql = ""

    async def execute_select(self, sql: str) -> SQLQueryResult:
        self.executed_sql = sql
        return SQLQueryResult(
            columns=["company", "role", "status"],
            rows=[
                {
                    "company": "腾讯",
                    "role": "AI 应用开发实习生",
                    "status": "interview",
                }
            ],
            sql=f"{sql} LIMIT 50",
        )


def test_is_job_application_query_detects_structured_application_questions() -> None:
    assert is_job_application_query("我投了哪些公司的什么岗位？") is True
    assert is_job_application_query("Redis 在这个项目里做什么？") is False


def test_build_job_application_query_plan_uses_channel_statistics() -> None:
    plan = build_job_application_query_plan("投递渠道统计一下")

    assert plan.title == "投递渠道统计"
    assert "GROUP BY channel" in plan.sql
    assert "job_applications" in plan.sql


async def test_query_database_returns_markdown_result() -> None:
    database_store = FakeDatabaseStore()

    result = await query_database(
        "我投了哪些公司的什么岗位？",
        database_store=database_store,
    )

    assert result.row_count == 1
    assert "SELECT company, role, channel, applied_at, status" in database_store.executed_sql
    assert "SQL：`" in result.markdown
    assert "| company | role | status |" in result.markdown
    assert "腾讯" in result.markdown
