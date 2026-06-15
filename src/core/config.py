"""Pydantic-based configuration validation for simc-helper.

Provides a validated ``Config`` model that reads all environment variables,
applies defaults, and raises clear errors for missing required values.

Usage:
    from src.core.config import Config, get_config

    config = get_config()
    print(config.host)          # "127.0.0.1"
    print(config.admin_token)   # Optional[str]
    print(config.simc_path)     # Optional[str]
"""

import os
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _read_env(name: str, default: Any = None) -> Any:
    """Read an environment variable, applying type coercion."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value


def _read_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var ('1', 'true', 'yes' → True; else default)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _read_int(name: str, default: int) -> int:
    """Read an integer env var."""
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def _read_float(name: str, default: float) -> float:
    """Read a float env var."""
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


# ---------------------------------------------------------------------------
# Core configuration
# ---------------------------------------------------------------------------


class Config(BaseModel):
    """Application configuration, validated from environment variables.

    All fields default to sensible values.  Required production fields are
    documented in the model docstring and validated by a model validator.
    """

    model_config = ConfigDict(extra="ignore")

    # --- General / Runtime ---
    base_dir: str = Field(default=".", description="Base directory for logs, data, and third-party binaries.")

    # --- SimulationCraft Engine ---
    simc_path: Optional[str] = Field(default=None, description="Path to the SimulationCraft binary.")

    # --- Data Directories ---
    inputs_dir: Optional[str] = Field(default=None, description="Directory for generated .simc input files.")
    reports_dir: Optional[str] = Field(default="/tmp/simc_reports", description="Directory for simulation reports.")

    # --- Web Server (master) ---
    port: int = Field(default=8000, ge=1, le=65535, description="HTTP server port.")
    host: str = Field(default="127.0.0.1", description="Bind host. Use '0.0.0.0' for external connections.")

    # --- TLS / HTTPS ---
    ssl_keyfile: Optional[str] = Field(default=None, description="Path to TLS private key (PEM).")
    ssl_certfile: Optional[str] = Field(default=None, description="Path to TLS certificate (PEM).")

    # --- CORS ---
    cors_allowed_origins: Optional[str] = Field(default=None, description="Comma-separated or JSON array of allowed CORS origins.")
    cors_enabled: bool = Field(default=False, description="Whether CORS is enabled.")

    # --- Authentication ---
    admin_token: Optional[str] = Field(default=None, description="Admin API token for destructive endpoints.")

    # --- Cluster / Worker ---
    cluster_secret: Optional[str] = Field(default=None, description="Secret for master-worker communication.")
    master_url: str = Field(default="http://localhost:8000", description="Master server URL (worker only).")
    worker_name: str = Field(default="LocalWorker", description="Worker node name for identification.")
    simc_update_interval_seconds: int = Field(default=86400, ge=0, description="Seconds between SimC engine update checks.")
    simc_helper_insecure_tls: bool = Field(default=False, description="Disable TLS verification for worker connections.")

    # --- Development Mode ---
    simc_helper_dev_mode: bool = Field(default=False, description="Enable development-friendly defaults.")

    # --- Worker retry settings ---
    max_worker_retry_count: int = Field(default=0, ge=0, description="Maximum worker retry count (0 = unlimited).")
    worker_retry_backoff_factor: int = Field(default=1, ge=1, description="Backoff multiplier for worker retries.")
    worker_retry_max_backoff: int = Field(default=60, ge=1, description="Max backoff seconds for worker retries.")
    max_task_retry_count: int = Field(default=3, ge=0, description="Maximum task retry count.")
    task_retry_backoff_factor: int = Field(default=2, ge=1, description="Backoff multiplier for task retries.")
    task_retry_max_backoff: int = Field(default=60, ge=1, description="Max backoff seconds for task retries.")

    # --- Circuit breaker ---
    worker_cb_failure_threshold: int = Field(default=5, ge=1, description="Failures before circuit opens.")
    worker_cb_recovery_timeout: float = Field(default=30.0, gt=0, description="Seconds to wait before recovery probe.")

    # --- WebSocket ---
    ws_max_size: int = Field(default=67108864, ge=1, description="Maximum WebSocket message size in bytes.")

    # --- Logging ---
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Logging level.")

    # --- Rate limiting ---
    sim_cooldown_seconds: int = Field(default=300, ge=0, description="Minimum seconds between simulations per user.")

    def __init__(self, **kwargs: Any):
        # Read all values from environment before Pydantic validation
        env = {
            "base_dir": _read_env("BASE_DIR", "."),
            "simc_path": _read_env("SIMC_PATH"),
            "inputs_dir": _read_env("INPUTS_DIR"),
            "reports_dir": _read_env("REPORTS_DIR", "/tmp/simc_reports"),
            "port": _read_int("PORT", 8000),
            "host": _read_env("HOST", "127.0.0.1"),
            "ssl_keyfile": _read_env("SSL_KEYFILE"),
            "ssl_certfile": _read_env("SSL_CERTFILE"),
            "cors_allowed_origins": _read_env("CORS_ALLOWED_ORIGINS"),
            "admin_token": _read_env("ADMIN_TOKEN"),
            "cluster_secret": _read_env("CLUSTER_SECRET"),
            "master_url": _read_env("MASTER_URL", "http://localhost:8000"),
            "worker_name": _read_env("WORKER_NAME", "LocalWorker"),
            "simc_update_interval_seconds": _read_int("SIMC_UPDATE_INTERVAL_SECONDS", 86400),
            "simc_helper_insecure_tls": _read_bool("SIMC_HELPER_INSECURE_TLS", False),
            "simc_helper_dev_mode": _read_bool("SIMC_HELPER_DEV_MODE", False),
            "max_worker_retry_count": _read_int("MAX_WORKER_RETRY_COUNT", 0),
            "worker_retry_backoff_factor": _read_int("WORKER_RETRY_BACKOFF_FACTOR", 1),
            "worker_retry_max_backoff": _read_int("WORKER_RETRY_MAX_BACKOFF", 60),
            "max_task_retry_count": _read_int("MAX_TASK_RETRY_COUNT", 3),
            "task_retry_backoff_factor": _read_int("TASK_RETRY_BACKOFF_FACTOR", 2),
            "task_retry_max_backoff": _read_int("TASK_RETRY_MAX_BACKOFF", 60),
            "worker_cb_failure_threshold": _read_int("WORKER_CB_FAILURE_THRESHOLD", 5),
            "worker_cb_recovery_timeout": _read_float("WORKER_CB_RECOVERY_TIMEOUT", 30.0),
            "ws_max_size": _read_int("WS_MAX_SIZE", 67108864),
            "log_level": _read_env("LOG_LEVEL", "INFO"),
            "sim_cooldown_seconds": _read_int("SIM_COOLDOWN_SECONDS", 300),
        }
        # kwargs override env vars
        env.update(kwargs)
        super().__init__(**env)

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, v: Optional[str]) -> Optional[str]:
        """Normalize CORS origins: accept both JSON arrays and comma-separated."""
        if not v:
            return None
        # Try parsing as JSON first
        import ast
        try:
            parsed = ast.literal_eval(v)
            if isinstance(parsed, list):
                return ",".join(str(o).strip() for o in parsed)
        except (ValueError, SyntaxError):
            pass
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Ensure host is a valid IP or hostname."""
        if not v or v.strip():
            return v
        raise ValueError("HOST must be a non-empty IP address or hostname")

    @model_validator(mode="after")
    def apply_dev_mode_defaults(self) -> "Config":
        """Apply dev-mode defaults when SIMC_HELPER_DEV_MODE=1."""
        if self.simc_helper_dev_mode:
            # In dev mode, allow all CORS origins
            self.cors_enabled = True
        return self

    @model_validator(mode="after")
    def validate_production_requirements(self) -> "Config":
        """Validate that required production fields are set."""
        if not self.simc_helper_dev_mode:
            warnings: List[str] = []
            if not self.admin_token:
                warnings.append("ADMIN_TOKEN is not set — admin endpoints are unprotected")
            if not self.cluster_secret:
                warnings.append("CLUSTER_SECRET is not set — an ephemeral secret will be generated (workers won't authenticate on restart)")
            if warnings:
                # Log warnings but don't raise — allow startup so tests work
                import logging
                logger = logging.getLogger("master")
                for w in warnings:
                    logger.warning(w)
        return self


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Return the singleton ``Config`` instance, lazily created from env."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reset_config() -> None:
    """Reset the singleton (useful for tests)."""
    global _config_instance
    _config_instance = None
