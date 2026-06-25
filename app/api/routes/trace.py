from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_trace_store
from app.models.trace import TraceRecord
from app.services.trace_store import TraceStore

router = APIRouter(tags=["trace"])


@router.get("/traces", response_model=list[TraceRecord])
def list_traces(
    limit: int = Query(default=20, ge=1, le=100),
    trace_store: TraceStore = Depends(get_trace_store),
) -> list[TraceRecord]:
    return trace_store.list_recent(limit)


@router.get("/traces/{trace_id}", response_model=TraceRecord)
def get_trace(
    trace_id: str,
    trace_store: TraceStore = Depends(get_trace_store),
) -> TraceRecord:
    record = trace_store.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return record
