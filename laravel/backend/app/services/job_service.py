"""
Thread-safe in-memory job tracker.
"""
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from backend.app.core.logger import debug_print

_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_MAX_COMPLETED = 200


def _evict_old():
    completed = [(jid, j) for jid, j in _JOBS.items() if j["status"] in ("done", "error")]
    if len(completed) <= _MAX_COMPLETED:
        return
    completed.sort(key=lambda x: x[1].get("finished_at") or "")
    for jid, _ in completed[: len(completed) - _MAX_COMPLETED]:
        _JOBS.pop(jid, None)


def create_job(kind: str, params: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id, "kind": kind, "params": params,
        "status": "pending", "progress": "queued", "result": None, "error": None,
        "created_at": datetime.now().isoformat(),
        "started_at": None, "finished_at": None,
    }
    with _LOCK:
        _JOBS[job_id] = job
        _evict_old()
    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **fields):
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def run_job(job_id: str, func, *args, **kwargs):
    _update_job(job_id, status="running", progress="running", started_at=datetime.now().isoformat())
    debug_print(f"[JOB {job_id[:8]}] starting {func.__name__}", "INFO")
    try:
        result = func(*args, **kwargs)
        _update_job(job_id, status="done", progress="completed", result=result, finished_at=datetime.now().isoformat())
        debug_print(f"[JOB {job_id[:8]}] done", "SUCCESS")
    except Exception as e:
        import traceback
        debug_print(f"[JOB {job_id[:8]}] ERROR: {e}", "ERROR")
        debug_print(traceback.format_exc(), "ERROR")
        _update_job(job_id, status="error", progress=f"error: {e}", error=str(e), finished_at=datetime.now().isoformat())
