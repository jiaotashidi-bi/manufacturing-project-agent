from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

from .database import DatabaseStore


class JobQueue:
    """In-process background queue for local use; production can replace it behind this API."""

    def __init__(self, database: DatabaseStore, workers: int = 2) -> None:
        self.database = database
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mpa-job")

    def submit(
        self,
        job_type: str,
        payload: dict[str, Any],
        function: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        job_id = uuid4().hex
        self.database.create_job(job_id, job_type, payload)

        def run() -> None:
            self.database.update_job(job_id, "running")
            try:
                result = function(*args, **kwargs)
                self.database.update_job(job_id, "completed", result=result)
            except Exception as exc:  # job boundary must capture and persist failures
                self.database.update_job(job_id, "failed", error=str(exc))

        self.executor.submit(run)
        return job_id
