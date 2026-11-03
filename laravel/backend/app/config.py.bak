"""
Configuration loader — Multi-IP, Backup URLs, Selenium Worker, Health Check.
No NOC tunnel.
"""
import json
import pathlib
import os
from typing import Any, Dict

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent


def _load_json_anywhere(filename: str) -> Dict[str, Any]:
    possible_paths = [
        pathlib.Path("/app") / filename,
        SCRIPT_DIR / filename,
        pathlib.Path.cwd() / filename,
        pathlib.Path.home() / "minitron_config" / filename,
        pathlib.Path("C:/minitron") / filename,
    ]
    for path in possible_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.startswith("\ufeff"):
                        content = content[1:]
                    return json.loads(content)
            except Exception as e:
                raise RuntimeError(f"Error parsing {filename} at {path}: {e}") from e
    raise FileNotFoundError(f"{filename} not found. Searched: {[str(p) for p in possible_paths]}")


CONFIG = _load_json_anywhere("config.json")
MAC_PREFIXES = _load_json_anywhere("mac_prefixes.json")

# ---- Core ----
OLT_IPS = CONFIG.get("olt_ips", {})
TELNET_USERNAME = CONFIG["credentials"]["telnet"]["username"]
TELNET_PASSWORD = CONFIG["credentials"]["telnet"]["password"]
PORT_ANALYSIS_FILE = CONFIG["file_paths"]["port_analysis_db"]
DEBUG_ENABLED = CONFIG["debug"]["enabled"]

# ---- Diameter (Primary + backups) ----
DIAMETER_BASE_URL = CONFIG["diameter_config"]["base_url"]
DIAMETER_DOMAIN = CONFIG["diameter_config"]["domain"]
DIAMETER_PATH = CONFIG["diameter_config"]["path"]
DIAMETER_BACKUP_URLS = CONFIG["diameter_config"].get("backup_urls", "")
DIAMETER_URL_LIST = [DIAMETER_BASE_URL] + [u.strip() for u in DIAMETER_BACKUP_URLS.split(",") if u.strip()]

# ---- CSVs ----
PROCTOR_CSV_PATH = CONFIG.get("file_paths", {}).get("proctor_csv", r"C:\Users\HP\Downloads\banga.csv")
KYLIAN_CSV_PATH = os.path.join(SCRIPT_DIR, "kylian.csv")

# ---- Selenium ----
SELENIUM_OLT_IPS = CONFIG.get("selenium_olt_ips", {})
SELENIUM_USERNAME = CONFIG.get("credentials", {}).get("selenium_olt", {}).get("username", "admin")
SELENIUM_PASSWORD = CONFIG.get("credentials", {}).get("selenium_olt", {}).get("password", "admin123")

OLT_DICT: Dict[str, Dict] = {}
for ip, name in SELENIUM_OLT_IPS.items():
    if isinstance(name, dict):
        OLT_DICT[ip] = {
            "name": name.get("name", str(ip)),
            "username": name.get("username", SELENIUM_USERNAME),
            "password": name.get("password", SELENIUM_PASSWORD),
        }
    else:
        OLT_DICT[ip] = {
            "name": str(name),
            "username": SELENIUM_USERNAME,
            "password": SELENIUM_PASSWORD,
        }

DATABASE_FILE = CONFIG.get("file_paths", {}).get("selenium_db", str(SCRIPT_DIR / "olt_ont_database.db"))
OUTPUT_FILE = CONFIG.get("file_paths", {}).get("selenium_output", str(SCRIPT_DIR / "olt_full_data.json"))
MAX_CONCURRENT_CHROME = CONFIG.get("selenium_settings", {}).get("max_concurrent_chrome", 1)
POOR_SIGNAL_THRESHOLD = CONFIG.get("selenium_settings", {}).get("poor_signal_threshold", -28)
PORT_HIGH_LOSS_THRESHOLD = CONFIG.get("selenium_settings", {}).get("port_high_loss_threshold", -29)

# ---- Selenium Remote Worker ----
SELENIUM_WORKER_URL = "http://127.0.0.1:8085"

# ---- CDATA ----
CDATA_OLT_DEVICES = CONFIG.get("cdata_olts", {})
CDATA_SAVE_FILE = CONFIG.get("cdata_save_file", "onu_status.json")
CDATA_MAC_ADDRESS_FILE = CONFIG.get("cdata_mac_file", r"C:\Users\HP\Downloads\mac_address_list.txt")
CDATA_USERNAME = CONFIG.get("cdata_credentials", {}).get("username", "admin")
CDATA_PASSWORD = CONFIG.get("cdata_credentials", {}).get("password", "admin123")

# ---- Health Check ----
HEALTH_CHECK = CONFIG.get("health_check", {"tunnel_test": "127.0.0.1:2323", "ping_test": "192.168.44.1"})

# ---- MAC prefixes ----
UBNT_MAC_PREFIXES = MAC_PREFIXES.get("ubnt", [])
CAMBIUM_MAC_PREFIXES = MAC_PREFIXES.get("cambium", [])
UBNT_PREFIXES_NORMALIZED = [p.replace(":", "").upper() for p in UBNT_MAC_PREFIXES]
CAMBIUM_PREFIXES_NORMALIZED = [p.replace(":", "").upper() for p in CAMBIUM_MAC_PREFIXES]

PHPSESSID_FILE = os.environ.get("PHPSESSID_FILE", "/tmp/phpsessid.txt")
