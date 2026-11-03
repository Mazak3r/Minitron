import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from backend.app.config import DATABASE_FILE, PORT_HIGH_LOSS_THRESHOLD
from backend.app.state import db_lock
from backend.app.core.logger import debug_print
from backend.app.core.utils import extract_olt_name

def init_selenium_database():
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS ont_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ont_name TEXT, serial_number TEXT, mac_address TEXT,
                olt_ip TEXT, olt_name TEXT, port_id INTEGER, onu_id INTEGER, status TEXT,
                last_seen TEXT, last_downtime TEXT, receive_power TEXT, rstate INTEGER, last_updated TEXT,
                UNIQUE(olt_ip, port_id, onu_id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS port_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT, olt_ip TEXT, olt_name TEXT, port_id INTEGER,
                average_power_dbm REAL, total_onts INTEGER, online_onts INTEGER, high_loss_flag BOOLEAN,
                last_checked TEXT, UNIQUE(olt_ip, port_id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS update_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, start_time TEXT, end_time TEXT,
                total_onts INTEGER, duration_seconds REAL, status TEXT)''')
        conn.commit()
        conn.close()
        debug_print(f"Selenium DB initialized: {DATABASE_FILE}", "DATABASE")

def get_selenium_database_stats() -> Dict:
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM ont_devices'); total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM ont_devices WHERE status = "Online"'); online = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM ont_devices WHERE status = "Offline"'); offline = cursor.fetchone()[0]
        cursor.execute('SELECT datetime(last_updated, "localtime") FROM ont_devices ORDER BY last_updated DESC LIMIT 1')
        lu = cursor.fetchone(); lu = lu[0] if lu else "Never"
        conn.close()
        return {"total": total, "online": online, "offline": offline, "last_update": lu}

def get_ont_location_from_selenium_db(search_term: str) -> Optional[Dict]:
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        pattern = f"%{search_term}%"
        cursor.execute('''SELECT olt_ip, olt_name, port_id, ont_name, serial_number, mac_address
            FROM ont_devices WHERE ont_name LIKE ? OR serial_number LIKE ? OR mac_address LIKE ? LIMIT 1''', (pattern, pattern, pattern))
        result = cursor.fetchone()
        conn.close()
        if result:
            d = dict(result)
            d["olt_name"] = extract_olt_name(d["olt_name"])
            return d
        return None
