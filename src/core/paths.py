import os
import re
from pathlib import Path

from fastapi import HTTPException


def safe_child_path(parent_dir: str, child_name: str) -> str:
    if os.path.basename(child_name) != child_name or child_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid file name")
    parent_real = os.path.realpath(parent_dir)
    child_real = os.path.realpath(os.path.join(parent_real, child_name))
    if os.path.commonpath([parent_real, child_real]) != parent_real:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return child_real


def validate_safe_id(value: str, label: str = "id") -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value or ""):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return value


def safe_task_dir(reports_dir: str, task_id: str) -> str:
    validate_safe_id(task_id, "task id")
    reports_real = os.path.realpath(reports_dir)
    task_real = os.path.realpath(os.path.join(reports_real, task_id))
    if os.path.commonpath([reports_real, task_real]) != reports_real:
        raise HTTPException(status_code=400, detail="Invalid task path")
    return task_real


def ensure_dir(path: str) -> str:
    Path(path).mkdir(parents=True, exist_ok=True)
    return path
