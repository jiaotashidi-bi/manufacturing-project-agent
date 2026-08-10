from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, Request, Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "request_id": request_id_var.get(),
            },
            ensure_ascii=False,
        )


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests: Counter[tuple[str, str, int]] = Counter()
        self.total_duration: defaultdict[tuple[str, str], float] = defaultdict(float)

    def observe(self, method: str, path: str, status: int, duration: float) -> None:
        with self._lock:
            self.requests[(method, path, status)] += 1
            self.total_duration[(method, path)] += duration

    def render(self) -> str:
        lines = [
            "# HELP mpa_http_requests_total Total HTTP requests.",
            "# TYPE mpa_http_requests_total counter",
        ]
        with self._lock:
            for (method, path, status), request_count in sorted(self.requests.items()):
                lines.append(
                    f'mpa_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {request_count}'
                )
            lines.extend(
                [
                    "# HELP mpa_http_request_duration_seconds_total Cumulative request duration.",
                    "# TYPE mpa_http_request_duration_seconds_total counter",
                ]
            )
            for (method, path), duration_total in sorted(self.total_duration.items()):
                lines.append(
                    f'mpa_http_request_duration_seconds_total{{method="{method}",path="{path}"}} {duration_total:.6f}'
                )
        return "\n".join(lines) + "\n"


metrics = Metrics()


def configure_observability(app: FastAPI, level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger("manufacturing_agent")
    root_logger.handlers = [handler]
    root_logger.setLevel(level)
    logger = logging.getLogger("manufacturing_agent.api")

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid4().hex[:16])
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            metrics.observe(request.method, request.url.path, status, duration)
            logger.info("request_complete method=%s path=%s status=%s duration=%.4f", request.method, request.url.path, status, duration)
            request_id_var.reset(token)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")
