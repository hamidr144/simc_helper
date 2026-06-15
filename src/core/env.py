import os
import secrets


def clean_pyinstaller_env():
    env = os.environ.copy()
    for var in ["LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"]:
        orig = var + "_ORIG"
        if orig in env:
            env[var] = env[orig]
        elif var in env:
            del env[var]
    return env


def load_cluster_secret(role: str, logger=None) -> str:
    configured = os.environ.get("CLUSTER_SECRET")
    if configured:
        return configured
    if os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        return "simc_helper_local_dev_secret"
    generated = secrets.token_urlsafe(32)
    if logger:
        logger.warning(
            "CLUSTER_SECRET is not set for %s; generated an ephemeral secret. "
            "Set CLUSTER_SECRET for distributed deployments, or SIMC_HELPER_DEV_MODE=1 for local development.",
            role,
        )
    return generated


def require_admin_token(provided: str = None) -> None:
    """Raise a FastAPI HTTPException if ADMIN_TOKEN is configured and missing/wrong."""
    required = os.environ.get("ADMIN_TOKEN")
    if not required:
        return
    if provided == required:
        return
    from fastapi import HTTPException

    raise HTTPException(status_code=403, detail="Admin token required")


def get_bind_host() -> str:
    return os.environ.get("HOST", "127.0.0.1")
