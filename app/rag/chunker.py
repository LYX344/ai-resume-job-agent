from typing import Any

from app.models.document import Document, DocumentChunk


DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


def chunk_document(
    document: Document,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be greater than or equal to 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[DocumentChunk] = []
    start_char = 0
    content_length = len(document.content)

    while start_char < content_length:
        end_char = min(start_char + chunk_size, content_length)
        chunk_index = len(chunks)
        chunk_content = document.content[start_char:end_char]

        chunks.append(
            DocumentChunk(
                chunk_id=f"{document.document_id}:{chunk_index}",
                document_id=document.document_id,
                content=chunk_content,
                source=document.metadata.source,
                chunk_index=chunk_index,
                start_char=start_char,
                end_char=end_char,
                metadata=_build_chunk_metadata(document, chunk_index, start_char, end_char),
            )
        )

        if end_char == content_length:
            break
        start_char = end_char - chunk_overlap

    return chunks


def _build_chunk_metadata(
    document: Document,
    chunk_index: int,
    start_char: int,
    end_char: int,
) -> dict[str, Any]:
    return {
        "source": document.metadata.source,
        "file_name": document.metadata.file_name,
        "file_type": document.metadata.file_type,
        "chunk_index": chunk_index,
        "start_char": start_char,
        "end_char": end_char,
    }
