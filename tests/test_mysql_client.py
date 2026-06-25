import pytest

from app.services.mysql_client import (
    SQLSafetyError,
    enforce_limit,
    extract_table_names,
    normalize_sql,
    prepare_safe_select,
    validate_readonly_select,
)


ALLOWED_TABLES = ["job_applications", "application_events"]


def test_normalize_sql_removes_single_trailing_semicolon() -> None:
    assert normalize_sql(" SELECT * FROM job_applications; ") == (
        "SELECT * FROM job_applications"
    )


def test_normalize_sql_rejects_multiple_statements() -> None:
    with pytest.raises(SQLSafetyError, match="Multiple SQL statements"):
        normalize_sql("SELECT * FROM job_applications; SELECT * FROM users")


def test_validate_readonly_select_rejects_dml() -> None:
    with pytest.raises(SQLSafetyError, match="Only SELECT"):
        validate_readonly_select(
            "DELETE FROM job_applications",
            allowed_tables=ALLOWED_TABLES,
        )


def test_validate_readonly_select_rejects_disallowed_tables() -> None:
    with pytest.raises(SQLSafetyError, match="disallowed"):
        validate_readonly_select(
            "SELECT * FROM users",
            allowed_tables=ALLOWED_TABLES,
        )


def test_prepare_safe_select_adds_limit() -> None:
    assert prepare_safe_select(
        "SELECT company, role FROM job_applications",
        allowed_tables=ALLOWED_TABLES,
        default_limit=50,
        max_limit=100,
    ) == "SELECT company, role FROM job_applications LIMIT 50"


def test_prepare_safe_select_caps_large_limit() -> None:
    assert prepare_safe_select(
        "SELECT company, role FROM job_applications LIMIT 500",
        allowed_tables=ALLOWED_TABLES,
        default_limit=50,
        max_limit=100,
    ) == "SELECT company, role FROM job_applications LIMIT 100"


def test_enforce_limit_rejects_offset_count_syntax() -> None:
    with pytest.raises(SQLSafetyError, match="offset,count"):
        enforce_limit("SELECT * FROM job_applications LIMIT 10, 20", default_limit=50, max_limit=100)


def test_extract_table_names_reads_from_and_join() -> None:
    assert extract_table_names(
        "SELECT * FROM job_applications j JOIN application_events e ON e.application_id = j.id"
    ) == ["job_applications", "application_events"]
