import os, threading
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.app import state
from backend.app.config import OLT_DICT, CDATA_OLT_DEVICES, PHPSESSID_FILE
from backend.app.core.selenium.database import get_selenium_database_stats
from backend.app.core.cdata import run_cdata_monitoring_background
from backend.app.core.utils import get_memory_usage, check_connection_health
from backend.app.services.job_service import create_job, run_job

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/stats")
def get_stats():
    mem_pct, mem_used, mem_total = get_memory_usage()
    health = check_connection_health()
    return {
        "selenium": get_selenium_database_stats(),
        "cdata_olt_count": len(CDATA_OLT_DEVICES),
        "selenium_olt_count": len(OLT_DICT),
        "memory": {"percentage": round(mem_pct, 1), "used_mb": mem_used, "total_mb": mem_total},
        "health": health,
        "selenium_update": {
            "running": state.global_update_status.get("running", False),
            "progress": state.global_update_status.get("progress", {}),
            "last_successful_update": str(state.global_update_status.get("last_successful_update") or ""),
            "update_count": state.global_update_status.get("update_count", 0),
        },
        "cdata_monitor": {
            "running": state.cdata_monitor_status["running"],
            "progress": state.cdata_monitor_status["progress"],
            "last_run": str(state.cdata_monitor_status["last_run"] or ""),
        },
    }


@router.post("/selenium/update")
def trigger_selenium_update():
    """Delegate the update to the remote Selenium worker."""
    import requests
    from backend.app.config import SELENIUM_WORKER_URL
    try:
        r = requests.post(f"{SELENIUM_WORKER_URL}/update", timeout=10)
        if r.status_code == 200:
            return {"status": "started", "worker_response": r.json()}
        return {"status": "error", "detail": r.text}
    except Exception as e:
        raise HTTPException(502, f"Worker unreachable: {e}")


class CdataMonitorReq(BaseModel):
    olt_id: str
    ports: Optional[List[int]] = None


@router.post("/cdata/monitor")
def trigger_cdata(req: CdataMonitorReq):
    if req.olt_id not in CDATA_OLT_DEVICES:
        raise HTTPException(400, "unknown CDATA OLT")
    with state.cdata_status_lock:
        if state.cdata_monitor_status["running"]:
            raise HTTPException(409, "CDATA monitoring already running")
    ports = req.ports or list(range(1, 9))
    threading.Thread(target=run_cdata_monitoring_background, args=(req.olt_id, ports), daemon=True).start()
    return {"status": "started", "olt_id": req.olt_id, "ports": ports}


class SessionReq(BaseModel):
    phpsessid: str


@router.post("/diameter/session")
def set_diameter_session(req: SessionReq):
    if not req.phpsessid.strip():
        raise HTTPException(400, "phpsessid required")
    sid = req.phpsessid.strip()
    os.environ["PHPSESSID"] = sid
    state.DIAMETER_SESSION_ID = sid
    try:
        with open(PHPSESSID_FILE, "w") as f:
            f.write(sid)
    except Exception:
        pass
    return {"status": "updated", "session_id_prefix": sid[:20] + "..."}
