"""
Global in-process state — replaces st.session_state.
"""
import threading
from typing import Dict

# ---- CDATA monitoring ----
cdata_monitoring_results: Dict = {}
cdata_monitor_status = {"running": False, "progress": "", "last_run": None}
cdata_status_lock = threading.Lock()

# ---- CDATA MAC map ----
cdata_mac_name_map_global: Dict[str, str] = {}
cdata_mac_lock = threading.Lock()

# ---- Selenium update status ----
global_update_status = {
    "running": False, "progress": {}, "total_onts": 0,
    "start_time": None, "end_time": None,
    "last_successful_update": None, "update_count": 0,
}

# ---- DEBUG_DATA (mirrors Streamlit global) ----
DEBUG_DATA = {
    "smartolt_name": None,
    "port_stats": {"total_onu": 0, "online": 0, "los": 0,
                   "dyinggasp": 0, "offline": 0, "percentages": {}},
    "status_flags": {"HL": 0, "MPI": 0, "MST": 0, "JCU": 0, "JWD": 0},
    "downtime_info": {"reason": None, "time_ago": None, "last_down": None},
    "mst_clients": [], "jcu_clients": [], "jwd_clients": [],
    "selenium_update_status": {
        "running": False, "progress": {}, "total_onts": 0,
        "start_time": None, "end_time": None,
        "last_successful_update": None, "update_count": 0,
    },
}

# ---- Locks / semaphores ----
db_lock = threading.Lock()
update_chrome_semaphore = threading.Semaphore(1)
search_chrome_semaphore = threading.Semaphore(1)
update_in_progress = False

# ---- Diameter session (runtime-updatable) ----
DIAMETER_SESSION_ID = ""
