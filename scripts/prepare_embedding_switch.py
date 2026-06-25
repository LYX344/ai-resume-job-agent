from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.services.redis_client import RedisStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare Redis vector data before switching embedding provider or dimension.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually drop the vector index and delete document chunk keys. Default is dry-run.",
    )
    parser.add_argument(
        "--yes-i-understand-data-loss",
        action="store_true",
        help="Required with --execute because document chunk hashes will be deleted.",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    if args.execute and not args.yes_i_understand_data_loss:
        print(
            "Refusing to execute: pass --yes-i-understand-data-loss with --execute.",
            file=sys.stderr,
        )
        return 2

    config = settings.redis_vector_index
    store = RedisStore.from_settings()
    try:
        if not await store.ping():
            print(f"Redis is not reachable: {settings.redis_url}", file=sys.stderr)
            return 1

        index_exists = await store.vector_index_exists(config)
        chunk_keys = await store.list_document_chunk_keys(config)

        print("Embedding switch preparation")
        print(f"dry_run={not args.execute}")
        print(f"redis_url={settings.redis_url}")
        print(f"embedding_provider={settings.embedding_provider}")
        print(f"embedding_model={settings.embedding_model}")
        print(f"vector_index_name={config.index_name}")
        print(f"vector_key_prefix={config.key_prefix}")
        print(f"vector_dimension={config.dimension}")
        print(f"vector_distance_metric={config.distance_metric}")
        print(f"index_exists={index_exists}")
        print(f"document_chunk_key_count={len(chunk_keys)}")

        if not args.execute:
            print("")
            print("No Redis data was changed.")
            print("To reset fake/old embedding data before re-uploading documents, run:")
            print(
                "  python scripts/prepare_embedding_switch.py "
                "--execute --yes-i-understand-data-loss"
            )
            print("")
            print("After reset:")
            print("  1. Set EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_API_KEY.")
            print("  2. Set REDIS_VECTOR_DIMENSION to the model output dimension.")
            print("  3. Restart the API so settings are reloaded.")
            print("  4. Re-upload documents and run scripts/evaluate_retrieval.py.")
            return 0

        dropped_index = await store.drop_vector_index(config)
        deleted_chunks = await store.delete_document_chunks(config)

        print("")
        print("Redis vector data reset complete.")
        print(f"dropped_index={dropped_index}")
        print(f"deleted_document_chunk_keys={deleted_chunks}")
        return 0
    finally:
        await store.aclose()


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
