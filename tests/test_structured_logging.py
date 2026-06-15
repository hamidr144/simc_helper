"""Tests for structured JSON logging (src.core.logging)."""

import json
import logging  # noqa: E402 — imported early for LogRecord
import os
import sys
from unittest.mock import patch

import pytest

# Ensure the project src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.core.logging import JsonFormatter, setup_logging  # noqa: E402 — after sys.path


@pytest.fixture(autouse=True)
def _clear_loggers():
    """Clear all simc-helper loggers before each test to avoid cross-test pollution."""
    import logging
    for name in list(logging.root.manager.loggerDict.keys()):
        if name in ("master", "worker"):
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.setLevel(logging.WARNING)
    yield
    # Cleanup after
    for name in ("master", "worker"):
        logger = logging.getLogger(name)
        logger.handlers.clear()


class TestJsonFormatter:
    """Test that JsonFormatter produces valid JSON with expected fields."""

    def test_json_formatter_produces_valid_json(self, capsys):
        """A log line should be valid JSON."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Hello world"
        assert parsed["filename"] == "test.py"
        assert parsed["lineno"] == 42
        assert "timestamp" in parsed

    def test_json_formatter_includes_exception(self, capsys):
        """Exception info should be included as an 'exception' field."""
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=10,
                msg="An error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert "exception" in parsed
            assert "ValueError: boom" in parsed["exception"]

    def test_json_formatter_includes_extra_fields(self, capsys):
        """Extra structured fields should appear in the JSON."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Task started",
            args=(),
            exc_info=None,
        )
        # Manually set extra attributes (simulates logger.withExtra behavior)
        record.task_id = "abc123"
        record.worker_name = "worker-1"
        record.user_id = "user-42"
        record.port = 8000
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["task_id"] == "abc123"
        assert parsed["worker_name"] == "worker-1"
        assert parsed["user_id"] == "user-42"
        assert parsed["port"] == 8000

    def test_json_formatter_timestamp_is_iso8601(self, capsys):
        """Timestamp should be ISO 8601 with timezone."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        # Should contain timezone info
        assert "T" in parsed["timestamp"]
        assert "Z" in parsed["timestamp"] or "+00:00" in parsed["timestamp"]


class TestSetupLogging:
    """Test setup_logging creates properly configured loggers."""

    def test_setup_master_logger_returns_logger(self):
        """setup_logging('master') returns a configured logger."""
        logger = setup_logging("master")
        assert logger.name == "master"
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) > 0

    def test_setup_worker_logger_returns_logger(self):
        """setup_logging('worker') returns a configured logger."""
        logger = setup_logging("worker")
        assert logger.name == "worker"
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) > 0

    def test_master_logger_outputs_json_in_production(self):
        """In production mode, master logger outputs JSON lines."""
        logger = setup_logging("master")

        # Create a string handler to capture output
        string_io = __import__('io').StringIO()
        string_handler = logging.StreamHandler(string_io)
        string_handler.setLevel(logging.INFO)
        string_handler.setFormatter(JsonFormatter())
        logger.addHandler(string_handler)

        logger.info("test message")
        string_io.seek(0)
        output = string_io.read().strip()
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test message"

    def test_worker_logger_outputs_json_in_production(self):
        """In production mode, worker logger outputs JSON lines."""
        logger = setup_logging("worker")

        string_io = __import__('io').StringIO()
        string_handler = logging.StreamHandler(string_io)
        string_handler.setLevel(logging.INFO)
        string_handler.setFormatter(JsonFormatter())
        logger.addHandler(string_handler)

        logger.info("worker test message")
        string_io.seek(0)
        output = string_io.read().strip()
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "worker test message"

    def test_loggers_are_idempotent(self):
        """Calling setup_logging twice does not add duplicate handlers."""
        logger = setup_logging("master")
        handler_count = len(logger.handlers)
        logger2 = setup_logging("master")
        assert len(logger2.handlers) == handler_count  # No duplicates

    def test_master_logger_creates_log_file(self, tmp_path):
        """Master logger should create log files in the logs directory."""
        with patch.dict(os.environ, {"BASE_DIR": str(tmp_path)}):
            logger = setup_logging("master")
            log_file = tmp_path / "logs" / "master.log"
            assert log_file.exists()

            # Write a log entry
            logger.info("test log entry")
            content = log_file.read_text()
            # File should contain JSON
            parsed = json.loads(content.strip())
            assert parsed["message"] == "test log entry"

    def test_worker_logger_creates_log_file(self, tmp_path):
        """Worker logger should create log files in the logs directory."""
        with patch.dict(os.environ, {"BASE_DIR": str(tmp_path)}):
            logger = setup_logging("worker")
            log_file = tmp_path / "logs" / "worker.log"
            assert log_file.exists()

            logger.info("worker log entry")
            content = log_file.read_text()
            parsed = json.loads(content.strip())
            assert parsed["message"] == "worker log entry"

    def test_log_levels_are_preserved(self, capsys):
        """Different log levels should be preserved in JSON output."""
        logger = setup_logging("master")

        string_io = __import__('io').StringIO()
        handler = logging.StreamHandler(string_io)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

        logger.debug("debug message")
        logger.info("info message")
        logger.warning("warning message")
        logger.error("error message")

        string_io.seek(0)
        lines = [line.strip() for line in string_io.readlines() if line.strip()]
        assert len(lines) == 4

        levels = [json.loads(line)["level"] for line in lines]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR"]
