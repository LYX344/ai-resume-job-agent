"""Verify knowledge-base isolation by collection (resume vs project_docs).

Rebuilds the Redis vector index with the new schema (collection TAG), indexes
the resume into the ``resume`` collection and project docs into
``project_docs``, then compares resume-question retrieval with vs without the
collection filter. Isolation should lift the resume hit_rate that was dragged
down by cross-collection contamination.

Uses real embeddings from settings. Run with Redis up:
    .venv\\Scripts\\python.exe scripts\\smoke_resume_isolation.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.dependencies import get_embedding_client
from app.evaluation.retrieval import find_keyword_hits, load_questions
from app.rag.chunker import chunk_document
from app.rag.document_loader import load_document
from app.rag.indexer import index_document_chunks
from app.rag.retriever import retrieve_document_chunks
from app.services.redis_client import RedisStore


async def _index_file(path: Path, *, collection: str, embedding_client, redis_store) -> int:
    document = load_document(path)
    chunks = chunk_document(document)
    await index_document_chunks(
        chunks,
        embedding_client=embedding_client,
        redis_store=redis_store,
        collection=collection,
    )
    return len(chunks)


async def _hit_rate(*, collection, embedding_client, redis_store) -> tuple[int, int]:
    questions = load_questions(PROJECT_ROOT / "data" / "eval" / "resume_questions.json")
    hits = 0
    for question in questions:
        results = await retrieve_document_chunks(
            question.question,
            top_k=3,
            embedding_client=embedding_client,
            redis_store=redis_store,
            collection=collection,
        )
        result_dicts = [{"content": r.content, "metadata": r.metadata} for r in results]
        if find_keyword_hits(question.expected_keywords, result_dicts):
            hits += 1
    return hits, len(questions)


async def main() -> int:
    redis_store = RedisStore.from_settings()
    embedding_client = get_embedding_client()

    if not await redis_store.ping():
        print("redis_not_reachable")
        return 1

    await redis_store.drop_vector_index()
    deleted = await redis_store.delete_document_chunks()
    await redis_store.ensure_vector_index()
    print(f"reset_done deleted_chunks={deleted}")

    resume_chunks = await _index_file(
        PROJECT_ROOT / "data" / "uploads" / "resume_sample.pdf",
        collection="resume",
        embedding_client=embedding_client,
        redis_store=redis_store,
    )
    print(f"indexed resume chunks={resume_chunks} collection=resume")

    project_files = [PROJECT_ROOT / "README.md", *sorted((PROJECT_ROOT / "docs").glob("*.md"))]
    project_chunks = 0
    for path in project_files:
        project_chunks += await _index_file(
            path,
            collection="project_docs",
            embedding_client=embedding_client,
            redis_store=redis_store,
        )
    print(f"indexed project_docs files={len(project_files)} chunks={project_chunks} collection=project_docs")

    isolated_hits, total = await _hit_rate(
        collection="resume", embedding_client=embedding_client, redis_store=redis_store
    )
    mixed_hits, _ = await _hit_rate(
        collection=None, embedding_client=embedding_client, redis_store=redis_store
    )

    print("----- RESUME RETRIEVAL HIT RATE -----")
    print(f"isolated(collection=resume): {isolated_hits}/{total} = {isolated_hits / total:.4f}")
    print(f"mixed(no filter):            {mixed_hits}/{total} = {mixed_hits / total:.4f}")

    await redis_store.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
