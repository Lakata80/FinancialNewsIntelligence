"""Tests for structured JSON logging (ADR-027)."""
from __future__ import annotations

import json
import logging
import io

from app.core.log_config import _JsonFormatter, configure_logging, run_id_var


def _capture_log(level: str = "INFO") -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger(f"test.{id(buf)}")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level))
    logger.propagate = False
    return logger, buf


class TestJsonFormatter:
    def test_output_is_valid_json(self):
        logger, buf = _capture_log()
        logger.info("hello world")
        record = json.loads(buf.getvalue().strip())
        assert record["msg"] == "hello world"
        assert record["level"] == "INFO"
        assert "ts" in record
        assert "logger" in record

    def test_run_id_included_when_set(self):
        token = run_id_var.set("run_test_001")
        try:
            logger, buf = _capture_log()
            logger.info("inside run")
            record = json.loads(buf.getvalue().strip())
            assert record["run_id"] == "run_test_001"
        finally:
            run_id_var.reset(token)

    def test_run_id_absent_when_not_set(self):
        # Ensure no run_id is set
        token = run_id_var.set(None)
        try:
            logger, buf = _capture_log()
            logger.info("outside run")
            record = json.loads(buf.getvalue().strip())
            assert "run_id" not in record
        finally:
            run_id_var.reset(token)

    def test_exception_info_included(self):
        logger, buf = _capture_log()
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("error occurred")
        record = json.loads(buf.getvalue().strip())
        assert "exc" in record
        assert "ValueError" in record["exc"]

    def test_ts_format(self):
        logger, buf = _capture_log()
        logger.info("ts test")
        record = json.loads(buf.getvalue().strip())
        ts = record["ts"]
        assert ts.endswith("Z")
        assert "T" in ts
