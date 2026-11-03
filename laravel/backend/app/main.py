import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import state
from backend.app.config import OLT_DICT, CDATA_OLT_DEVICES
from backend.app.core.logger import debug_print
from backend.app.core.selenium.database import init_selenium_database, get_selenium_database_stats
from backend.app.core.cdata import init_cdata_mac_map
from backend.app.core.diameter import get_phpsessid_from_env

from backend.app.api.routes_search import router as search_router
from backend.app.api.routes_admin import router as admin_router
from backend.app.api.routes_health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    debug_print("MINITRON (new_mini) starting up...", "INFO")
    init_selenium_database()
    try:
        init_cdata_mac_map()
    except Exception as e:
        debug_print(f"CDATA MAC init skipped: {e}", "WARNING")

    sid = get_phpsessid_from_env()
    if sid:
        state.DIAMETER_SESSION_ID = sid
        debug_print(f"Diameter PHPSESSID loaded ({len(sid)} chars)", "SUCCESS")
    else:
        debug_print("No PHPSESSID found — Diameter lookups will be skipped", "WARNING")

    stats = get_selenium_database_stats()
    debug_print(f"Selenium DB: {stats['total']} ONTs", "SUCCESS")
    debug_print(f"Selenium OLTs configured: {len(OLT_DICT)}", "INFO")
    debug_print(f"CDATA OLTs configured: {len(CDATA_OLT_DEVICES)}", "INFO")
    debug_print("MINITRON backend ready ✅", "SUCCESS")
    yield
    debug_print("MINITRON backend shutting down", "INFO")


app = FastAPI(title="MINITRON new_mini", version="0.008", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.include_router(health_router)
app.include_router(search_router)
app.include_router(admin_router)


@app.get("/")
def root():
    return {"name": "MINITRON new_mini", "version": "0.008", "docs": "/docs", "health": "/api/health"}
