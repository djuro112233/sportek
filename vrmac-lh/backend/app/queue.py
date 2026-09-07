"""Background jobs: Redis/RQ in the demo stack, synchronous in tests (QUEUE_MODE=sync)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from .config import settings

log = logging.getLogger(__name__)
QUEUE_NAME = "vrmac"


def enqueue(func: Callable, *args, job_timeout: int = 900, **kwargs):
    """Run ``func`` now (sync mode) or on the RQ worker. ``func`` must be a module-level function."""
    if settings.queue_mode == "sync":
        return func(*args, **kwargs)
    from redis import Redis
    from rq import Queue

    q = Queue(QUEUE_NAME, connection=Redis.from_url(settings.redis_url))
    job = q.enqueue(func, *args, job_timeout=job_timeout, **kwargs)
    log.info("enqueued %s as job %s", getattr(func, "__name__", func), job.id)
    return job
