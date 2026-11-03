"""
Selenium search via Remote Worker ONLY.
Falls through to CDATA if worker is down or returns no result.
"""
import requests
from backend.app.config import SELENIUM_WORKER_URL
from backend.app.core.logger import debug_print


def check_selenium_worker() -> bool:
    try:
        resp = requests.get(f"{SELENIUM_WORKER_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def search_selenium_olt(search_term: str):
    debug_print(f"Searching Selenium Worker for: {search_term}", "SELENIUM")
    
    if not check_selenium_worker():
        debug_print("Worker unreachable. Skipping Selenium.", "WARNING")
        return None
        
    try:
        resp = requests.post(
            f"{SELENIUM_WORKER_URL}",
            json={"action": "scan", "search_term": search_term},
            timeout=180
        )
        if resp.status_code == 200:
            result = resp.json()
            if result and result.get("report"):
                debug_print("Worker returned valid report", "SUCCESS")
                return result
        return None
    except Exception as e:
        debug_print(f"Worker search failed: {e}", "ERROR")
        return None
