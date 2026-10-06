"""Structured JSON logging with run_id context propagation (ADR-027).

Usage:
    from app.core.log_config import configure_logging, run_id_var

    configure_logging(level="INFO")          # call once at startup
    run_id_var.set("run_abc123")             # at the start of each pipeline run
    logger = logging.getLogger(__name__)
    logger.info("LLM call completed")        # emits JSON with run_id
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

run_id_var: ContextVar[str | None] = ContextVar("pipeline_run_id", default=None)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        run_id = run_id_var.get(None)
        if run_id is not None:
            payload["run_id"] = run_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
            }:
                try:
                    json.dumps(val)
                    payload[key] = val
                except (TypeError, ValueError):
                    payload[key] = str(val)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
