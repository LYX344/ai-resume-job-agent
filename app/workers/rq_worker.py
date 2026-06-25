from redis import Redis
from rq import Queue, SimpleWorker

from app.core.config import settings


def main() -> None:
    connection = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
    )
    queue = Queue(settings.document_index_queue_name, connection=connection)
    worker = SimpleWorker([queue], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
