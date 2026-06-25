from app.models.trace import TraceRecord, TraceStep
from app.services.trace_store import TraceStore


def _record(trace_id: str, duration: float = 10.0) -> TraceRecord:
    return TraceRecord(
        trace_id=trace_id,
        kind="agent",
        query="q",
        intent="general_chat",
        started_at="2026-06-18T00:00:00+00:00",
        duration_ms=duration,
        step_count=1,
        steps=[TraceStep(name="understand_intent", status="completed")],
    )


def test_trace_store_append_and_list_recent(tmp_path) -> None:
    store = TraceStore(str(tmp_path / "traces.jsonl"))
    store.append(_record("t1"))
    store.append(_record("t2"))

    recent = store.list_recent(10)

    assert [record.trace_id for record in recent] == ["t2", "t1"]


def test_trace_store_get_returns_record(tmp_path) -> None:
    store = TraceStore(str(tmp_path / "traces.jsonl"))
    store.append(_record("t1"))

    assert store.get("t1").trace_id == "t1"
    assert store.get("missing") is None


def test_trace_store_list_recent_respects_limit(tmp_path) -> None:
    store = TraceStore(str(tmp_path / "traces.jsonl"))
    for index in range(5):
        store.append(_record(f"t{index}"))

    recent = store.list_recent(2)

    assert [record.trace_id for record in recent] == ["t4", "t3"]


def test_trace_store_empty_when_file_missing(tmp_path) -> None:
    store = TraceStore(str(tmp_path / "missing.jsonl"))

    assert store.list_recent() == []
    assert store.get("x") is None
