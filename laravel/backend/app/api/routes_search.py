from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from backend.app.services.job_service import create_job, get_job, run_job
from backend.app.services.search_service import execute_search
from backend.app.core.diameter import get_phpsessid_from_env

router = APIRouter(prefix="/api", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    session_id: str = ""


def _do_search(query: str, session_id: str):
    return execute_search(query, session_id=session_id)


@router.post("/search")
def post_search(req: SearchRequest, background: BackgroundTasks):
    if not req.query.strip():
        raise HTTPException(400, "query is required")
    sid = req.session_id or get_phpsessid_from_env()
    job = create_job("search", {"query": req.query})
    background.add_task(run_job, job["id"], _do_search, req.query, sid)
    return {"job_id": job["id"], "status": "pending"}


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    j = get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j
