"""Structured JSON logging for simc-helper.

Provides JSON-formatted loggers with proper log levels, timestamps,
service name, and optional structured fields (e.g. task_id, worker_name).

Usage:
    from src.core.logging import setup_logging

    logger = setup_logging("master")  # or "worker"
    logger.info("Server started", extra={"port": 8000})

In dev mode (SIMC_HELPER_DEV_MODE=1), logs are emitted as plain text
for readability in local development.
"""

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as JSON for structured log consumption."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include structured extra fields
        for key in ("task_id", "worker_name", "worker_id", "user_id", "port", "service", "status"):
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        # Include exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = self.formatException(record.exc_info)

        # Include caller info for debugging
        log_data["filename"] = record.filename
        log_data["lineno"] = record.lineno

        return json.dumps(log_data, default=str)


def _setup_master_logger(name: str = "master") -> logging.Logger:
    """Set up the master (web server) logger with JSON formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger  # Already configured

    log_dir = os.path.join(os.environ.get("BASE_DIR", "."), "logs")
    os.makedirs(log_dir, exist_ok=True)

    dev_mode = os.environ.get("SIMC_HELPER_DEV_MODE") == "1"

    # File handler — always JSON
    file_handler = logging.FileHandler(os.path.join(log_dir, "master.log"))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    # Console handler
    if dev_mode:
        # Plain text for local dev readability
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(console_handler)
    else:
        # JSON for production (container/Docker log ingestion)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(JsonFormatter())
        logger.addHandler(console_handler)

    return logger


def _setup_worker_logger(name: str = "worker") -> logging.Logger:
    """Set up the worker logger with JSON formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger  # Already configured

    log_dir = os.path.join(os.environ.get("BASE_DIR", "."), "logs")
    os.makedirs(log_dir, exist_ok=True)

    dev_mode = os.environ.get("SIMC_HELPER_DEV_MODE") == "1"

    # File handler — always JSON
    file_handler = logging.FileHandler(os.path.join(log_dir, "worker.log"))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    # Console handler
    if dev_mode:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(console_handler)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(JsonFormatter())
        logger.addHandler(console_handler)

    return logger


def setup_logging(service: str) -> logging.Logger:
    """Set up structured logging for a service.

    Args:
        service: Either "master" (web server) or "worker" (worker daemon).

    Returns:
        Configured logger instance.
    """
    if service == "worker":
        return _setup_worker_logger()
    return _setup_master_logger()
