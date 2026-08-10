#!/usr/bin/env python3
import streamlit as st
import asyncio
import nest_asyncio
import socket
import telnetlib3
import re
import time
import threading
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from collections import defaultdict
import sys
import math
import json
import ast
import os
import requests
from bs4 import BeautifulSoup
import platform
import subprocess
import tempfile
import pathlib
import urllib3
import sqlite3
import queue
import shutil
from typing import Dict, List, Optional, Tuple
import pandas as pd

# Authentication state management
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'sidebar_locked' not in st.session_state:
    st.session_state.sidebar_locked = True

def check_sidebar_auth():
    """Check if sidebar should be accessible"""
    return st.session_state.authenticated

def authenticate_sidebar(password_input):
    """Authenticate to unlock sidebar"""
    # Change this to your desired password
    AUTH_PASSWORD = os.environ.get("MINITRON_SIDEBAR_PASS", "admin")
    
    if password_input == AUTH_PASSWORD:
        st.session_state.authenticated = True
        st.session_state.sidebar_locked = False
        return True
    return False

def lock_sidebar():
    """Lock the sidebar"""
    st.session_state.authenticated = False
    st.session_state.sidebar_locked = True

st.set_page_config(
    page_title="MINITRON v0.007", 
    page_icon="🤖", 
    layout="centered",
    initial_sidebar_state="collapsed"  # This keeps sidebar closed by default
)

nest_asyncio.apply()

SCRIPT_DIR = pathlib.Path(__file__).parent.absolute()

DEBUG_ENABLED = True

def debug_print(message, level="INFO"):
    if not DEBUG_ENABLED:
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    level_colors = {
        "INFO": "\033[94m", "SUCCESS": "\033[92m", "WARNING": "\033[93m",
        "ERROR": "\033[91m", "DEBUG": "\033[95m", "PORT": "\033[96m", "CLIENT": "\033[97m",
        "SELENIUM": "\033[93m", "DATABASE": "\033[95m", "CDATA": "\033[36m", "CSV": "\033[92m"
    }
    reset = "\033[0m"
    color = level_colors.get(level, "\033[97m")
    print(f"{color}[{timestamp}] {level}: {message}{reset}")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

def extract_olt_name(olt_name):
    if olt_name is None:
        return "Unknown OLT"
    if isinstance(olt_name, dict):
        return olt_name.get("name", str(olt_name))
    if isinstance(olt_name, str):
        if olt_name.strip().startswith('{') and olt_name.strip().endswith('}'):
            try:
                parsed = ast.literal_eval(olt_name)
                if isinstance(parsed, dict) and 'name' in parsed:
                    return str(parsed['name'])
                else:
                    return str(parsed)
            except (ValueError, SyntaxError, Exception):
                match = re.search(r"'name':\s*'([^']+)'", olt_name)
                if match:
                    return match.group(1)
                return olt_name
        else:
            return olt_name
    return str(olt_name)

def load_config():
    possible_paths = [
        SCRIPT_DIR / 'config.json',
        pathlib.Path.cwd() / 'config.json',
        pathlib.Path.home() / 'minitron_config' / 'config.json',
        pathlib.Path('C:/minitron/config.json')
    ]
    config_path = None
    for path in possible_paths:
        if path.exists():
            config_path = path
            break
    if not config_path:
        st.error(f"Configuration file not found. Searched in: {[str(p) for p in possible_paths]}")
        st.stop()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if content.startswith('\ufeff'):
                content = content[1:]
            return json.loads(content)
    except json.JSONDecodeError as e:
        st.error(f"Error parsing config.json at {config_path}: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Error loading config: {e}")
        st.stop()

def load_mac_prefixes():
    possible_paths = [
        SCRIPT_DIR / 'mac_prefixes.json',
        pathlib.Path.cwd() / 'mac_prefixes.json',
        pathlib.Path.home() / 'minitron_config' / 'mac_prefixes.json',
        pathlib.Path('C:/minitron/mac_prefixes.json')
    ]
    mac_path = None
    for path in possible_paths:
        if path.exists():
            mac_path = path
            break
    if not mac_path:
        st.error(f"MAC prefixes file not found. Searched in: {[str(p) for p in possible_paths]}")
        st.stop()
    try:
        with open(mac_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if content.startswith('\ufeff'):
                content = content[1:]
            return json.loads(content)
    except json.JSONDecodeError as e:
        st.error(f"Error parsing mac_prefixes.json at {mac_path}: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Error loading MAC prefixes: {e}")
        st.stop()

CONFIG = load_config()
MAC_PREFIXES = load_mac_prefixes()

OLT_IPS = CONFIG.get("olt_ips", {})
TELNET_USERNAME = CONFIG["credentials"]["telnet"]["username"]
TELNET_PASSWORD = CONFIG["credentials"]["telnet"]["password"]
PORT_ANALYSIS_FILE = CONFIG["file_paths"]["port_analysis_db"]
DIAMETER_BASE_URL = CONFIG["diameter_config"]["base_url"]
DIAMETER_DOMAIN = CONFIG["diameter_config"]["domain"]
DIAMETER_PATH = CONFIG["diameter_config"]["path"]
DEBUG_ENABLED = CONFIG["debug"]["enabled"]

PROCTOR_CSV_PATH = CONFIG.get("file_paths", {}).get("proctor_csv", r"C:\Users\HP\Downloads\banga.csv")

SELENIUM_OLT_IPS = CONFIG.get("selenium_olt_ips", {})
SELENIUM_USERNAME = CONFIG.get("credentials", {}).get("selenium_olt", {}).get("username", "admin")
SELENIUM_PASSWORD = CONFIG.get("credentials", {}).get("selenium_olt", {}).get("password", "admin123")

OLT_DICT = {}
for ip, name in SELENIUM_OLT_IPS.items():
    if isinstance(name, dict):
        OLT_DICT[ip] = {
            "name": name.get("name", str(ip)),
            "username": name.get("username", SELENIUM_USERNAME),
            "password": name.get("password", SELENIUM_PASSWORD)
        }
    else:
        OLT_DICT[ip] = {
            "name": str(name),
            "username": SELENIUM_USERNAME,
            "password": SELENIUM_PASSWORD
        }

DATABASE_FILE = CONFIG.get("file_paths", {}).get("selenium_db", str(SCRIPT_DIR / "olt_ont_database.db"))
OUTPUT_FILE = CONFIG.get("file_paths", {}).get("selenium_output", str(SCRIPT_DIR / "olt_full_data.json"))

MAX_CONCURRENT_CHROME = CONFIG.get("selenium_settings", {}).get("max_concurrent_chrome", 1)
POOR_SIGNAL_THRESHOLD = CONFIG.get("selenium_settings", {}).get("poor_signal_threshold", -28)
PORT_HIGH_LOSS_THRESHOLD = CONFIG.get("selenium_settings", {}).get("port_high_loss_threshold", -29)

USE_VISIBLE_MODE = False

UBNT_MAC_PREFIXES = MAC_PREFIXES.get("ubnt", [])
CAMBIUM_MAC_PREFIXES = MAC_PREFIXES.get("cambium", [])
UBNT_PREFIXES_NORMALIZED = [prefix.replace(":", "").upper() for prefix in UBNT_MAC_PREFIXES]
CAMBIUM_PREFIXES_NORMALIZED = [prefix.replace(":", "").upper() for prefix in CAMBIUM_MAC_PREFIXES]

CDATA_OLT_DEVICES = CONFIG.get("cdata_olts", {})
CDATA_SAVE_FILE = CONFIG.get("cdata_save_file", "onu_status.json")
CDATA_MAC_ADDRESS_FILE = CONFIG.get("cdata_mac_file", r"C:\Users\HP\Downloads\mac_address_list.txt")
CDATA_USERNAME = CONFIG.get("cdata_credentials", {}).get("username", "admin")
CDATA_PASSWORD = CONFIG.get("cdata_credentials", {}).get("password", "admin123")

debug_print(f"Config loaded successfully", "SUCCESS")
debug_print(f"Proctor CSV path: {PROCTOR_CSV_PATH}", "CSV")

def search_proctor_csv(search_term: str) -> List[Dict]:
    if not os.path.exists(PROCTOR_CSV_PATH):
        debug_print(f"Proctor CSV file not found: {PROCTOR_CSV_PATH}", "ERROR")
        return []
    try:
        df = pd.read_csv(PROCTOR_CSV_PATH)
        original_term = search_term.strip()
        search_variations = [original_term.lower()]
        if ' ' in original_term:
            search_variations.append(original_term.replace(' ', '_').lower())
        if '_' in original_term:
            search_variations.append(original_term.replace('_', ' ').lower())
        search_variations = list(dict.fromkeys(search_variations))
        debug_print(f"CSV searching for variations: {search_variations}", "CSV")
        debug_print(f"Total records in CSV: {len(df)}", "CSV")
        
        matches = []
        
        for idx, row in df.iterrows():
            sn = str(row.get('SN', '')).strip().lower() if pd.notna(row.get('SN')) else ''
            name = str(row.get('Name', '')).strip().lower() if pd.notna(row.get('Name')) else ''
            for search_var in search_variations:
                if search_var == sn or search_var == name or (search_var in name and len(search_var) > 3):
                    debug_print(f"✅ Match found in CSV at row {idx+1}", "SUCCESS")
                    debug_print(f"   Name: {row.get('Name')}", "CSV")
                    debug_print(f"   SN: {row.get('SN')}", "CSV")
                    debug_print(f"   OLT: {row.get('OLT')}", "CSV")
                    debug_print(f"   Board: {row.get('Board')}", "CSV")
                    debug_print(f"   Port: {row.get('Port')}", "CSV")
                    debug_print(f"   ONU ID: {row.get('Allocated ONU')}", "CSV")
                    pon_type = str(row.get('PON Type', 'gpon')).strip().lower()
                    olt_full = f"{row.get('OLT')} {pon_type}-onu_1/{row.get('Board')}/{row.get('Port')}:{row.get('Allocated ONU')}"
                    debug_print(f"   olt_full: '{olt_full}'", "CSV")
                    
                    matches.append({
                        "smartolt_name": str(row.get('Name')).strip(),
                        "serial_number": str(row.get('SN')).strip(),
                        "olt_full": olt_full,
                        "row_index": idx + 1
                    })
                    break
        
        if not matches:
            debug_print(f"❌ No match found for '{original_term}'", "WARNING")
            return []
        
        debug_print(f"📊 Total matches found: {len(matches)}", "SUCCESS")
        return matches
        
    except Exception as e:
        debug_print(f"Error reading CSV: {e}", "ERROR")
        return []

DEBUG_DATA = {
    "last_check": None,
    "smartolt_name": None,
    "port_stats": {
        "total_onu": 0,
        "online": 0,
        "los": 0,
        "dyinggasp": 0,
        "offline": 0,
        "percentages": {}
    },
    "status_flags": {
        "HL": 0,
        "MPI": 0,
        "MST": 0,
        "JCU": 0,
        "JWD": 0
    },
    "downtime_info": {
        "reason": None,
        "time_ago": None,
        "last_down": None
    },
    "mst_clients": [],
    "jcu_clients": [],
    "jwd_clients": [],
    "selenium_update_status": {
        "running": False,
        "progress": {},
        "total_onts": 0,
        "start_time": None,
        "end_time": None,
        "last_successful_update": None,
        "update_count": 0
    }
}

if 'cdata_monitoring_results' not in st.session_state:
    st.session_state.cdata_monitoring_results = {}

if 'selected_serial' not in st.session_state:
    st.session_state.selected_serial = None

cdata_mac_name_map_global = {}
cdata_mac_lock = threading.Lock()

cdata_monitor_status = {
    "running": False,
    "progress": "",
    "last_run": None
}
cdata_status_lock = threading.Lock()

def check_reachability(ip, port=23, timeout=3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except:
        return False

def ping_ip(ip, timeout=3, extended_timeout=False):
    if ip == 'N/A' or not ip:
        return False
    ip = ip.strip()
    try:
        socket.inet_aton(ip)
    except socket.error:
        return False
    ping_timeout = 10 if extended_timeout else timeout
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as temp_file:
            temp_path = temp_file.name
        if platform.system().lower() == 'windows':
            count = 4 if extended_timeout else 2
            command = ['ping', '-n', str(count), '-w', str(ping_timeout * 1000), ip]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=ping_timeout + 2)
        else:
            count = 4 if extended_timeout else 2
            command = ['ping', '-c', str(count), '-W', str(ping_timeout), ip]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=ping_timeout + 2)
        with open(temp_path, 'w') as f:
            f.write(result.stdout)
        output = result.stdout.lower()
        success_indicators = [f"reply from {ip}", f"{ip} : bytes=", f"64 bytes from {ip}", f"from {ip}: icmp_seq="]
        failure_indicators = ["ttl expired in transit", "destination host unreachable", "request timed out", "100% packet loss", "unreachable"]
        for indicator in failure_indicators:
            if indicator in output:
                os.unlink(temp_path)
                return False
        for indicator in success_indicators:
            if indicator in output:
                os.unlink(temp_path)
                return True
        if result.returncode == 0 and not any(indicator in output for indicator in failure_indicators):
            os.unlink(temp_path)
            return True
        os.unlink(temp_path)
        return False
    except (subprocess.TimeoutExpired, Exception):
        return False

def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            loop = asyncio.get_event_loop()
            if loop.is_running():
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    return loop.run_until_complete(coro)
                except ImportError:
                    raise RuntimeError("Install nest_asyncio: pip install nest-asyncio")
            else:
                return loop.run_until_complete(coro)
        else:
            raise

def cdata_load_mac_address_list(file_path: str) -> Dict[str, str]:
    mac_name_map = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            match = re.search(r'^\s*\d+\.\s+([a-zA-Z_]+)\s*-?\s*([0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2})', line, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                mac = match.group(2).strip().lower().replace(":", "").replace("-", "")
                mac_name_map[mac] = name
        debug_print(f"CDATA MAC list loaded: {len(mac_name_map)} entries", "CDATA")
        return mac_name_map
    except Exception as e:
        debug_print(f"Error loading CDATA MAC list: {e}", "CDATA")
        return {}

def cdata_find_matching_name(mac_address: str, mac_name_map: Dict[str, str]) -> str:
    if not mac_address or not mac_name_map:
        return ""
    clean_mac = mac_address.lower().replace(":", "").replace("-", "")
    if clean_mac in mac_name_map:
        return mac_name_map[clean_mac]
    if len(clean_mac) == 12:
        partial_mac = clean_mac[:11]
        for stored_mac, name in mac_name_map.items():
            if stored_mac.startswith(partial_mac) and len(stored_mac) == 12:
                return name
    elif len(clean_mac) == 11:
        for stored_mac, name in mac_name_map.items():
            if stored_mac.startswith(clean_mac) and len(stored_mac) == 12:
                return name
    mac_without_colons = clean_mac.replace(":", "")
    if mac_without_colons in mac_name_map:
        return mac_name_map[mac_without_colons]
    if ":" in mac_address and len(mac_address) == 17:
        mac_without_last = mac_address[:-1].lower().replace(":", "")
        for stored_mac, name in mac_name_map.items():
            if stored_mac.startswith(mac_without_last) and len(stored_mac) == 12:
                return name
    return ""

def cdata_load_previous_results() -> Dict:
    try:
        if os.path.exists(CDATA_SAVE_FILE):
            with open(CDATA_SAVE_FILE, "r") as f:
                data = json.load(f)
                debug_print(f"CDATA saved data loaded: {len(data)} OLTs", "CDATA")
                return data
    except Exception as e:
        debug_print(f"Error loading CDATA saved results: {e}", "CDATA")
    return {}

def cdata_search_in_saved_data(search_query: str) -> Tuple[Optional[str], Optional[str], Optional[Dict]]:
    data = cdata_load_previous_results()
    if not data:
        debug_print("CDATA saved data is empty", "CDATA")
        return None, None, None
    query_raw = search_query.strip()
    query_lower = query_raw.lower()
    query_name_normalized = re.sub(r'[_\s]+', '', query_lower)
    query_mac_clean = re.sub(r'[:\-\s]', '', query_lower)
    debug_print(f"CDATA searching for '{search_query}'", "CDATA")
    for olt_ip, ports in data.items():
        for port, onu_list in ports.items():
            for onu in onu_list:
                onu_name = onu.get("Name", "")
                onu_mac = onu.get("Mac address", onu.get("mac", ""))
                name_norm = re.sub(r'[_\s]+', '', onu_name.lower()) if onu_name else ""
                mac_clean = re.sub(r'[:\-\s]', '', onu_mac.lower()) if onu_mac else ""
                if name_norm and query_name_normalized in name_norm:
                    debug_print(f"CDATA found by Name: '{onu_name}' at {olt_ip}:{port}", "CDATA")
                    return olt_ip, port, onu
                if mac_clean and query_mac_clean:
                    if query_mac_clean in mac_clean:
                        debug_print(f"CDATA found by MAC substring: {mac_clean} at {olt_ip}:{port}", "CDATA")
                        return olt_ip, port, onu
                    if mac_clean.startswith(query_mac_clean) and len(mac_clean) - len(query_mac_clean) <= 2:
                        debug_print(f"CDATA found by MAC prefix: {mac_clean} at {olt_ip}:{port}", "CDATA")
                        return olt_ip, port, onu
                if not name_norm and mac_clean and query_mac_clean in mac_clean:
                    debug_print(f"CDATA found by MAC (no name): {mac_clean} at {olt_ip}:{port}", "CDATA")
                    return olt_ip, port, onu
    debug_print("CDATA search: no match in saved data", "CDATA")
    return None, None, None

def cdata_extract_signal_value(signal_str: str) -> Optional[float]:
    if not signal_str or signal_str == "N/A":
        return None
    match = re.search(r'(-?\d+\.?\d*)', signal_str)
    if match:
        return float(match.group(1))
    return None

def get_cdata_olt_name_by_ip(ip: str) -> str:
    for olt_id, olt_info in CDATA_OLT_DEVICES.items():
        if olt_info.get("ip") == ip:
            return olt_info.get("name", ip)
    return ip

async def cdata_get_full_command_output(reader, writer, command: str, max_pages: int = 10) -> str:
    full_output = ""
    cmd = command + "\r\n"
    debug_print(f"CDATA telnet >>> {command}", "CDATA")
    writer.write(cmd.encode())
    await writer.drain()
    for page in range(max_pages):
        await asyncio.sleep(1)
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=2)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="ignore")
            debug_print(f"CDATA telnet <<< {text}", "CDATA")
            full_output += text
            if "epon#" in text or "#" in text or ">" in text:
                break
        except asyncio.TimeoutError:
            debug_print(f"CDATA telnet timeout on page {page}", "CDATA")
            pass
    return full_output

async def cdata_get_onu_signal(reader, writer, port: int, onu_id: str) -> str:
    try:
        command = f"show olt {port} onu {onu_id} ctc optical"
        output = await cdata_get_full_command_output(reader, writer, command)
        match = re.search(r'rx power\s+(-?\d+\.\d+)\s*d?Bm?', output, re.IGNORECASE)
        if match:
            signal = match.group(1) + " dBm"
            debug_print(f"CDATA ONU {onu_id} signal: {signal}", "CDATA")
            return signal
        debug_print(f"CDATA ONU {onu_id} signal not found in output", "CDATA")
        return "N/A"
    except Exception as e:
        debug_print(f"CDATA error getting signal for ONU {onu_id}: {e}", "CDATA")
        return "N/A"

def cdata_parse_online_onu(output: str, port: int) -> List[Dict]:
    onu_list = []
    lines = output.split('\n')
    debug_print(f"CDATA parsing online-onu output for port {port} ({len(lines)} lines)", "CDATA")
    with cdata_mac_lock:
        mac_map = cdata_mac_name_map_global.copy()
    for line in lines:
        line = line.strip()
        if re.match(r'^\d+\s+\d+\s+[0-9a-f:-]{10,}', line.lower()):
            parts = line.split()
            if len(parts) >= 3:
                onu_id = parts[1]
                mac = parts[2].lower().replace("-", ":")
                name = cdata_find_matching_name(mac, mac_map)
                onu_list.append({"onu_id": onu_id, "mac": mac, "name": name})
                debug_print(f"CDATA found online ONU: ID={onu_id}, MAC={mac}, Name={name}", "CDATA")
    debug_print(f"CDATA parsed {len(onu_list)} online ONUs for port {port}", "CDATA")
    return onu_list

async def cdata_monitor_olt(host: str, username: str, password: str, ports: List[int]) -> Dict[str, List[Dict]]:
    results = {}
    writer = None
    try:
        debug_print(f"CDATA connecting to {host}:23...", "CDATA")
        reader, writer = await asyncio.open_connection(host, 23)
        banner = await reader.readuntil(b"Username:")
        debug_print(f"CDATA login banner: {banner.decode(errors='ignore').strip()}", "CDATA")
        writer.write((username + "\r\n").encode()); await writer.drain()
        await reader.readuntil(b"Password:")
        writer.write((password + "\r\n").encode()); await writer.drain()
        await asyncio.sleep(1)
        initial_output = await reader.read(1024)
        debug_print(f"CDATA post-login: {initial_output.decode(errors='ignore')}", "CDATA")
        for port in ports:
            debug_print(f"CDATA scanning port {port}...", "CDATA")
            command = f"show olt online-onu {port}"
            full_output = await cdata_get_full_command_output(reader, writer, command)
            onu_list = cdata_parse_online_onu(full_output, port)
            table_data = []
            for onu in onu_list:
                onu_id = onu["onu_id"]
                mac = onu["mac"]
                name = onu["name"]
                signal = await cdata_get_onu_signal(reader, writer, port, onu_id)
                table_data.append({
                    "Status": "🟢",
                    "ID": onu_id,
                    "Name": name,
                    "Mac address": mac,
                    "Onu signal": signal
                })
            results[str(port)] = table_data
            debug_print(f"CDATA port {port} done: {len(table_data)} ONUs", "CDATA")
        writer.close()
        await writer.wait_closed()
        return results
    except Exception as e:
        debug_print(f"CDATA error monitoring OLT {host}: {e}", "CDATA")
        import traceback
        traceback.print_exc()
        return {}
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()

def cdata_run_monitoring(olt_id: str, ports: Optional[List[int]] = None) -> Dict[str, List[Dict]]:
    if olt_id not in CDATA_OLT_DEVICES:
        raise ValueError(f"Invalid CDATA OLT ID: {olt_id}")
    olt = CDATA_OLT_DEVICES[olt_id]
    if ports is None:
        ports = list(range(1, 9))
    if not check_reachability(olt["ip"], 23, 3):
        debug_print(f"CDATA OLT {olt['name']} ({olt['ip']}) is unreachable", "CDATA")
        return {}
    debug_print(f"CDATA monitoring {olt['name']} ({olt['ip']}) on ports {ports}", "CDATA")
    current_results = run_async(cdata_monitor_olt(olt["ip"], CDATA_USERNAME, CDATA_PASSWORD, ports))
    if not current_results:
        debug_print("CDATA monitoring returned empty results", "CDATA")
        return {}
    prev_data = cdata_load_previous_results()
    olt_prev = prev_data.get(olt["ip"], {})
    final_results = {}
    for port in ports:
        port_str = str(port)
        curr_list = current_results.get(port_str, [])
        prev_list = olt_prev.get(port_str, [])
        curr_macs = {onu["Mac address"] for onu in curr_list}
        final_list = list(curr_list)
        for prev_onu in prev_list:
            mac = prev_onu.get("Mac address", prev_onu.get("mac", ""))
            if mac not in curr_macs:
                offline = prev_onu.copy()
                offline["Status"] = "🔴"
                if "mac" in offline:
                    offline["Mac address"] = offline.pop("mac")
                if "onu_id" in offline:
                    offline["ID"] = offline.pop("onu_id")
                if "Onu signal" not in offline:
                    offline["Onu signal"] = "N/A"
                final_list.append(offline)
        final_results[port_str] = final_list
    st.session_state.cdata_monitoring_results[olt["ip"]] = final_results

    return final_results

def cdata_search_and_monitor_port(query: str) -> Tuple[Optional[Dict], Optional[List[Dict]], Optional[str], Optional[str], Optional[str]]:
    debug_print(f"CDATA search_and_monitor_port called with query: {query}", "CDATA")
    olt_ip, port_str, saved_onu = cdata_search_in_saved_data(query)
    if not olt_ip:
        debug_print("CDATA: no location found in saved data", "CDATA")
        return None, None, None, None, None
    if not check_reachability(olt_ip, 23, 3):
        olt_name = get_cdata_olt_name_by_ip(olt_ip)
        error_msg = f"❌ {olt_name.upper()} - OLT is currently DOWN"
        debug_print(f"CDATA: {error_msg}", "CDATA")
        return None, None, olt_ip, port_str, error_msg
    port = int(port_str)
    olt_name = get_cdata_olt_name_by_ip(olt_ip)
    debug_print(f"CDATA found location: OLT={olt_name} ({olt_ip}), Port={port}", "CDATA")
    debug_print(f"CDATA initiating live scan on port {port}...", "CDATA")
    current_data = run_async(cdata_monitor_olt(olt_ip, CDATA_USERNAME, CDATA_PASSWORD, [port]))
    curr_list = current_data.get(str(port), [])
    debug_print(f"CDATA live scan returned {len(curr_list)} online ONUs", "CDATA")
    prev_data = cdata_load_previous_results()
    prev_list = prev_data.get(olt_ip, {}).get(str(port), [])
    curr_macs = {onu["Mac address"] for onu in curr_list}
    final_list = list(curr_list)
    for prev_onu in prev_list:
        mac = prev_onu.get("Mac address", prev_onu.get("mac", ""))
        if mac not in curr_macs:
            offline = prev_onu.copy()
            offline["Status"] = "🔴"
            if "mac" in offline:
                offline["Mac address"] = offline.pop("mac")
            if "onu_id" in offline:
                offline["ID"] = offline.pop("onu_id")
            if "Onu signal" not in offline:
                offline["Onu signal"] = "N/A"
            final_list.append(offline)
    debug_print(f"CDATA final port list has {len(final_list)} total ONUs", "CDATA")


    # Load existing data for display, but DO NOT save to file
    existing = cdata_load_previous_results()
    if olt_ip not in existing:
        existing[olt_ip] = {}
    existing[olt_ip][str(port)] = final_list
    # ========== SAVE DISABLED – DumbOLT handles persistence ==========
    # with open(CDATA_SAVE_FILE, "w") as f:
    #     json.dump(existing, f, indent=2)
    st.session_state.cdata_monitoring_results[olt_ip] = existing[olt_ip]

    matched = None
    query_lower = query.lower()
    search_mac = re.sub(r'[:\-\s]', '', query_lower)
    for onu in final_list:
        mac = onu.get("Mac address", "").lower().replace(":", "").replace("-", "")
        name = onu.get("Name", "").lower()
        name_norm = re.sub(r'[_\s]+', '', name)
        if mac.startswith(search_mac) or search_mac in mac or query_lower in name_norm:
            matched = onu
            debug_print(f"CDATA matched ONU in live data: {onu}", "CDATA")
            break
    if not matched:
        debug_print("CDATA: matched ONU not found in live scan; using saved data for report", "CDATA")
        matched = saved_onu
    return matched, final_list, olt_ip, port_str, None

def cdata_generate_diagnostic_report(matched_onu: Dict, port_data: List[Dict], olt_name: str, port: int) -> str:
    onu_status = matched_onu.get("Status", "🔴")
    onu_name = matched_onu.get("Name", "Unknown")
    onu_mac = matched_onu.get("Mac address", matched_onu.get("mac", "N/A"))
    signal_str = matched_onu.get("Onu signal", "N/A")
    signal_val = cdata_extract_signal_value(signal_str)
    total = len(port_data)
    online_onus = [o for o in port_data if o.get("Status") == "🟢"]
    online_count = len(online_onus)
    signals = [cdata_extract_signal_value(o.get("Onu signal", "")) for o in online_onus if o.get("Onu signal", "N/A") != "N/A"]
    avg_signal = sum(signals) / len(signals) if signals else None
    POOR_THRESHOLD = -28.0
    if onu_status == "🟢" and signal_val is not None and signal_val >= POOR_THRESHOLD:
        return f"""

🟢 **ONLINE** | **Signal:** **GOOD** **({signal_str})**

**Diagnostic Report:** > **{onu_name}** EPON device (**{onu_mac}**) is currently **Online**.

**Location Details:**

**OLT**: **{olt_name}**

**Port details**: Port {port}

The unit is running within the optimal operating range.

**Action Item:** > If the client reports a total loss of service despite these readings, please check Network Analysis below to confirm if the Ping is reachable before escalating the issue to the G-NOC group chat.
Thank you."""
    elif onu_status == "🟢" and signal_val is not None and signal_val < POOR_THRESHOLD:
        if avg_signal is not None and avg_signal >= POOR_THRESHOLD:
            return f"""

🔴 **ONLINE** | **Signal:** **Poor** **({signal_str})**

**Diagnostic Report:** > **{onu_name}** is currently utilizing a Epon device **({onu_mac})**.

**Location Details:**

**OLT**: **{olt_name}**

**Port details**: Port {port}

While the status is Online, the current signal strength is recorded at **{signal_val:.2f}** **dBm**. This indicates significant optical power loss affecting the client's ONU.


**Diagnostic Context & Required Action:** > * The average port signal remains **stable**, suggesting an isolated physical layer issue at the client's premises. If the user experiences intermittent connectivity, please generate a support ticket for a technician visit to inspect the fiber terminations.
Thank you."""
        else:
            return f"""

🔴 **ONLINE** | **Signal**: **Poor** **({signal_str})**

**Diagnostic Report:** > **{onu_name}** is currently utilizing a Epon device **({onu_mac})**.

**Location Details:**

**OLT**: **{olt_name}**

**Port details**: Port {port}

While the status is Online, the current signal strength is recorded at **{signal_val:.2f}** dBm. This indicates significant optical power loss affecting the client's ONU.

**Diagnostic Context & Required Action:** > * Diagnostic data indicates the entire port is experiencing **high optical power loss**, impacting most connected ONUs. Please verify if this port is flagged; if not, urgently alert **NOC** to investigate the OLT port.
Thank you."""
    else:
        if online_count == 0:
            return f"""

🔴 **OFFLINE**

**Diagnostic Report:** > **{onu_name}** EPON device **({onu_mac})** is currently **OFFLINE**.

**Location Details:**

**OLT:** **{olt_name}**

**Port details:** Port {port}


**Port diagnosis:** **The Pon Port is currently down**. Kindly confirm the port has been flagged, if not urgently inform **NOC** to check"""
        else:
            return f"""

🔴 **OFFLINE**

**Diagnostic Report:** > **{onu_name}** EPON device **({onu_mac})** is currently **OFFLINE**.

**Location Details:**

**OLT:** **{olt_name}**

**Port details:** Port {port}

**Port diagnosis:** The PON PORT looks stable with **{online_count}** ONU(s) online. If the client is experiencing LOS **Kindly raise a support ticket for the client.**"""
    return "Unable to generate report."

def run_cdata_monitoring_background(olt_id: str, ports: List[int]):
    global cdata_monitor_status
    with cdata_status_lock:
        cdata_monitor_status["running"] = True
        cdata_monitor_status["progress"] = f"Monitoring {olt_id}..."
    try:
        results = cdata_run_monitoring(olt_id, ports)
        if not results:
            with cdata_status_lock:
                cdata_monitor_status["progress"] = "OLT unreachable or no data"
        else:
            with cdata_status_lock:
                cdata_monitor_status["last_run"] = datetime.now()
                cdata_monitor_status["progress"] = "Completed"
        debug_print("CDATA background monitoring completed", "CDATA")
    except Exception as e:
        debug_print(f"CDATA monitoring error: {e}", "CDATA")
        with cdata_status_lock:
            cdata_monitor_status["progress"] = f"Error: {e}"
    finally:
        with cdata_status_lock:
            cdata_monitor_status["running"] = False

db_lock = threading.Lock()
update_chrome_semaphore = threading.Semaphore(MAX_CONCURRENT_CHROME)
search_chrome_semaphore = threading.Semaphore(1)
update_in_progress = False

global_update_status = {
    "running": False,
    "progress": {},
    "total_onts": 0,
    "start_time": None,
    "end_time": None,
    "last_successful_update": None,
    "update_count": 0
}

def init_selenium_database():
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ont_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ont_name TEXT,
                serial_number TEXT,
                mac_address TEXT,
                olt_ip TEXT,
                olt_name TEXT,
                port_id INTEGER,
                onu_id INTEGER,
                status TEXT,
                last_seen TEXT,
                last_downtime TEXT,
                receive_power TEXT,
                rstate INTEGER,
                last_updated TEXT,
                UNIQUE(olt_ip, port_id, onu_id)
            )
        ''')
        cursor.execute("PRAGMA table_info(ont_devices)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'last_updated' not in columns:
            cursor.execute("ALTER TABLE ont_devices ADD COLUMN last_updated TEXT")
        if 'rstate' not in columns:
            cursor.execute("ALTER TABLE ont_devices ADD COLUMN rstate INTEGER")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS port_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                olt_ip TEXT,
                olt_name TEXT,
                port_id INTEGER,
                average_power_dbm REAL,
                total_onts INTEGER,
                online_onts INTEGER,
                high_loss_flag BOOLEAN,
                last_checked TEXT,
                UNIQUE(olt_ip, port_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS update_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT,
                end_time TEXT,
                total_onts INTEGER,
                duration_seconds REAL,
                status TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ont_name ON ont_devices(ont_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_serial ON ont_devices(serial_number)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mac ON ont_devices(mac_address)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_olt_port ON ont_devices(olt_ip, port_id)')
        conn.commit()
        conn.close()
        debug_print(f"Selenium database initialized: {DATABASE_FILE}", "DATABASE")

def get_selenium_database_stats() -> Dict:
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM ont_devices')
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM ont_devices WHERE status = "Online"')
        online = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM ont_devices WHERE status = "Offline"')
        offline = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(DISTINCT olt_name) FROM ont_devices')
        olt_count = cursor.fetchone()[0]
        cursor.execute('SELECT datetime(last_updated, "localtime") FROM ont_devices ORDER BY last_updated DESC LIMIT 1')
        last_update = cursor.fetchone()
        last_update = last_update[0] if last_update else "Never"
        conn.close()
        return {
            "total": total,
            "online": online,
            "offline": offline,
            "olt_count": olt_count,
            "last_update": last_update
        }

def search_selenium_database(search_term: str) -> List[Dict]:
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = '''
            SELECT * FROM ont_devices 
            WHERE ont_name LIKE ? 
               OR serial_number LIKE ? 
               OR mac_address LIKE ?
            ORDER BY last_seen DESC
        '''
        search_pattern = f"%{search_term}%"
        cursor.execute(query, (search_pattern, search_pattern, search_pattern))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

def get_ont_location_from_selenium_db(search_term: str) -> Optional[Dict]:
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = '''
            SELECT olt_ip, olt_name, port_id, ont_name, serial_number, mac_address
            FROM ont_devices 
            WHERE ont_name LIKE ? OR serial_number LIKE ? OR mac_address LIKE ?
            LIMIT 1
        '''
        search_pattern = f"%{search_term}%"
        cursor.execute(query, (search_pattern, search_pattern, search_pattern))
        result = cursor.fetchone()
        if result:
            result_dict = dict(result)
            result_dict['olt_name'] = extract_olt_name(result_dict['olt_name'])
            return result_dict
        return None

def update_ont_in_selenium_database(ont_data: Dict, olt_ip: str, olt_name: str):
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        clean_olt_name = extract_olt_name(olt_name)
        cursor.execute('''
            INSERT OR REPLACE INTO ont_devices 
            (ont_name, serial_number, mac_address, olt_ip, olt_name, port_id, onu_id, 
             status, last_seen, last_downtime, receive_power, rstate, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ont_data.get('ont_name', 'N/A'),
            ont_data.get('ont_sn', 'N/A'),
            ont_data.get('macaddr', 'N/A'),
            olt_ip,
            clean_olt_name,
            ont_data.get('port_id', 0),
            ont_data.get('onu_id', 0),
            "Online" if ont_data.get('rstate') == 1 else "Offline",
            datetime.now().isoformat(),
            ont_data.get('last_d_time', 'N/A'),
            ont_data.get('receive_power', 'N/A'),
            ont_data.get('rstate', 0),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

def update_port_health_selenium(olt_ip: str, olt_name: str, port_id: int, avg_power: Optional[float], total_onts: int, online_onts: int):
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        clean_olt_name = extract_olt_name(olt_name)
        high_loss_flag = False
        if avg_power is not None and avg_power < PORT_HIGH_LOSS_THRESHOLD:
            high_loss_flag = True
        cursor.execute('''
            INSERT OR REPLACE INTO port_health 
            (olt_ip, olt_name, port_id, average_power_dbm, total_onts, online_onts, high_loss_flag, last_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (olt_ip, clean_olt_name, port_id, avg_power, total_onts, online_onts, high_loss_flag, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def log_update_history_selenium(start_time: datetime, end_time: datetime, total_onts: int, status: str):
    with db_lock:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        duration = (end_time - start_time).total_seconds()
        cursor.execute('''
            INSERT INTO update_history (start_time, end_time, total_onts, duration_seconds, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (start_time.isoformat(), end_time.isoformat(), total_onts, duration, status))
        conn.commit()
        conn.close()

def get_phpsessid_from_env():
    return os.environ.get('PHPSESSID', '')

def identify_radio_type(mac_address):
    if not mac_address or mac_address == "N/A":
        return None
    mac_normalized = mac_address.replace(":", "").replace("-", "").upper()
    if len(mac_normalized) >= 6:
        mac_prefix = mac_normalized[:6]
        if mac_prefix in UBNT_PREFIXES_NORMALIZED:
            return "ubnt"
        elif mac_prefix in CAMBIUM_PREFIXES_NORMALIZED:
            return "cambium"
    return None

def format_radio_message(radio_type, nas_bts, session_ip, ping_reachable):
    if radio_type == "ubnt":
        if ping_reachable:
            return f"Client is a UBNT radio client connected to {nas_bts}. The client's IP address is reachable via ping. Kindly click on this IP {session_ip} to access the radio and troubleshoot further."
        else:
            return f"Client is a UBNT radio client whose IP is not reachable. Kindly confirm if any UBNT Access Point (AP) is down from {nas_bts}. If no access point is down from {nas_bts}, please troubleshoot and confirm with the client that both LAN cables connected to the PoE box are properly connected. Once confirmed, wait for 5 minutes. If the device does not come online, please raise a ticket."
    elif radio_type == "cambium":
        if ping_reachable:
            return f"Client is a Cambium radio client connected to {nas_bts}. The client's IP address is reachable via ping. Kindly click on this IP {session_ip} to access the radio and troubleshoot further."
        else:
            return f"Client is a Cambium radio client whose IP address is not reachable. Kindly confirm if any Cambium Access Point (AP) is down from {nas_bts}. If no access point is down from {nas_bts}, please troubleshoot and confirm with the client that both LAN cables connected to the PoE box are properly connected. Once confirmed, wait for 5 minutes. If the device does not come online, please raise a ticket."
    return None

def create_diameter_session(session_id):
    debug_print(f"[DIAMETER] Creating session with PHPSESSID: {session_id[:20]}...", "DEBUG")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Create session with custom adapter for longer timeouts
    session = requests.Session()
    session.verify = False
    session.encoding = 'utf-8'
    
    # Configure retry strategy
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    retry_strategy = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        'Referer': DIAMETER_BASE_URL,
        'Origin': f'https://{DIAMETER_DOMAIN}' if DIAMETER_DOMAIN else DIAMETER_BASE_URL,
        'Host': DIAMETER_DOMAIN if DIAMETER_DOMAIN else '',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Charset': 'utf-8',
        'Accept-Encoding': 'utf-8',
        'Content-Type': 'text/html; charset=utf-8',
        'Connection': 'keep-alive'
    })
    
    # Set cookie
    cookie_domain = DIAMETER_DOMAIN if DIAMETER_DOMAIN else ''
    cookie_path = DIAMETER_PATH if DIAMETER_PATH else '/'
    session.cookies.set('PHPSESSID', session_id, domain=cookie_domain, path=cookie_path)
    
    debug_print(f"[DIAMETER] Cookie set: domain='{cookie_domain}', path='{cookie_path}'", "DEBUG")
    
    return session

def parse_edit_user_page(html_content, username):
    debug_print(f"[DIAMETER] Parsing edit_user page for username: {username}", "DEBUG")
    
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')
    
    # Check for login page
    if "Secure login" in html_content:
        debug_print(f"[DIAMETER] 'Secure login' detected - session expired", "WARNING")
        return {'found': False, 'username': username, 'login_page': True}
    
    if "User not found!" in html_content:
        debug_print(f"[DIAMETER] 'User not found!' detected", "WARNING")
        return {'found': False, 'username': username, 'user_not_found': True}
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    user_data = {
        'found': True, 
        'username': username, 
        'phone': 'N/A', 
        'mobile': 'N/A',
        'first_name': 'N/A', 
        'last_name': 'N/A', 
        'email': 'N/A', 
        'address': 'N/A',
        'city': 'N/A', 
        'state': 'N/A', 
        'country': 'N/A', 
        'company': 'N/A',
        'service_plan': 'N/A', 
        'expiry_date': 'N/A', 
        'cpe_ip': 'N/A', 
        'cm_ip': 'N/A',
        'cm_mac': 'N/A', 
        'nas_bts': 'N/A', 
        'registered_date': 'N/A', 
        'last_logoff': 'N/A',
        'session_ip': 'N/A', 
        'mac_address': 'N/A', 
        'is_online': False, 
        'status': 'OFFLINE'
    }
    
    fields = ['phone', 'mobile', 'firstname', 'lastname', 'email', 'address', 'city', 
              'state', 'country', 'company', 'staticipcpe', 'staticipcm', 'cmmac', 
              'createdon', 'lastlogoff', 'expiration']
    
    for field in fields:
        input_elem = soup.find('input', {'name': field})
        if input_elem and input_elem.get('value'):
            value = input_elem.get('value').strip()
            debug_print(f"[DIAMETER] Found field {field} = {value[:50] if value else 'EMPTY'}", "DEBUG")
            
            if field == 'firstname':
                user_data['first_name'] = value
            elif field == 'lastname':
                user_data['last_name'] = value
            elif field == 'staticipcpe':
                user_data['cpe_ip'] = value
            elif field == 'staticipcm':
                user_data['cm_ip'] = value
            elif field == 'cmmac':
                user_data['cm_mac'] = value
            elif field == 'createdon':
                user_data['registered_date'] = value
            elif field == 'lastlogoff':
                user_data['last_logoff'] = value
            elif field == 'expiration':
                user_data['expiry_date'] = value
            else:
                user_data[field] = value
    
    # Extract MAC address from Caller ID on user page (BEFORE traffic report)
    try:
        for td in soup.find_all('td', class_='normal'):
            div = td.find('div', align='right')
            if div and 'Caller ID:' in div.get_text():
                next_td = td.find_next_sibling('td', class_='normal')
                if next_td:
                    # Try to get MAC from onClick attribute
                    inner_div = next_td.find('div')
                    if inner_div and inner_div.get('onClick'):
                        import re as re_mac
                        mac_match = re_mac.search(r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}", inner_div.get('onClick'))
                        if mac_match:
                            user_data['mac_address'] = mac_match.group(0)
                            debug_print(f"[DIAMETER] MAC from Caller ID: {user_data['mac_address']}", "SUCCESS")
                    # Fallback: get from <a> tag
                    if user_data.get('mac_address', 'N/A') == 'N/A':
                        a_tag = next_td.find('a')
                        if a_tag:
                            mac_text = a_tag.get_text(strip=True)
                            if re.match(r'[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}', mac_text):
                                user_data['mac_address'] = mac_text
                                debug_print(f"[DIAMETER] MAC from Caller ID (a tag): {user_data['mac_address']}", "SUCCESS")
                    break
    except Exception as e:
        debug_print(f"[DIAMETER] Error extracting Caller ID MAC: {e}", "DEBUG")

    # Extract NAS/BTS from user page (BEFORE traffic report)
    try:
        for td in soup.find_all('td', class_='normal'):
            div = td.find('div', align='right')
            if div and 'NAS:' in div.get_text():
                next_td = td.find_next_sibling('td', class_='normal')
                if next_td:
                    nas_link = next_td.find('a')
                    if nas_link:
                        nas_text = nas_link.get_text(strip=True)
                        if nas_text:
                            user_data['nas_bts'] = nas_text
                            debug_print(f"[DIAMETER] NAS from user page: {nas_text}", "SUCCESS")
                    else:
                        nas_text = next_td.get_text(strip=True)
                        if nas_text and nas_text.lower() not in ['n/a', '', '&nbsp;']:
                            user_data['nas_bts'] = nas_text
                            debug_print(f"[DIAMETER] NAS from user page (text): {nas_text}", "SUCCESS")
                    break
    except Exception as e:
        debug_print(f"[DIAMETER] Error extracting NAS: {e}", "DEBUG")

    # Get service plan
    service_select = soup.find('select', {'name': 'srvid'})
    if service_select:
        selected_option = service_select.find('option', selected=True)
        if selected_option:
            user_data['service_plan'] = selected_option.get_text(strip=True)
            debug_print(f"[DIAMETER] Service plan: {user_data['service_plan']}", "DEBUG")
    
    # Check online status from the Connection status table cell bgcolor
    # Look for the row that contains "Connection status:"
    is_online = False
    try:
        # Find all cells with "Connection status:" text
        for td in soup.find_all('td', string=re.compile(r'Connection status:', re.IGNORECASE)):
            # Get the next table cell (sibling) or find the next td
            parent_row = td.find_parent('tr')
            if parent_row:
                # Find all td elements in this row
                cells = parent_row.find_all('td')
                for idx, cell in enumerate(cells):
                    if 'Connection status:' in cell.get_text():
                        # The status is in the next cell (idx + 1)
                        if idx + 1 < len(cells):
                            status_cell = cells[idx + 1]
                            # Look for the table inside the status cell
                            inner_table = status_cell.find('table')
                            if inner_table:
                                bgcolor = inner_table.get('bgcolor', '')
                                debug_print(f"[DIAMETER] Connection status table bgcolor: '{bgcolor}'", "DEBUG")
                                # Online has bgcolor="#95B8FF", Offline has bgcolor=""
                                if bgcolor and bgcolor.lower() in ['#95b8ff', '95b8ff']:
                                    is_online = True
                                    debug_print(f"[DIAMETER] User is ONLINE (bgcolor={bgcolor})", "SUCCESS")
                                else:
                                    debug_print(f"[DIAMETER] User is OFFLINE (bgcolor={bgcolor})", "INFO")
                                break
            break
    except Exception as e:
        debug_print(f"[DIAMETER] Error parsing connection status: {e}", "WARNING")
        # Fallback to old method if parsing fails
        if "Online" in html_content or "ONLINE" in html_content:
            is_online = True
            debug_print(f"[DIAMETER] Fallback: User is ONLINE (keyword found)", "SUCCESS")
        else:
            debug_print(f"[DIAMETER] Fallback: User is OFFLINE", "INFO")
    
    if is_online:
        user_data['is_online'] = True
        user_data['status'] = 'ONLINE'
    else:
        user_data['is_online'] = False
        user_data['status'] = 'OFFLINE'
    
    debug_print(f"[DIAMETER] Parsed user_data summary: name={user_data['first_name']} {user_data['last_name']}, CPE IP={user_data['cpe_ip']}, Status={user_data['status']}", "INFO")
    
    return user_data


def parse_traffic_report(html_content, username, from_date):
    debug_print(f"[DIAMETER] Parsing traffic report for {username} from date {from_date}", "DEBUG")
    
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')
    
    # DEBUG: Dump first 500 chars and row info
    debug_print(f"[DIAMETER] Traffic HTML length: {len(html_content)} chars", "DEBUG")
    debug_print(f"[DIAMETER] Contains 'tb-header': {'tb-header' in html_content}", "DEBUG")
    debug_print(f"[DIAMETER] Contains '#E0E0E0': {'#E0E0E0' in html_content}", "DEBUG")
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    if "Secure login" in html_content or "login" in html_content.lower():
        debug_print(f"[DIAMETER] Login page detected in traffic report", "WARNING")
        return 'N/A', 'N/A', 'N/A', False
    
    if "no records found" in html_content.lower() or "no data" in html_content.lower():
        debug_print(f"[DIAMETER] No records found in traffic report", "DEBUG")
        return 'N/A', 'N/A', 'N/A', False
    
    # Find data rows with class "normal" that have actual data (skip TOTALS row with bgcolor="#EAF1FF")
    all_rows = soup.find_all('tr', class_='normal')
    rows = []
    for r in all_rows:
        bg = r.get('bgcolor', '').upper()
        # Skip TOTALS row (#EAF1FF) and empty rows
        if bg != '#EAF1FF':
            cells = r.find_all('td')
            # Must have enough cells to be a data row (16 columns)
            if len(cells) >= 15:
                rows.append(r)
    
    debug_print(f"[DIAMETER] Found {len(rows)} rows in traffic table", "DEBUG")
    
    session_ip = 'N/A'
    mac_address = 'N/A'
    nas_bts = 'N/A'
    
    for idx, row in enumerate(rows):
        cells = row.find_all('td')
        debug_print(f"[DIAMETER] Row {idx} has {len(cells)} cells", "DEBUG")
        
        # Cell 12 = IP address
        if len(cells) > 12:
            ip_text = cells[12].get_text(strip=True)
            if ip_text and ip_text.lower() not in ['n/a', '', '&nbsp;', '--']:
                session_ip = ip_text
                debug_print(f"[DIAMETER] Found session_ip: {session_ip}", "DEBUG")
        
        # Cell 13 = Caller ID (MAC address)
        if len(cells) > 13:
            mac_text = cells[13].get_text(strip=True)
            if mac_text and mac_text.lower() not in ['n/a', '', '&nbsp;', '--']:
                mac_address = mac_text
                debug_print(f"[DIAMETER] Found mac_address: {mac_address}", "DEBUG")
        
        # Cell 14 = NAS (with <a> link)
        if len(cells) > 14:
            nas_cell = cells[14]
            nas_link = nas_cell.find('a')
            if nas_link:
                nas_bts = nas_link.get_text(strip=True)
                debug_print(f"[DIAMETER] Found nas_bts (link): {nas_bts}", "DEBUG")
            else:
                nas_text = nas_cell.get_text(strip=True)
                if nas_text and nas_text.lower() not in ['n/a', '', '&nbsp;', '--']:
                    nas_bts = nas_text
                    debug_print(f"[DIAMETER] Found nas_bts (text): {nas_bts}", "DEBUG")
        
        # Return on first row with valid data
        if session_ip != 'N/A' or mac_address != 'N/A' or nas_bts != 'N/A':
            debug_print(f"[DIAMETER] Successfully extracted traffic data from row {idx}", "SUCCESS")
            return session_ip, mac_address, nas_bts, True
    
    debug_print(f"[DIAMETER] No valid traffic data found in any row", "WARNING")
    return 'N/A', 'N/A', 'N/A', False

def get_diameter_traffic_data(session, base_url, username, last_logoff=None, expiry_date=None, registered_date=None):
    debug_print(f"[DIAMETER] === START get_diameter_traffic_data for {username} ===", "DEBUG")
    debug_print(f"[DIAMETER] last_logoff: {last_logoff}", "DEBUG")
    debug_print(f"[DIAMETER] expiry_date: {expiry_date}", "DEBUG")
    debug_print(f"[DIAMETER] registered_date: {registered_date}", "DEBUG")
    
    try:
        # Determine the start date for searching
        start_date = None
        
        # Priority 1: Use last_logoff if available
        if last_logoff and last_logoff != "N/A":
            try:
                start_date = datetime.strptime(last_logoff.split()[0], "%Y-%m-%d")
                debug_print(f"[DIAMETER] Using last_logoff as start_date: {start_date}", "DEBUG")
            except:
                debug_print(f"[DIAMETER] Failed to parse last_logoff, will try expiry_date", "WARNING")
                start_date = None
        
        # Priority 2: Use expiry_date if last_logoff not available
        if not start_date and expiry_date and expiry_date != "N/A":
            try:
                start_date = datetime.strptime(expiry_date.split()[0], "%Y-%m-%d")
                debug_print(f"[DIAMETER] Using expiry_date as start_date: {start_date}", "DEBUG")
            except:
                debug_print(f"[DIAMETER] Failed to parse expiry_date, using current date", "WARNING")
                start_date = None
        
        # Priority 3: Use current date if neither is available
        if not start_date:
            start_date = datetime.now()
            debug_print(f"[DIAMETER] No last_logoff or expiry_date, using current date: {start_date}", "DEBUG")
        
        # Check if last_logoff is before 2024 - if so, skip traffic report entirely
        if start_date.year < 2024:
            debug_print(f"[DIAMETER] Last logoff date {start_date} is before 2024, skipping traffic report", "WARNING")
            return {'session_ip': 'N/A', 'mac_address': 'N/A', 'nas_bts': 'N/A', 'traffic_date': None}
        
        # Determine end date (registration date or current date, whichever is earlier)
        end_date = datetime.now()
        if registered_date and registered_date != "N/A":
            try:
                end_date = datetime.strptime(registered_date.split()[0], "%Y-%m-%d")
                debug_print(f"[DIAMETER] Using registered_date as end_date: {end_date}", "DEBUG")
            except:
                pass
        
        # Search day by day from last_logoff backwards to registered_date
        max_days = (start_date - end_date).days
        if max_days < 0:
            max_days = 10  # fallback to 10 days if dates are wrong
        if max_days > 365:
            max_days = 10  # cap at 10 days maximum
        
        debug_print(f"[DIAMETER] Searching day by day: {start_date.date()} → {end_date.date()} ({max_days} days max)", "DEBUG")
        
        day_offset = 0
        while day_offset <= max_days:
            search_date = start_date - timedelta(days=day_offset)
            from_date = search_date.strftime("%Y-%m-%d")
            
            traffic_url = f"{base_url}cont=detailed_traffic_report&username={username}&fromdate={from_date}&framedip=%&stationid=%&nasid=&apid="
            debug_print(f"[DIAMETER] Trying traffic URL: {traffic_url}", "DEBUG")
            
            try:
                response = session.get(traffic_url, timeout=60)
                response.encoding = 'utf-8'
                
                if response.status_code != 200:
                    debug_print(f"[DIAMETER] Non-200 response: {response.status_code}", "WARNING")
                    day_offset += 1
                    continue
                
                debug_print(f"[DIAMETER] Traffic response length: {len(response.text)} chars", "DEBUG")
                
                # DUMP first 1000 chars to see what we're getting
                debug_print(f"[DIAMETER] Response start: {response.text[:1000]}", "DEBUG")
                
                # Check if we got the login page instead of traffic data
                if "Secure login" in response.text or "txt_Username" in response.text:
                    debug_print(f"[DIAMETER] Session expired - got login page instead of traffic data", "WARNING")
                    return {'session_ip': 'N/A', 'mac_address': 'N/A', 'nas_bts': 'N/A', 'traffic_date': None}
                
                debug_print(f"[DIAMETER] Contains 'Detailed traffic report': {'Detailed traffic report' in response.text}", "DEBUG")
                
                session_ip, mac_address, nas_bts, found_data = parse_traffic_report(response.text, username, from_date)
                
                if found_data:
                    debug_print(f"[DIAMETER] Traffic data found! Date: {from_date}, Day offset: {day_offset}", "SUCCESS")
                    debug_print(f"[DIAMETER] Session IP: {session_ip}, NAS BTS: {nas_bts}", "DEBUG")
                    return {
                        'session_ip': session_ip, 
                        'mac_address': mac_address, 
                        'nas_bts': nas_bts, 
                        'traffic_date': from_date
                    }
                else:
                    debug_print(f"[DIAMETER] No valid traffic data for {from_date}", "DEBUG")
                    
            except requests.exceptions.ReadTimeout:
                debug_print(f"[DIAMETER] Timeout for date {from_date}, continuing to next day", "WARNING")
            except Exception as e:
                debug_print(f"[DIAMETER] Error for date {from_date}: {e}", "WARNING")
            
            day_offset += 1
        
        debug_print(f"[DIAMETER] No traffic data found after searching {day_offset} days", "WARNING")
        return {'session_ip': 'N/A', 'mac_address': 'N/A', 'nas_bts': 'N/A', 'traffic_date': None}
        
    except Exception as e:
        debug_print(f"[DIAMETER] Error in get_diameter_traffic_data: {e}", "ERROR")
        import traceback
        debug_print(f"[DIAMETER] Traceback: {traceback.format_exc()}", "ERROR")
        return {'session_ip': 'N/A', 'mac_address': 'N/A', 'nas_bts': 'N/A', 'traffic_date': None}

def get_diameter_user_data(username, base_url, session_id):
    debug_print(f"[DIAMETER] === START get_diameter_user_data ===", "INFO")
    debug_print(f"[DIAMETER] username: {username}", "INFO")
    
    if not session_id or session_id == '':
        debug_print(f"[DIAMETER] No PHPSESSID provided for Diameter", "WARNING")
        return None
    
    diameter_username = username.replace(' ', '_')
    debug_print(f"[DIAMETER] Converted username: '{username}' → '{diameter_username}'", "INFO")
    
    session = create_diameter_session(session_id)
    debug_print(f"[DIAMETER] Session created successfully", "INFO")
    
    try:
        # Test connection with longer timeout (30 seconds)
        debug_print(f"[DIAMETER] Testing connection to {base_url}?cont=list_users", "INFO")
        response = session.get(f"{base_url}?cont=list_users", timeout=60)
        response.encoding = 'utf-8'
        debug_print(f"[DIAMETER] list_users response status: {response.status_code}", "INFO")
        
        if response.status_code != 200:
            debug_print(f"[DIAMETER] list_users returned non-200: {response.status_code}", "ERROR")
            return None
        
        # Get edit user page with longer timeout (30 seconds)
        edit_url = f"{base_url}?cont=edit_user&username={diameter_username}"
        debug_print(f"[DIAMETER] Fetching edit user page: {edit_url}", "INFO")
        response = session.get(edit_url, timeout=60, allow_redirects=True)
        response.encoding = 'utf-8'
        debug_print(f"[DIAMETER] edit_user response status: {response.status_code}", "INFO")
        
        if response.status_code != 200:
            debug_print(f"[DIAMETER] edit_user returned non-200: {response.status_code}", "ERROR")
            return None
        
        # Check for login page
        if "Secure login" in response.text or "login" in response.text.lower():
            debug_print(f"[DIAMETER] Login page detected - session may be expired", "WARNING")
            return {'found': False, 'username': diameter_username, 'login_page': True}
        
        # Parse user data
        debug_print(f"[DIAMETER] Parsing edit_user page for user data", "INFO")
        user_data = parse_edit_user_page(response.text, diameter_username)
        
        if user_data.get('user_not_found', False):
            debug_print(f"[DIAMETER] User not found: {diameter_username}", "WARNING")
            return user_data
        
        # Only fetch traffic report if device is OFFLINE (online devices have all data on user page)
        if user_data.get('is_online', False):
            debug_print(f"[DIAMETER] Device ONLINE - all data from user page, skipping traffic report", "SUCCESS")
        else:
            debug_print(f"[DIAMETER] Device OFFLINE - fetching traffic report for last session", "INFO")
            traffic_data = get_diameter_traffic_data(session, base_url, diameter_username,
                                              user_data.get('last_logoff'),
                                              user_data.get('expiry_date'),
                                              user_data.get('registered_date'))
            if traffic_data:
                user_data['session_ip'] = traffic_data.get('session_ip', 'N/A')
                # Only fill in missing from traffic
                if user_data.get('mac_address', 'N/A') == 'N/A':
                    user_data['mac_address'] = traffic_data.get('mac_address', 'N/A')
                if user_data.get('nas_bts', 'N/A') == 'N/A':
                    user_data['nas_bts'] = traffic_data.get('nas_bts', 'N/A')
                user_data['traffic_date'] = traffic_data.get('traffic_date', None)


        
        # Ping test (keep as is)
        ping_result = False
        ping_ip_used = None
        if user_data['cpe_ip'] != 'N/A':
            debug_print(f"[DIAMETER] Testing ping to CPE IP: {user_data['cpe_ip']}", "INFO")
            ping_result = ping_ip(user_data['cpe_ip'])
            if ping_result:
                ping_ip_used = user_data['cpe_ip']
                debug_print(f"[DIAMETER] Ping successful to {ping_ip_used}", "SUCCESS")
            else:
                debug_print(f"[DIAMETER] Ping failed to {user_data['cpe_ip']}", "WARNING")
        
        account_expired = is_account_expired(user_data['expiry_date'])
        user_data['ping_reachable'] = ping_result
        user_data['ping_ip'] = ping_ip_used
        user_data['expired'] = account_expired
        
        debug_print(f"[DIAMETER] === END get_diameter_user_data - SUCCESS ===", "SUCCESS")
        return user_data
        
    except requests.exceptions.ReadTimeout:
        debug_print(f"[DIAMETER] Read timeout - server taking too long to respond", "ERROR")
        debug_print(f"[DIAMETER] Try increasing timeout values or check network connectivity to {DIAMETER_DOMAIN}", "ERROR")
        return None
    except requests.exceptions.ConnectionError as e:
        debug_print(f"[DIAMETER] Connection error: {e}", "ERROR")
        return None
    except Exception as e:
        debug_print(f"[DIAMETER] Error accessing Diameter: {e}", "ERROR")
        import traceback
        debug_print(f"[DIAMETER] Traceback: {traceback.format_exc()}", "ERROR")
        return None
    finally:
        session.close()

def is_account_expired(expiry_date):
    if not expiry_date or expiry_date == "N/A":
        return False
    try:
        expiry_dt = datetime.strptime(expiry_date.split()[0], "%Y-%m-%d")
        return expiry_dt < datetime.now()
    except:
        return False

# MAC Vendor lookup for Network Analysis
import urllib.request
import urllib.error

# Known Huawei OEM/brand names from MAC vendor API
HUAWEI_VENDOR_NAMES = [
    'huawei', 'goodman', 'hon hai', 'foxconn', 'fih',
]

@st.cache_data(ttl=86400)
def is_huawei_vendor(vendor_name):
    """Check if vendor name indicates a Huawei device (including OEMs)"""
    if not vendor_name:
        return False
    vendor_lower = vendor_name.lower()
    for name in HUAWEI_VENDOR_NAMES:
        if name in vendor_lower:
            return True
    return False

@st.cache_data(ttl=86400)
def get_mac_vendor(mac_address):
    """Look up vendor for a MAC address using macvendors.com API"""
    if not mac_address or mac_address == 'N/A':
        return ""
    clean_mac = mac_address.replace(':', '').replace('-', '').replace('.', '').upper()
    if len(clean_mac) < 6:
        return ""
    formatted_mac = ':'.join(clean_mac[i:i+2] for i in range(0, 12, 2))
    url = f"https://api.macvendors.com/{formatted_mac}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Python-Mac-Lookup'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read().decode('utf-8').strip()
    except:
        return ""

def format_network_analysis(diameter_data):
    if not diameter_data:
        return ""
    if diameter_data.get('user_not_found', False):
        return """
## ⚠️ User Not Found

**This PPPoE username does not exist in the system. Please confirm the correct PPPoE username with the client.**

The username you searched for could not be found in the Diameter database. This typically means:
- The username was typed incorrectly
- The client provided an incorrect username
- The account may have been deleted or never created

Please verify the correct username before proceeding with troubleshooting.
"""
    if diameter_data.get('login_page', False):
        return """
## ⚠️ Network Analysis Unavailable

**Session Expired:** The Diameter session is invalid. Please refresh your PHPSESSID.

This could happen if:
- The session has timed out
- The PHPSESSID is incorrect
- You need to log in to the Diameter web interface first

To fix this, get a fresh PHPSESSID from your browser after logging into Radius Manager.
"""
    if not diameter_data.get('found', False):
        return ""
    status_emoji = "🟢" if diameter_data.get('is_online') else "🔴"
    ping_emoji = "🟢" if diameter_data.get('ping_reachable') else "🔴"
    expiry_emoji = "🔴" if diameter_data.get('expired') else "🟢"
    full_name = f"{diameter_data.get('first_name', '')} {diameter_data.get('last_name', '')}".strip()
    if not full_name or full_name == 'N/A N/A':
        full_name = diameter_data.get('username', 'N/A')
    traffic_info = ""
    if diameter_data.get('traffic_date'):
        traffic_info = f"\n| **Traffic Data From** | - | `{diameter_data.get('traffic_date')}` |"
    analysis = f"""
## Network Analysis

| Metric | Status | Details |
|--------|--------|---------|
| **Full Name** | - | `{full_name}` |
| **Email** | - | `{diameter_data.get('email', 'N/A')}` |
| **Phone** | - | `{diameter_data.get('phone', 'N/A')}` |
| **Mobile** | - | `{diameter_data.get('mobile', 'N/A')}` |
| **Diameter Status** | {status_emoji} {diameter_data.get('status', 'N/A')} | - |
| **NAS/BTS** | - | `{diameter_data.get('nas_bts', 'N/A')}` |
| **Session IP** | - | `{diameter_data.get('session_ip', 'N/A')}` |
| **CPE IP** | - | `{diameter_data.get('cpe_ip', 'N/A')}` |
| **CM IP** | - | `{diameter_data.get('cm_ip', 'N/A')}` |
| **CM MAC** | - | `{diameter_data.get('cm_mac', 'N/A')}` |
| **MAC Address** | - | `{diameter_data.get('mac_address', 'N/A')}` {get_mac_vendor(diameter_data.get('mac_address', ''))} |
| **Ping (CPE IP)** | {ping_emoji} {"Reachable" if diameter_data.get('ping_reachable') else "Unreachable"} | via `{diameter_data.get('ping_ip', 'N/A')}` |
| **Account Status** | {expiry_emoji} {"EXPIRED" if diameter_data.get('expired') else "Active"} | Expires: `{diameter_data.get('expiry_date', 'N/A')}` |
| **Service Plan** | - | `{diameter_data.get('service_plan', 'N/A')}` |
| **Registered Date** | - | `{diameter_data.get('registered_date', 'N/A')}` |
| **Last Logoff** | - | `{diameter_data.get('last_logoff', 'N/A')}` |{traffic_info}
| **Address** | - | `{diameter_data.get('address', 'N/A')}` |
| **City/State** | - | `{diameter_data.get('city', 'N/A')}, {diameter_data.get('state', 'N/A')}` |
| **Country** | - | `{diameter_data.get('country', 'N/A')}` |
"""
    return analysis

def format_gpon_request_message():
    return """

**Action Required:** Unable to identify the connection type based on available information.

**Recommendation:** Kindly request the GPON Serial Number from the client for further troubleshooting. The serial number is usually found on a label on the ONT/ONU device and typically starts with letters like ZTE, HWTC, or ALCL.

Once you have the serial number, please search again using that information to get detailed diagnostic data from the OLT.
"""

def load_port_analysis_data():
    try:
        port_file_path = pathlib.Path(PORT_ANALYSIS_FILE)
        if not port_file_path.exists():
            port_file_path = SCRIPT_DIR / port_file_path.name
        if not port_file_path.exists():
            return []
        with open(port_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def extract_port_analysis_fields(output_string):
    try:
        output_dict = ast.literal_eval(output_string)
        return {
            "Explanation": output_dict.get("Explanation"), 
            "Action": output_dict.get("Action"), 
            "Severity": output_dict.get("Severity")
        }
    except Exception:
        return None

def find_port_analysis_match(percentages, flags):
    data = load_port_analysis_data()
    if not data:
        return None
    input_dict = {
        "onl": percentages.get('onl', 0), 
        "LOS": percentages.get('los', 0),
        "pf": percentages.get('pf', 0), 
        "ofl": percentages.get('ofl', 0),
        "flags": {
            "JCU": flags.get('JCU', 0), 
            "JWD": flags.get('JWD', 0),
            "HL": flags.get('HL', 0), 
            "MPI": flags.get('MPI', 0),
            "MST": flags.get('MST', 0)
        }
    }
    input_str = repr(input_dict).strip()
    for record in data:
        if record.get("input", "").strip() == input_str:
            return extract_port_analysis_fields(record.get("output", ""))
    return None

def clean_search_input_for_smartolt(search_text):
    if not search_text:
        return ""
    cleaned_text = search_text.replace('_', ' ')
    return ' '.join(cleaned_text.split()).strip()

def clean_search_input_for_selenium(search_text):
    if not search_text:
        return ""
    return search_text.strip()

def format_online_duration(duration_str):
    if not duration_str or duration_str == "N/A":
        return None
    years = months = days = hours = minutes = seconds = 0
    try:
        if 'y' in duration_str.lower():
            year_match = re.search(r'(\d+)\s*y', duration_str, re.IGNORECASE)
            if year_match:
                years = int(year_match.group(1))
        if 'month' in duration_str.lower():
            month_match = re.search(r'(\d+)\s*month', duration_str, re.IGNORECASE)
            if month_match:
                months = int(month_match.group(1))
        if 'd' in duration_str.lower():
            day_match = re.search(r'(\d+)\s*d', duration_str, re.IGNORECASE)
            if day_match:
                days = int(day_match.group(1))
        if 'h' in duration_str.lower():
            hour_match = re.search(r'(\d+)\s*h', duration_str, re.IGNORECASE)
            if hour_match:
                hours = int(hour_match.group(1))
        minute_match = re.search(r'(\d+)\s*m(?!o)', duration_str, re.IGNORECASE)
        if minute_match:
            minutes = int(minute_match.group(1))
        if 's' in duration_str.lower():
            second_match = re.search(r'(\d+)\s*s', duration_str, re.IGNORECASE)
            if second_match:
                seconds = int(second_match.group(1))
        return {
            "years": years, 
            "months": months, 
            "days": days, 
            "hours": hours, 
            "minutes": minutes, 
            "seconds": seconds
        }
    except Exception:
        return None

def calculate_uptime_from_duration(duration_str):
    if not duration_str or duration_str == "N/A":
        return None
    try:
        total_minutes = 0
        day_match = re.search(r'(\d+)\s*d', duration_str, re.IGNORECASE)
        if day_match:
            total_minutes += int(day_match.group(1)) * 24 * 60
        hour_match = re.search(r'(\d+)\s*h', duration_str, re.IGNORECASE)
        if hour_match:
            total_minutes += int(hour_match.group(1)) * 60
        minute_match = re.search(r'(\d+)\s*m', duration_str, re.IGNORECASE)
        if minute_match:
            total_minutes += int(minute_match.group(1))
        return total_minutes
    except:
        return None

def get_device_type(serial_number):
    if not serial_number or serial_number == "N/A":
        return "Unknown"
    serial_upper = serial_number.upper()
    if serial_upper.startswith(('ZTE', 'RTEGC', 'F4E4', 'B4DE', 'F4B8', 'ZXI', 'DC71')):
        return "ZTE"
    elif serial_upper.startswith('E0'):
        return "Cdata"
    elif serial_upper.startswith(('HWTC', 'C4B8', '208C', '002E', '0011')):
        return "Huawei"
    else:
        return "Unknown"

def parse_gpon_history_for_optical_issues(detail_output, time_offset=None):
    optical_keywords = ['LOS', 'LOSi', 'LOFi']
    optical_events = []
    table_match = re.search(r'Authpass Time\s+OfflineTime\s+Cause', detail_output, re.IGNORECASE)
    if not table_match:
        return 0, None
    pattern = re.compile(r'^\s*(\d+)\s+([\d-]+)\s+([\d:]+)\s+([\d-]+)\s+([\d:]+)\s+(.+?)$', re.MULTILINE)
    for match in pattern.finditer(detail_output):
        num = match.group(1)
        authpass_date = match.group(2)
        authpass_time = match.group(3)
        offline_date = match.group(4)
        offline_time = match.group(5)
        cause = match.group(6).strip()
        authpass_str = f"{authpass_date} {authpass_time}"
        offline_str = f"{offline_date} {offline_time}"
        try:
            authpass_dt = datetime.strptime(authpass_str, "%Y-%m-%d %H:%M:%S")
            if time_offset:
                authpass_dt = authpass_dt + time_offset
            if any(opt in cause for opt in optical_keywords):
                optical_events.append({
                    'authpass': authpass_dt,
                    'cause': cause
                })
                if offline_str != "0000-00-00 00:00:00":
                    offline_dt = datetime.strptime(offline_str, "%Y-%m-%d %H:%M:%S")
                    if time_offset:
                        offline_dt = offline_dt + time_offset
                    optical_events[-1]['offline'] = offline_dt
        except Exception as e:
            debug_print(f"Error parsing GPON history: {e}", "DEBUG")
            continue
    if not optical_events:
        return 0, None
    first_event = optical_events[0]
    last_event = optical_events[-1]
    start_time = first_event['authpass']
    if 'offline' in last_event and last_event['offline']:
        end_time = last_event['offline']
    else:
        end_time = last_event['authpass']
    duration = end_time - start_time
    if duration.days > 0:
        time_frame = f"{duration.days} days"
    elif duration.seconds >= 3600:
        hours = duration.seconds // 3600
        time_frame = f"{hours} hours"
    elif duration.seconds >= 60:
        minutes = duration.seconds // 60
        time_frame = f"{minutes} minutes"
    else:
        time_frame = "a few moments"
    return len(optical_events), time_frame

def parse_epon_history_for_optical_issues(detail_output, time_offset=None):
    optical_events = []
    lines = detail_output.split('\n')
    table_start = -1
    for i, line in enumerate(lines):
        if 'Register time' in line and 'Authpass Time' in line and 'OfflineTime' in line:
            table_start = i
            break
    if table_start == -1:
        for i, line in enumerate(lines):
            if 'Register time' in line and 'Authpass' in line:
                table_start = i
                break
    if table_start == -1:
        debug_print("EPON history table header not found", "DEBUG")
        return 0, None
    debug_print(f"EPON history table header found at line {table_start}", "DEBUG")
    i = table_start + 1
    while i < len(lines):
        line = lines[i].strip()
        match = re.match(r'^\s*(\d+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)$', line)
        if match:
            num = match.group(1)
            authpass_date = match.group(4)
            authpass_time = match.group(5)
            offline_date = match.group(6)
            offline_time = match.group(7)
            cause = match.group(8).strip()
            authpass_str = f"{authpass_date} {authpass_time}"
            offline_str = f"{offline_date} {offline_time}"
            debug_print(f"EPON entry {num}: authpass={authpass_str}, cause='{cause}'", "DEBUG")
            try:
                authpass_dt = datetime.strptime(authpass_str, "%Y/%m/%d %H:%M:%S")
                if time_offset:
                    authpass_dt = authpass_dt + time_offset
                if "Lin" in cause:
                    debug_print(f"  -> OPTICAL ISSUE DETECTED (Lin found) in entry {num}", "SUCCESS")
                    optical_events.append({
                        'authpass': authpass_dt,
                        'cause': cause,
                        'offline': None
                    })
                    if offline_str != "0000/00/00 00:00:00":
                        offline_dt = datetime.strptime(offline_str, "%Y/%m/%d %H:%M:%S")
                        if time_offset:
                            offline_dt = offline_dt + time_offset
                        optical_events[-1]['offline'] = offline_dt
            except Exception as e:
                debug_print(f"Error parsing EPON history entry {num}: {e}", "DEBUG")
            i += 1
        else:
            i += 1
    if not optical_events:
        debug_print(f"No optical events (Lin) found", "DEBUG")
        return 0, None
    first_event = optical_events[0]
    last_event = optical_events[-1]
    start_time = first_event['authpass']
    if last_event.get('offline'):
        end_time = last_event['offline']
    else:
        end_time = last_event['authpass']
    duration = end_time - start_time
    if duration.days > 0:
        time_frame = f"{duration.days} days"
    elif duration.seconds >= 3600:
        hours = duration.seconds // 3600
        time_frame = f"{hours} hours"
    elif duration.seconds >= 60:
        minutes = duration.seconds // 60
        time_frame = f"{minutes} minutes"
    else:
        time_frame = "a few moments"
    debug_print(f"Optical issues detected: {len(optical_events)} in {time_frame}", "WARNING")
    return len(optical_events), time_frame

def format_optical_issue_message(optical_count, time_frame, onu_type):
    if optical_count >= 2:
        if onu_type.lower() == "gpon":
            return f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced {optical_count} optical-related outages within the last {time_frame} before its current state."
        else:
            return f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced {optical_count} optical-related outages within the last {time_frame} before its current state."
    elif optical_count == 1:
        if onu_type.lower() == "gpon":
            return f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced 1 optical-related issue recently. Please monitor the connection."
        else:
            return f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced 1 Link disconnect recently. Please monitor the connection."
    return ""

def format_llm_response(smartolt_name, device_name, onu_type, serial_number, 
                        client_status, rx_power_val, uptime, downtime_reason, 
                        avg_port_power, is_high_loss, olt_name, board, port, time_ago,
                        optical_issue_message=""):
    if client_status == "online":
        uptime_parts = format_online_duration(uptime)
        if uptime_parts:
            parts = []
            if uptime_parts["years"] > 0:
                parts.append(f"{uptime_parts['years']}y")
            if uptime_parts["months"] > 0:
                parts.append(f"{uptime_parts['months']}m")
            if uptime_parts["days"] > 0:
                parts.append(f"{uptime_parts['days']}d")
            if uptime_parts["hours"] > 0:
                parts.append(f"{uptime_parts['hours']}h")
            if uptime_parts["minutes"] > 0:
                parts.append(f"{uptime_parts['minutes']}m")
            if uptime_parts["seconds"] > 0:
                parts.append(f"{uptime_parts['seconds']}s")
            uptime_str = " ".join(parts) if parts else "a few moments"
        else:
            uptime_str = "Unknown"
        signal_quality = "Good"
        signal_emoji = "🟢"
        if rx_power_val is not None:
            if rx_power_val < -29:
                signal_quality = "Poor"
                signal_emoji = "🔴"
            elif rx_power_val < -28:
                signal_quality = "Marginal"
                signal_emoji = "🟡"
        signal_str = f"{rx_power_val:.2f} dBm" if rx_power_val is not None else "N/A"
        if signal_quality == "Good":
            return f"""{signal_emoji} ONLINE | Signal: Good

**Diagnostic Report:** > Analysis of **{smartolt_name.upper()}** identifies the **{device_name}** **{onu_type.upper()}** device (SN: **{serial_number.upper()}**) as currently Online.

**Location Details:**

- **OLT:** {olt_name}
- **Port details:** Board **{board}** | Port **{port}**

The unit has maintained a continuous uptime of **{uptime_str}** with a signal strength of **{signal_str}**, which is within the optimal operating range.

- **Action Item:** > If the client reports a total loss of service despite these readings, please check Network Analysis below to confirm if the Ping is reachable before escalating the issue to the G-NOC group chat.

Thank you."""
        else:
            port_context = ""
            if is_high_loss:
                port_context = "Diagnostic data indicates the entire port is experiencing high optical power loss, impacting most connected ONUs. Please verify if this port is flagged; if not, urgently alert NOC to investigate the OLT port or distribution splitter."
            else:
                port_context = "The average port signal remains stable, suggesting an isolated physical layer issue at the client's premises. If the user experiences intermittent connectivity, please generate a support ticket for a technician visit to inspect the fiber terminations."
            return f"""{signal_emoji} ONLINE | Signal: {signal_quality}

**Diagnostic Report:** > **{smartolt_name.upper()}** is currently utilizing a **{device_name}** **{onu_type.upper()}** device (SN: **{serial_number.upper()}**).

**Location Details:**

- **OLT:** {olt_name}
- **Port details:** Board **{board}** | Port **{port}**

While the status is Online (Uptime: **{uptime_str}**), the current signal strength is recorded at **{signal_str}**. This indicates significant optical power loss affecting the client's ONU.

- **Diagnostic Context & Required Action:** > * {port_context}

Thank you."""
    else:
        if onu_type.lower() == "epon":
            if downtime_reason == "Lin":
                formatted_reason = "Loss of Signal"
            elif downtime_reason == "Pow":
                formatted_reason = "Power Failure"
            else:
                formatted_reason = downtime_reason
        else:
            reason_map = {
                "Loss of Signal": "Loss of Signal",
                "Power Failure": "Power Failure (Dying Gasp)",
                "Power Off": "Power Off",
                "Offline State": "Offline State"
            }
            base_reason = downtime_reason.split(" (")[0] if downtime_reason else "Unknown"
            formatted_reason = reason_map.get(base_reason, base_reason)
        downtime_duration = time_ago if time_ago else ""
        response = f"""🔴 OFFLINE

**Diagnostic Report:** > **{smartolt_name.upper()}** is currently Offline. The **{device_name}** **{onu_type.upper()}** device (SN: **{serial_number.upper()}**) has been unreachable from the OLT since **{downtime_duration}**.

**Location Details:**

- **OLT:** {olt_name}
- **Port details:** Board **{board}** | Port **{port}**
- **Reason for Outage:** The outage is attributed to: **{formatted_reason}**"""
        if optical_issue_message:
            response += optical_issue_message
        return response

def format_port_analysis(port_analysis, is_mst_detected, mst_clients=None, 
                         is_jcu_detected=None, jcu_clients=None,
                         is_jwd_detected=None, jwd_clients=None):
    result = "\n---\n\n## Port Analysis\n\n"
    if not port_analysis:
        percentages = DEBUG_DATA["port_stats"].get("percentages", {})
        flags = DEBUG_DATA["status_flags"]
        result += f"""- **⚠️ Port Analysis Error:** No exact match found in the port analysis database for this specific combination of port statistics and flags.

- **Current Port State:**
  - Online: {percentages.get('onl', 0)}%
  - LOS: {percentages.get('los', 0)}%
  - Power Failure: {percentages.get('pf', 0)}%
  - Offline: {percentages.get('ofl', 0)}%
  - Flags: {flags}

- **Explanation:** This specific combination of port statistics and flags does not match any predefined scenarios in the database.

- **Action Required:** Please manually review the port and add this scenario to the database if it's a recurring pattern.

- **Severity:** Review Required
"""
    else:
        explanation = port_analysis.get('Explanation', 'No explanation available')
        action = port_analysis.get('Action', 'No action specified')
        severity = port_analysis.get('Severity', 'Unknown')
        result += f"""- **Explanation:** {explanation}

- **Action:** {action}

- **Severity:** {severity}
"""
    if is_mst_detected and mst_clients and len(mst_clients) >= 2:
        result += "\n**Clients experiencing suspect MST issue:**\n"
        for client in mst_clients[:10]:
            result += f"- {client}\n"
        if len(mst_clients) > 10:
            result += f"- ... and {len(mst_clients) - 10} more\n"
    if is_jcu_detected and jcu_clients and len(jcu_clients) >= 3:
        result += "\n**Clients that just came up (within last 5 minutes):**\n"
        for client in jcu_clients[:10]:
            result += f"- {client}\n"
        if len(jcu_clients) > 10:
            result += f"- ... and {len(jcu_clients) - 10} more\n"
    if is_jwd_detected and jwd_clients and len(jwd_clients) >= 3:
        result += "\n**Clients that just went down (within last 5 minutes):**\n"
        for client in jwd_clients[:10]:
            result += f"- {client}\n"
        if len(jwd_clients) > 10:
            result += f"- ... and {len(jwd_clients) - 10} more\n"
    return result

class AutoLoginSystem:
    def __init__(self, driver, username, password):
        self.driver = driver
        self.username = username
        self.password = password
        self.login_interval = 1800
        self.last_login_check = None
        self.running = False
        self.login_thread = None
    def is_login_page(self):
        try:
            self.driver.find_element(By.NAME, "identity")
            self.driver.find_element(By.NAME, "password")
            self.driver.find_element(By.XPATH, "//input[@type='submit' and @value='Login']")
            return True
        except:
            return False
    def login(self):
        try:
            username_input = self.driver.find_element(By.NAME, "identity")
            username_input.clear()
            username_input.send_keys(self.username)
            password_input = self.driver.find_element(By.NAME, "password")
            password_input.clear()
            password_input.send_keys(self.password)
            login_button = self.driver.find_element(By.XPATH, "//input[@type='submit' and @value='Login']")
            login_button.click()
            time.sleep(3)
            if not self.is_login_page():
                return True
            return False
        except Exception:
            return False
    def monitor_and_login(self):
        self.running = True
        while self.running:
            try:
                current_time = datetime.now()
                should_check = self.is_login_page() or (self.last_login_check is None or 
                                                       (current_time - self.last_login_check) > timedelta(seconds=self.login_interval))
                if should_check:
                    self.last_login_check = current_time
                    if self.is_login_page():
                        self.login()
                time.sleep(60)
            except Exception:
                time.sleep(10)
    def start_monitoring(self):
        if self.login_thread is None or not self.login_thread.is_alive():
            self.login_thread = threading.Thread(target=self.monitor_and_login, daemon=True)
            self.login_thread.start()
    def stop_monitoring(self):
        self.running = False

GPON_STATE_REGEX = re.compile(r"(?m)^(\d+/\d+/\d+:\d+)\s+enable\s+\w+\s+(working|OffLine|LOS|DyingGasp)\s+\d+\(GPON\)", re.IGNORECASE)
EPON_STATE_REGEX = re.compile(r"(?m)^epon-onu_(\d+/\d+/\d+:\d+)\s+(Online|Offline|Power Off)\s+\w+\s+", re.IGNORECASE)
ONU_RX_POWER_REGEX = re.compile(r"down\s+Tx\s*:[\d\.\-]+\(dbm\)\s+Rx\s*:([\-\d\.]+)\(dbm\)", re.IGNORECASE)

def parse_onu_states(raw_output, onu_type="gpon"):
    grouped = defaultdict(list)
    working = []
    if onu_type.lower() == "gpon":
        for onu_id, state in GPON_STATE_REGEX.findall(raw_output):
            if state.lower() == "working":
                working.append(onu_id)
            else:
                grouped[state.upper()].append(onu_id)
    elif onu_type.lower() == "epon":
        for onu_id, state in EPON_STATE_REGEX.findall(raw_output):
            if state.lower() == "online":
                working.append(onu_id)
            else:
                grouped[state.upper()].append(onu_id)
    return grouped, working

def parse_onu_rx_power_single(raw_output):
    match = ONU_RX_POWER_REGEX.search(raw_output)
    if match:
        try:
            return float(match.group(1))
        except:
            return None
    return None

def parse_olt_time(raw_output):
    match = re.search(r'(\d{2}:\d{2}:\d{2})\s+\w+\s+(\w+)\s+(\d{1,2})\s+(\d{4})', raw_output)
    if not match:
        return datetime.now()
    time_part, month_str, day, year = match.groups()
    month_map = {"Jan":1, "Feb":2, "Mar":3, "Apr":4, "May":5, "Jun":6,
                 "Jul":7, "Aug":8, "Sep":9, "Oct":10, "Nov":11, "Dec":12}
    month = month_map.get(month_str)
    if not month:
        return datetime.now()
    return datetime.strptime(f"{year}-{month:02d}-{int(day):02d} {time_part}", "%Y-%m-%d %H:%M:%S")

def calculate_time_offset(olt_time):
    return datetime.now() - olt_time

def format_time_ago(event_time):
    if not event_time:
        return None
    diff = datetime.now() - event_time
    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds >= 3600:
        return f"{diff.seconds // 3600} hour{'s' if diff.seconds // 3600 > 1 else ''} ago"
    elif diff.seconds >= 60:
        return f"{diff.seconds // 60} minute{'s' if diff.seconds // 60 > 1 else ''} ago"
    else:
        return "just now"

async def telnet_connect(olt_ip):
    reader, writer = await telnetlib3.open_connection(olt_ip, 23, connect_minwait=0.05, connect_maxwait=1)
    writer.write(f"{TELNET_USERNAME}\n")
    await asyncio.sleep(0.5)
    writer.write(f"{TELNET_PASSWORD}\n")
    await asyncio.sleep(0.5)
    while True:
        chunk = await asyncio.wait_for(reader.read(1024), timeout=5)
        if "ZXAN>" in chunk or "ZXAN#" in chunk:
            break
    writer.write("terminal length 0\n")
    await asyncio.sleep(0.5)
    return reader, writer

async def send_command_with_pagination(reader, writer, command):
    writer.write(command + "\n")
    await asyncio.sleep(1.5)
    output = ""
    page_count = 0
    while page_count < 20:
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=3)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        output += chunk
        if '--More--' in chunk:
            writer.write(' ')
            page_count += 1
            await asyncio.sleep(0.8)
        if "ZXAN>" in chunk or "ZXAN#" in chunk:
            break
        await asyncio.sleep(0.2)
    return output

async def get_olt_time_correction(reader, writer):
    try:
        time_output = await send_command_with_pagination(reader, writer, "show clock")
        olt_time = parse_olt_time(time_output)
        return calculate_time_offset(olt_time)
    except:
        return timedelta(0)

def extract_client_info(detail_output):
    name = None
    serial = None
    name_match = re.search(r'Name:\s*(\S.+)', detail_output)
    if name_match:
        name = name_match.group(1).strip()
        name = re.sub(r'\s+', ' ', name)
    serial_match = re.search(r'Serial number:\s*(\S+)', detail_output, re.IGNORECASE)
    if serial_match:
        serial = serial_match.group(1).strip()
    return name, serial

def parse_epon_detail_info(raw_output, time_offset=None):
    offline_times = []
    online_duration = None
    name = None
    serial = None
    last_down_time = None
    last_down_cause = None
    name, serial = extract_client_info(raw_output)
    physical_state_match = re.search(r'Physical State:\s*(\w+)', raw_output, re.IGNORECASE)
    is_online = False
    if physical_state_match and physical_state_match.group(1).lower() == "online":
        is_online = True
    table_start = re.search(r'------------------------------------------', raw_output)
    if table_start:
        table_content = raw_output[table_start.end():]
        lines = table_content.strip().split('\n')
        if len(lines) > 1:
            for line in lines[1:]:
                match = re.match(r'^\s*(\d+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)$', line.strip())
                if match:
                    authpass_date = match.group(4)
                    authpass_time = match.group(5)
                    offline_date = match.group(6)
                    offline_time = match.group(7)
                    cause = match.group(8).strip()
                    authpass_str = f"{authpass_date} {authpass_time}"
                    offline_str = f"{offline_date} {offline_time}"
                    if is_online:
                        try:
                            authpass_dt = datetime.strptime(authpass_str, "%Y/%m/%d %H:%M:%S")
                            if time_offset:
                                authpass_dt = authpass_dt + time_offset
                            if not last_down_time or authpass_dt > last_down_time:
                                uptime_seconds = (datetime.now() - authpass_dt).total_seconds()
                                if uptime_seconds >= 0:
                                    uptime_parts = []
                                    days = int(uptime_seconds // 86400)
                                    if days > 0:
                                        uptime_parts.append(f"{days}d")
                                    hours = int((uptime_seconds % 86400) // 3600)
                                    if hours > 0 or days > 0:
                                        uptime_parts.append(f"{hours}h")
                                    minutes = int((uptime_seconds % 3600) // 60)
                                    if minutes > 0 or hours > 0 or days > 0:
                                        uptime_parts.append(f"{minutes}m")
                                    seconds = int(uptime_seconds % 60)
                                    if seconds > 0 and not uptime_parts:
                                        uptime_parts.append(f"{seconds}s")
                                    online_duration = " ".join(uptime_parts) if uptime_parts else "0m"
                        except:
                            pass
                    else:
                        if offline_str != "0000/00/00 00:00:00":
                            try:
                                offline_dt = datetime.strptime(offline_str, "%Y/%m/%d %H:%M:%S")
                                if time_offset:
                                    offline_dt = offline_dt + time_offset
                                last_down_cause = cause
                                if not last_down_time or offline_dt > last_down_time:
                                    last_down_time = offline_dt
                            except:
                                pass
    if not is_online and not last_down_cause and physical_state_match:
        phys_state = physical_state_match.group(1).lower()
        if phys_state == "power off":
            last_down_cause = "Pow"
        else:
            last_down_cause = phys_state.capitalize()
    return offline_times, online_duration, name, serial, last_down_time, last_down_cause

def parse_onu_detail_info(raw_output, time_offset=None):
    offline_times = []
    online_duration = None
    name, serial = extract_client_info(raw_output)
    dur_match = re.search(r"Online Duration:\s*([^\n]+)", raw_output)
    if dur_match:
        online_duration = dur_match.group(1).strip()
    timestamp_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})')
    for match in timestamp_pattern.finditer(raw_output):
        ts = match.group(1)
        if ts != "0000-00-00 00:00:00":
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                if time_offset:
                    dt = dt + time_offset
                offline_times.append(dt)
            except:
                continue
    return offline_times, online_duration, name, serial

async def get_port_signal_average(reader, writer, olt_port, onu_type):
    try:
        state_command = f"show {onu_type.lower()} onu state {onu_type.lower()}-{olt_port}\n"
        writer.write(state_command)
        await writer.drain()
        state_output = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=8)
                if not chunk:
                    break
                state_output += chunk
                if '--More--' in chunk:
                    writer.write(' ')
                    await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk:
                    break
            except asyncio.TimeoutError:
                break
        _, working_onus = parse_onu_states(state_output, onu_type)
        if not working_onus:
            return 0, 0, 0, 0
        rx_values = []
        for onu in working_onus[:20]:
            try:
                power_command = f"show pon power attenuation {onu_type.lower()}-onu_{onu}\n"
                writer.write(power_command)
                await writer.drain()
                power_output = ""
                while True:
                    try:
                        chunk = await asyncio.wait_for(reader.read(1024), timeout=5)
                        if not chunk:
                            break
                        power_output += chunk
                        if "ZXAN>" in chunk or "ZXAN#" in chunk:
                            break
                    except asyncio.TimeoutError:
                        break
                for line in power_output.split('\n'):
                    if 'down' in line.lower():
                        rx_match = re.search(r'Rx:([-\d\.]+)\(dbm\)', line, re.IGNORECASE)
                        if rx_match:
                            rx_values.append(float(rx_match.group(1)))
                            break
                await asyncio.sleep(0.3)
            except:
                continue
        if not rx_values:
            return 0, 0, 0, 0
        avg_signal = sum(rx_values) / len(rx_values)
        below_29 = sum(1 for s in rx_values if s < -29)
        below_28 = sum(1 for s in rx_values if s < -28)
        return avg_signal, below_28, below_29, len(rx_values)
    except:
        return 0, 0, 0, 0

async def connect_to_olt(OLT, olt_ip, onu_type, olt_port, onu_id, smartolt_name):
    result_lines = []
    status = "unknown"
    rx_power_val = None
    avg_port_power = 0
    downtime_reason = None
    online_duration = "N/A"
    time_ago = None
    optical_issue_message = ""
    global DEBUG_DATA
    DEBUG_DATA["smartolt_name"] = smartolt_name
    DEBUG_DATA["downtime_info"] = {"reason": None, "time_ago": None, "last_down": None}
    DEBUG_DATA["mst_clients"] = []
    DEBUG_DATA["jcu_clients"] = []
    DEBUG_DATA["jwd_clients"] = []
    try:
        reader, writer = await telnet_connect(olt_ip)
        time_offset = await get_olt_time_correction(reader, writer)
        state_command = f"show {onu_type.lower()} onu state {onu_type.lower()}-{olt_port}\n"
        writer.write(state_command)
        await writer.drain()
        state_output = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk:
                    break
                state_output += chunk
                if '--More--' in chunk:
                    writer.write(' ')
                    await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk:
                    break
            except asyncio.TimeoutError:
                break
        power_command = f"show pon power attenuation {onu_type.lower()}-onu_{olt_port.replace('olt_', '')}:{onu_id}\n"
        writer.write(power_command)
        await writer.drain()
        power_output = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk:
                    break
                power_output += chunk
                if '--More--' in chunk:
                    writer.write(' ')
                    await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk:
                    break
            except asyncio.TimeoutError:
                break
        rx_power_val = parse_onu_rx_power_single(power_output)
        target_onu = f"{olt_port.replace('olt_', '')}:{onu_id}"
        if onu_type.lower() == "gpon":
            detail_command = f"show {onu_type.lower()} onu detail-info {onu_type.lower()}-onu_{target_onu}\n"
        else:
            detail_command = f"show onu detail-info epon-onu_{target_onu}\n"
        writer.write(detail_command)
        await writer.drain()
        detail_output = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk:
                    break
                detail_output += chunk
                if '--More--' in chunk:
                    writer.write(' ')
                    await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk:
                    break
            except asyncio.TimeoutError:
                break
        grouped, working_onus = parse_onu_states(state_output, onu_type)
        if onu_type.lower() == "gpon":
            offline_times, online_duration, name, serial = parse_onu_detail_info(detail_output, time_offset)
            optical_count, optical_time_frame = parse_gpon_history_for_optical_issues(detail_output, time_offset)
            if optical_count >= 2:
                optical_issue_message = format_optical_issue_message(optical_count, optical_time_frame, onu_type)
            found = False
            target_onu_full = f"{olt_port.replace('olt_', '')}:{onu_id}"
            for onu in working_onus:
                if onu == target_onu_full:
                    found = True
                    status = "online"
                    if offline_times:
                        last_down = max(offline_times)
                        uptime_seconds = (datetime.now() - last_down).total_seconds()
                        if uptime_seconds >= 0:
                            uptime_parts = []
                            days = int(uptime_seconds // 86400)
                            if days > 0:
                                uptime_parts.append(f"{days}d")
                            hours = int((uptime_seconds % 86400) // 3600)
                            if hours > 0 or days > 0:
                                uptime_parts.append(f"{hours}h")
                            minutes = int((uptime_seconds % 3600) // 60)
                            if minutes > 0 or hours > 0 or days > 0:
                                uptime_parts.append(f"{minutes}m")
                            seconds = int(uptime_seconds % 60)
                            if seconds > 0 and not uptime_parts:
                                uptime_parts.append(f"{seconds}s")
                            online_duration = " ".join(uptime_parts) if uptime_parts else "0m"
                    break
            if not found:
                for state, onus in grouped.items():
                    for onu in onus:
                        if onu == target_onu_full:
                            found = True
                            status = "offline"
                            if offline_times:
                                last_down = max(offline_times)
                                time_ago = format_time_ago(last_down)
                                if state.upper() == "LOS":
                                    downtime_reason = f"Loss of Signal ({time_ago})"
                                elif state.upper() == "DYINGGASP":
                                    downtime_reason = f"Power Failure ({time_ago})"
                                else:
                                    downtime_reason = f"{state} ({time_ago})"
                                DEBUG_DATA["downtime_info"] = {"reason": downtime_reason, "time_ago": time_ago, "last_down": last_down}
                            break
                    if found:
                        break
            if not found:
                status = "not_found"
                result_lines.append(f"❌ ONU ID {onu_id} not found in the list.")
        else:
            offline_times, online_duration, name, serial, last_down, cause = parse_epon_detail_info(detail_output, time_offset)
            optical_count, optical_time_frame = parse_epon_history_for_optical_issues(detail_output, time_offset)
            if optical_count >= 2:
                optical_issue_message = format_optical_issue_message(optical_count, optical_time_frame, onu_type)
            physical_state_match = re.search(r'Physical State:\s*(\w+)', detail_output, re.IGNORECASE)
            if physical_state_match and physical_state_match.group(1).lower() == "online":
                status = "online"
            else:
                status = "offline"
                if last_down:
                    time_ago = format_time_ago(last_down)
                    downtime_reason = cause if cause else "Unknown"
                    DEBUG_DATA["downtime_info"] = {"reason": downtime_reason, "time_ago": time_ago, "last_down": last_down}
        total_clients = len(working_onus)
        for state, onus in grouped.items():
            total_clients += len(onus)
        online_clients = len(working_onus)
        los_clients = len(grouped.get("LOS", []))
        dyinggasp_clients = len(grouped.get("DYINGGASP", []))
        offline_clients = len(grouped.get("OFFLINE", [])) + len(grouped.get("POWER OFF", []))
        DEBUG_DATA["port_stats"] = {
            "total_onu": total_clients, 
            "online": online_clients, 
            "los": los_clients,
            "dyinggasp": dyinggasp_clients, 
            "offline": offline_clients, 
            "percentages": {}
        }
        if total_clients > 0:
            onu_data = {"onl": online_clients, "LOS": los_clients, "pf": dyinggasp_clients, "ofl": offline_clients}
            percentages = round_percentages_to_10(onu_data)
            DEBUG_DATA["port_stats"]["percentages"] = {
                "onl": percentages.get("onl", 0), 
                "los": percentages.get("LOS", 0),
                "pf": percentages.get("pf", 0), 
                "ofl": percentages.get("ofl", 0)
            }
        avg_port_power, below_28, below_29, total_onus = await get_port_signal_average(reader, writer, olt_port, onu_type)
        DEBUG_DATA["status_flags"] = {"JCU": 0, "JWD": 0, "HL": 0, "MPI": 0, "MST": 0}
        is_high_loss = False
        if avg_port_power < -29:
            is_high_loss = True
            DEBUG_DATA["status_flags"]["HL"] = 1
        elif total_onus > 0 and (below_29 / total_onus) >= 0.7:
            is_high_loss = True
            DEBUG_DATA["status_flags"]["HL"] = 1
        elif total_onus > 0 and (below_28 / total_onus) >= 0.85:
            is_high_loss = True
            DEBUG_DATA["status_flags"]["HL"] = 1
        port_analysis_lines, mst_clients, jcu_clients, jwd_clients = await get_detailed_port_analysis(
            reader, writer, olt_port, onu_type, time_offset, downtime_reason or "unknown", total_clients, online_clients
        )
        DEBUG_DATA["mst_clients"] = mst_clients
        DEBUG_DATA["jcu_clients"] = jcu_clients
        DEBUG_DATA["jwd_clients"] = jwd_clients
        if len(mst_clients) >= 2:
            DEBUG_DATA["status_flags"]["MST"] = 1
        if len(jcu_clients) >= 3:
            DEBUG_DATA["status_flags"]["JCU"] = 1
        if len(jwd_clients) >= 3:
            DEBUG_DATA["status_flags"]["JWD"] = 1
        if total_clients > 0 and (online_clients == 0 or (online_clients / total_clients) <= 0.2):
            DEBUG_DATA["status_flags"]["MPI"] = 1
        writer.close()
    except Exception as e:
        result_lines.append(f"Error connecting to OLT: {str(e)}")
        status = "error"
        debug_print(f"Error in connect_to_olt: {e}", "ERROR")
    return result_lines, status, avg_port_power, is_high_loss, rx_power_val, online_duration, downtime_reason, time_ago, optical_issue_message

async def get_detailed_port_analysis(reader, writer, olt_port, onu_type, time_offset, current_onu_state, total_clients, online_clients):
    mst_clients = []
    jcu_clients = []
    jwd_clients = []
    try:
        state_command = f"show {onu_type.lower()} onu state {onu_type.lower()}-{olt_port}\n"
        writer.write(state_command)
        await writer.drain()
        state_output = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk:
                    break
                state_output += chunk
                if '--More--' in chunk:
                    writer.write(' ')
                    await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk:
                    break
            except asyncio.TimeoutError:
                break
        grouped, working_onus = parse_onu_states(state_output, onu_type)
        for onu_id in working_onus[:30]:
            detail_info = await get_onu_details(reader, writer, onu_id, onu_type, time_offset)
            uptime_minutes = calculate_uptime_from_duration(detail_info.get("online_duration", "N/A"))
            if uptime_minutes is not None and uptime_minutes <= 5 and detail_info.get("client_name") and detail_info["client_name"] != "Unknown":
                jcu_clients.append(detail_info["client_name"])
        non_working_onus = [(onu, state) for state, onus in grouped.items() for onu in onus]
        los_records = []
        for onu_id, state in non_working_onus[:30]:
            detail_info = await get_onu_details(reader, writer, onu_id, onu_type, time_offset)
            if detail_info.get("last_down"):
                last_down = detail_info["last_down"]
                if datetime.now() - last_down <= timedelta(minutes=5) and detail_info.get("client_name") and detail_info["client_name"] != "Unknown":
                    jwd_clients.append(detail_info["client_name"])
                los_records.append({
                    "onu_id": onu_id, 
                    "client_name": detail_info.get("client_name", "Unknown"), 
                    "last_down": last_down, 
                    "state": state
                })
        if len(los_records) >= 2:
            mst_time_groups = defaultdict(list)
            for record in los_records:
                if record["last_down"]:
                    time_key = record["last_down"].replace(second=0, microsecond=0)
                    minute = (time_key.minute // 5) * 5
                    time_key = time_key.replace(minute=minute)
                    mst_time_groups[time_key].append(record)
            for records in mst_time_groups.values():
                if 2 <= len(records) <= 8:
                    for record in records:
                        if record["client_name"] and record["client_name"] != "Unknown":
                            mst_clients.append(record["client_name"])
    except Exception as e:
        debug_print(f"Error in port analysis: {str(e)}", "ERROR")
    return [], mst_clients, jcu_clients, jwd_clients

async def get_onu_details(reader, writer, onu_id, onu_type, time_offset=None):
    try:
        if onu_type.lower() == "gpon":
            detail_command = f"show {onu_type.lower()} onu detail-info {onu_type.lower()}-onu_{onu_id}\n"
        else:
            detail_command = f"show onu detail-info epon-onu_{onu_id}\n"
        writer.write(detail_command)
        await writer.drain()
        detail_output = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=8)
                if not chunk:
                    break
                detail_output += chunk
                if '--More--' in chunk:
                    writer.write(' ')
                    await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk:
                    break
            except asyncio.TimeoutError:
                break
        if onu_type.lower() == "gpon":
            offline_times, online_duration, name, serial = parse_onu_detail_info(detail_output, time_offset)
            last_down = max(offline_times) if offline_times else None
            time_ago = format_time_ago(last_down) if last_down else "N/A"
            return {
                "client_name": name or "Unknown", 
                "serial": serial or "N/A", 
                "last_down": last_down, 
                "time_ago": time_ago, 
                "online_duration": online_duration or "N/A"
            }
        else:
            _, online_duration, name, serial, last_down, cause = parse_epon_detail_info(detail_output, time_offset)
            time_ago = format_time_ago(last_down) if last_down else "N/A"
            return {
                "client_name": name or "Unknown", 
                "serial": serial or "N/A", 
                "last_down": last_down, 
                "time_ago": time_ago, 
                "online_duration": online_duration or "N/A",
                "cause": cause
            }
    except Exception:
        return {
            "client_name": "Unknown", 
            "serial": "N/A", 
            "last_down": None, 
            "time_ago": "N/A", 
            "online_duration": "N/A"
        }

def round_percentages_to_10(data):
    total = sum(data.values())
    if total == 0:
        return {k: 0 for k in data}
    real_percentages = {k: (v / total) * 100 for k, v in data.items()}
    rounded = {}
    differences = {}
    for k, v in real_percentages.items():
        rounded_value = round(v / 10) * 10
        rounded[k] = rounded_value
        differences[k] = v - rounded_value
    current_sum = sum(rounded.values())
    remainder = 100 - current_sum
    if remainder != 0:
        adjustment = 10 if remainder > 0 else -10
        steps_needed = abs(remainder) // 10
        candidates = sorted(differences.items(), key=lambda x: x[1], reverse=(remainder > 0))
        for i in range(min(steps_needed, len(candidates))):
            rounded[candidates[i][0]] += adjustment
    return rounded

def print_debug_header():
    debug_print("=" * 60, "DEBUG")
    debug_print("CLIENT SEARCH DEBUG INFORMATION", "DEBUG")
    debug_print("=" * 60, "DEBUG")

def print_client_info(smartolt_name, serial_number, olt_full, board, port, onu_type, device_name):
    debug_print(f"Smart OLT Name: {smartolt_name.upper()}", "CLIENT")
    debug_print(f"Serial Number: {serial_number.upper()}", "CLIENT")
    debug_print(f"Device Name: {device_name}", "CLIENT")
    debug_print(f"OLT: {olt_full}", "CLIENT")
    debug_print(f"Board: {board}", "CLIENT")
    debug_print(f"Port: {port}", "CLIENT")
    debug_print(f"ONU Type: {onu_type.upper()}", "CLIENT")
    debug_print("-" * 40, "DEBUG")

def print_port_statistics():
    stats = DEBUG_DATA["port_stats"]
    debug_print("PORT STATISTICS", "PORT")
    debug_print(f"Total ONUs: {stats['total_onu']}", "PORT")
    debug_print(f"Online: {stats['online']}", "PORT")
    debug_print(f"LOS: {stats['los']}", "PORT")
    debug_print(f"Power Failure: {stats['dyinggasp']}", "PORT")
    debug_print(f"Offline: {stats['offline']}", "PORT")
    if stats["percentages"]:
        pct = stats["percentages"]
        debug_print("PERCENTAGES (Rounded to nearest 10%)", "PORT")
        debug_print(f"Online (onl): {pct.get('onl', 0)}%", "PORT")
        debug_print(f"LOS (los): {pct.get('los', 0)}%", "PORT")
        debug_print(f"Power Failure (pf): {pct.get('pf', 0)}%", "PORT")
        debug_print(f"Offline (ofl): {pct.get('ofl', 0)}%", "PORT")

def print_status_flags():
    flags = DEBUG_DATA["status_flags"]
    debug_print("STATUS FLAGS (1=True, 0=False)", "DEBUG")
    debug_print(f"HL (High Loss): {flags['HL']}", "DEBUG")
    debug_print(f"MPI (Major Port Issue): {flags['MPI']}", "DEBUG")
    debug_print(f"MST (Suspected MST): {flags['MST']}", "DEBUG")
    debug_print(f"JCU (Just Came Up): {flags['JCU']}", "DEBUG")
    debug_print(f"JWD (Just Went Down): {flags['JWD']}", "DEBUG")

def print_downtime_info():
    downtime = DEBUG_DATA["downtime_info"]
    if downtime["reason"]:
        debug_print("DOWNTIME INFORMATION", "WARNING")
        debug_print(f"Reason: {downtime['reason']}", "WARNING")
        debug_print(f"Time Ago: {downtime['time_ago']}", "WARNING")

def create_selenium_driver(user_data_dir: str = None, is_search: bool = False):
    """Create and configure Chrome driver - FORCES headless for server"""
    global USE_VISIBLE_MODE
    
    options = Options()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
    
    # FORCE headless mode on server
    use_headless = True
    
    if use_headless:
        if is_search:
            debug_print(f"   Search Chrome: HEADLESS mode (server)", "SELENIUM")
        else:
            debug_print(f"   Update Chrome: HEADLESS mode (server)", "SELENIUM")
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-logging')
        options.add_argument('--log-level=3')
        options.add_argument('--silent')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--ignore-ssl-errors')
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option('useAutomationExtension', False)
    else:
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-extensions')
    
    options.add_argument('--disable-background-timer-throttling')
    options.add_argument('--disable-backgrounding-occluded-windows')
    options.add_argument('--disable-renderer-backgrounding')
    options.page_load_strategy = 'eager'
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        debug_print(f"   Chrome driver created with webdriver-manager", "SELENIUM")
    except Exception as e:
        debug_print(f"   webdriver-manager failed: {e}", "WARNING")
        options.binary_location = '/usr/bin/google-chrome'
        driver = webdriver.Chrome(options=options)
        debug_print(f"   Chrome driver created with system Chrome", "SELENIUM")
    
    driver.execute_cdp_cmd("Network.enable", {})
    
    return driver

def login_to_selenium_olt(driver, olt_ip: str, username: str, password: str, is_search: bool = False, max_retries: int = 3):
    login_url = f"http://{olt_ip}/#/login"
    for attempt in range(max_retries):
        try:
            driver.get(login_url)
            time.sleep(3)
            
            # Check if refresh needed
            need_refresh = False
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "el-input__inner"))
                )
            except TimeoutException:
                debug_print(f"   Login elements not found, refreshing...", "SELENIUM")
                need_refresh = True
            
            if need_refresh:
                driver.refresh()
                time.sleep(3)
                # Clear logs after refresh
                try:
                    driver.get_log("performance")
                except:
                    pass
            
            wait = WebDriverWait(driver, 20)
            inputs = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "el-input__inner")))
            
            if len(inputs) < 2:
                continue
            
            inputs[0].clear()
            inputs[0].send_keys(username)
            inputs[1].clear()
            inputs[1].send_keys(password)
            
            # Find login button
            login_btn = None
            try:
                login_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Login')]")
            except:
                login_btn = driver.find_element(By.XPATH, "//button")
            
            login_btn.click()
            time.sleep(5)
            
            if "login" in driver.current_url.lower():
                continue
            
            # Clear logs after successful login
            try:
                driver.get_log("performance")
            except:
                pass
            
            if is_search:
                debug_print(f"   ✓ Search Chrome logged into {olt_ip}", "SELENIUM")
            else:
                debug_print(f"   ✓ Update Chrome logged into {olt_ip}", "SELENIUM")
            return True
            
        except TimeoutException:
            if attempt == max_retries - 1:
                raise
        except Exception as e:
            debug_print(f"   Login attempt {attempt+1} failed: {e}", "WARNING")
            if attempt == max_retries - 1:
                raise
    
    return False

def capture_api_response_selenium(driver, keyword: str):
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                message = json.loads(entry["message"])
                log_message = message.get("message", {})
                
                if log_message.get("method") == "Network.responseReceived":
                    params = log_message.get("params", {})
                    response = params.get("response", {})
                    url = response.get("url", "")
                    
                    if keyword in url:
                        request_id = params.get("requestId")
                        if request_id and isinstance(request_id, str):
                            try:
                                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
                                if body and "body" in body:
                                    try:
                                        return json.loads(body["body"])
                                    except:
                                        return body["body"]
                            except Exception:
                                continue
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    except Exception:
        pass
    
    return None

def load_status_page_selenium(driver, olt_ip: str):
    status_page = f"http://{olt_ip}/#/status"
    driver.get(status_page)
    time.sleep(3)
    driver.get_log("performance")

def get_mac_table_selenium(driver, olt_ip: str):
    mac_page_options = [f"http://{olt_ip}/#/mac_table", f"http://{olt_ip}/#/mac_mgmt"]
    for mac_url in mac_page_options:
        try:
            driver.get_log("performance")
            driver.get(mac_url)
            time.sleep(5)
            mac_data = capture_api_response_selenium(driver, "sw_mac_table")
            if mac_data is None:
                mac_data = capture_api_response_selenium(driver, "mac_table")
            if mac_data is not None:
                if isinstance(mac_data, dict):
                    data = mac_data.get("data")
                    if isinstance(data, list):
                        return data
                elif isinstance(mac_data, list):
                    return mac_data
        except Exception:
            continue
    
    return []

def parse_power_dbm_selenium(power_str: str) -> Optional[float]:
    if power_str == 'N/A' or not power_str:
        return None
    power_num = re.sub(r'[^\d.-]', '', power_str)
    try:
        return float(power_num)
    except ValueError:
        return None

def extract_ont_data_selenium(ont, port, onu_id, existing_ont=None):
    if not isinstance(ont, dict):
        return {
            "rstate": 0,
            "ont_name": "N/A",
            "ont_sn": "N/A",
            "receive_power": "N/A",
            "last_d_time": "N/A",
            "onu_id": int(onu_id) if onu_id is not None else 0,
            "port_id": int(port) if port is not None else 0,
            "macaddr": "N/A"
        }
    
    rstate = 0
    if 'rstate' in ont:
        rstate = 1 if ont['rstate'] == 1 else 0
    
    ont_name = 'N/A'
    for name_key in ['ont_name', 'name', 'description', 'ont_description']:
        if name_key in ont and ont[name_key]:
            ont_name = str(ont[name_key])
            break
    
    ont_sn = 'N/A'
    for sn_key in ['ont_sn', 'sn', 'serial', 'serial_number', 'serial_num']:
        if sn_key in ont and ont[sn_key]:
            ont_sn = str(ont[sn_key])
            break
    
    receive_power = 'N/A'
    for power_key in ['receive_power', 'rx_power', 'rxpower', 'rx']:
        if power_key in ont and ont[power_key] is not None and ont[power_key] != '':
            receive_power = str(ont[power_key])
            if receive_power.replace('.', '').replace('-', '').replace('+', '').isdigit():
                if not receive_power.endswith('dBm'):
                    receive_power = f"{receive_power} dBm"
            break
    
    last_d_time = 'N/A'
    for time_key in ['last_d_time', 'last_downtime', 'last_down_time', 'last_d']:
        if time_key in ont and ont[time_key]:
            last_d_time = str(ont[time_key])
            break
    
    if existing_ont and isinstance(existing_ont, dict):
        if receive_power == 'N/A' and existing_ont.get('receive_power', 'N/A') != 'N/A':
            receive_power = existing_ont['receive_power']
        if last_d_time == 'N/A' and existing_ont.get('last_d_time', 'N/A') != 'N/A':
            last_d_time = existing_ont['last_d_time']
        if ont_name == 'N/A' and existing_ont.get('ont_name', 'N/A') != 'N/A':
            ont_name = existing_ont['ont_name']
        if ont_sn == 'N/A' and existing_ont.get('ont_sn', 'N/A') != 'N/A':
            ont_sn = existing_ont['ont_sn']
    
    # Ensure proper integer conversion
    try:
        onu_id_int = int(onu_id) if onu_id is not None else 0
    except (ValueError, TypeError):
        onu_id_int = 0
    
    try:
        port_int = int(port) if port is not None else 0
    except (ValueError, TypeError):
        port_int = 0
    
    return {
        "rstate": rstate,
        "ont_name": ont_name,
        "ont_sn": ont_sn,
        "receive_power": receive_power,
        "last_d_time": last_d_time,
        "onu_id": onu_id_int,
        "port_id": port_int,
        "macaddr": "N/A"
    }

def create_mac_lookup_selenium(mac_entries):
    mac_lookup = {}
    
    if not isinstance(mac_entries, list):
        return mac_lookup
    
    for mac_entry in mac_entries:
        if not isinstance(mac_entry, dict):
            continue
        
        port_id = None
        for key in ['port_id', 'port', 'interface_port']:
            if key in mac_entry and mac_entry[key] is not None:
                val = mac_entry[key]
                if isinstance(val, (int, float)):
                    port_id = int(val)
                    break
                elif isinstance(val, str):
                    numbers = re.findall(r'\d+', val)
                    if numbers:
                        port_id = int(numbers[0])
                        break
        
        ont_id = None
        for key in ['ont_id', 'onu_id', 'ont', 'onu']:
            if key in mac_entry and mac_entry[key] is not None:
                val = mac_entry[key]
                if isinstance(val, (int, float)):
                    ont_id = int(val)
                    break
                elif isinstance(val, str):
                    numbers = re.findall(r'\d+', val)
                    if numbers:
                        ont_id = int(numbers[0])
                        break
        
        mac_addr = None
        for key in ['mac', 'mac_address', 'macaddr', 'mac_addr']:
            if key in mac_entry and mac_entry[key]:
                mac_addr = str(mac_entry[key]).upper()
                break
        
        if port_id is not None and ont_id is not None and mac_addr and mac_addr != 'N/A':
            key = (port_id, ont_id)
            mac_lookup[key] = mac_addr
    
    return mac_lookup

def collect_port_statistics_selenium(driver, olt_ip: str, olt_name: str, port: int, mac_lookup: dict, verbose=False, is_search=False) -> Dict:
    if verbose:
        if is_search:
            debug_print(f"   Search Chrome: Scanning Port {port}", "SELENIUM")
        else:
            debug_print(f"   Update Chrome: Scanning Port {port}", "SELENIUM")
    
    # Clear logs before starting
    try:
        driver.get_log("performance")
    except:
        pass
    
    gpon_data = None
    
    # Try twice
    for retry in range(2):
        try:
            gpon_url = f"http://{olt_ip}/#/onu_allow?port_id={port}"
            driver.get(gpon_url)
            time.sleep(4)
            
            gpon_data = capture_api_response_selenium(driver, "gponont_mgmt")
            
            if gpon_data and isinstance(gpon_data, dict):
                break
            
            if retry == 0:
                debug_print(f"   Port {port}: No response, refreshing...", "SELENIUM")
                driver.refresh()
                time.sleep(4)
                try:
                    driver.get_log("performance")
                except:
                    pass
        except Exception:
            if retry == 0:
                time.sleep(2)
    
    port_stats = {
        "port_id": port,
        "total_onts": 0,
        "online_onts": 0,
        "offline_onts": 0,
        "average_power_dbm": None,
        "power_readings": [],
        "high_loss_flag": False,
        "onts": []
    }
    
    if gpon_data and isinstance(gpon_data, dict):
        port_data = gpon_data.get("data")
        if isinstance(port_data, list):
            power_sum = 0.0
            power_count = 0
            
            for idx, ont in enumerate(port_data):
                if not isinstance(ont, dict):
                    continue
                
                # Safe integer conversion
                try:
                    current_idx = int(idx) if idx is not None else 0
                except (ValueError, TypeError):
                    current_idx = 0
                
                ont_data = {
                    "rstate": 1 if ont.get('rstate') == 1 else 0,
                    "ont_name": ont.get('ont_name', ont.get('name', 'N/A')),
                    "ont_sn": ont.get('ont_sn', ont.get('sn', 'N/A')),
                    "receive_power": ont.get('receive_power', ont.get('rx_power', 'N/A')),
                    "last_d_time": ont.get('last_d_time', ont.get('last_downtime', 'N/A')),
                    "onu_id": current_idx,
                    "port_id": port,
                    "macaddr": "N/A"
                }
                
                # Format power value
                if ont_data['receive_power'] != 'N/A':
                    power_str = str(ont_data['receive_power'])
                    if power_str.replace('.', '').replace('-', '').replace('+', '').isdigit():
                        if not power_str.endswith('dBm'):
                            ont_data['receive_power'] = f"{power_str} dBm"
                
                # Add MAC if available
                key = (port, current_idx)
                if key in mac_lookup:
                    ont_data['macaddr'] = mac_lookup[key]
                
                if not is_search:
                    try:
                        update_ont_in_selenium_database(ont_data, olt_ip, olt_name)
                    except Exception:
                        pass
                
                port_stats["onts"].append(ont_data)
                port_stats["total_onts"] += 1
                
                if ont_data['rstate'] == 1:
                    port_stats["online_onts"] += 1
                    
                    # Parse power value
                    power_val = None
                    if ont_data['receive_power'] != 'N/A':
                        try:
                            power_num = re.sub(r'[^\d.-]', '', ont_data['receive_power'])
                            if power_num:
                                power_val = float(power_num)
                        except:
                            pass
                    
                    if power_val is not None:
                        power_sum += power_val
                        power_count += 1
                        port_stats["power_readings"].append(power_val)
                else:
                    port_stats["offline_onts"] += 1
            
            if power_count > 0:
                avg_power = power_sum / power_count
                port_stats["average_power_dbm"] = round(avg_power, 2)
                if avg_power < PORT_HIGH_LOSS_THRESHOLD:
                    port_stats["high_loss_flag"] = True
            
            try:
                update_port_health_selenium(olt_ip, olt_name, port, port_stats["average_power_dbm"], 
                                            port_stats["total_onts"], port_stats["online_onts"])
            except Exception:
                pass
            
            if verbose:
                status_line = f"  Port {port}: 🟢 {port_stats['online_onts']}/{port_stats['total_onts']} online"
                if port_stats["average_power_dbm"] is not None:
                    status_line += f" | Avg RX Power: {port_stats['average_power_dbm']} dBm"
                    if port_stats["high_loss_flag"]:
                        status_line += f" ⚠️ HIGH LOSS"
                debug_print(status_line, "SELENIUM")
    
    return port_stats

def detect_device_vendor_selenium(serial_number: str) -> str:
    if not serial_number or serial_number == 'N/A':
        return "GPON"
    sn_upper = serial_number.upper()
    if sn_upper.startswith('HWT'):
        return "Huawei"
    elif sn_upper.startswith('ZXIC') or sn_upper.startswith('ZTE'):
        return "ZTE"
    elif sn_upper.startswith('ALCL'):
        return "Alcatel-Lucent"
    elif sn_upper.startswith('FHTT'):
        return "FibreHome"
    elif sn_upper.startswith('CMDC'):
        return "Cisco"
    else:
        return "GPON"

def generate_selenium_diagnostic_report(target_ont: Dict, port_stats: Dict, olt_name: str) -> str:
    olt_name = extract_olt_name(olt_name)
    port_id = port_stats.get('port_id', 'Unknown')
    port_avg = port_stats.get('average_power_dbm')
    port_high_loss = port_stats.get('high_loss_flag', False)
    if port_stats.get('online_onts', 0) == 0:
        return f"""

🔴 **PON PORT IS CURRENTLY DOWN** | No Online Clients

**Diagnostic Report:** > The PON port is currently down

**Location Details:**
- **OLT:** {olt_name}
- **Port:** {port_id}

**Action Item:** > Confirm if the port has been flagged, if not Escalate to NOC immediately.
Thank you."""
    if target_ont:
        ont_name = target_ont.get('ont_name', 'Unknown')
        serial_number = target_ont.get('ont_sn', 'N/A')
        vendor = detect_device_vendor_selenium(serial_number)
        current_power_str = target_ont.get('receive_power', 'N/A')
        current_power = parse_power_dbm_selenium(current_power_str)
        is_power_poor = False
        if current_power is not None:
            is_power_poor = current_power < POOR_SIGNAL_THRESHOLD
        is_port_average_poor = False
        if port_avg is not None:
            is_port_average_poor = port_avg < POOR_SIGNAL_THRESHOLD
        if target_ont.get('rstate') == 1 and current_power is not None and not is_power_poor:
            power_display = f"{current_power:.2f} dBm" if current_power is not None else current_power_str
            report = f"""

🟢 **ONLINE** | Signal: **Good** (**{current_power_str}**)

**Diagnostic Report:** > Analysis of **{ont_name}** identifies the **{vendor}** GPON device (SN: **{serial_number}**) as currently Online.

**Location Details:**
- **OLT:** {olt_name}
- **Port:** {port_id}
The unit has a signal strength of **{power_display}**, which is within the optimal operating range.

**Action Item:** > If the client reports a total loss of service despite these readings, please check Network Analysis below to confirm if the Ping is reachable before escalating the issue to the G-NOC group chat.

Thank you."""
            return report
        if target_ont.get('rstate') == 1 and is_power_poor and not is_port_average_poor:
            power_display = f"{current_power:.2f} dBm" if current_power is not None else current_power_str
            return f"""

🔴 **ONLINE** | Signal: **Poor** **({current_power_str})**

**Diagnostic Report:** > **{ont_name}** is currently utilizing a **{vendor}** GPON device (SN: **{serial_number}**).

**Location Details:**
- **OLT:** {olt_name}
- **Port:** {port_id}
While the status is **Online**, the current signal strength is recorded at **{power_display}**. This indicates significant optical power loss affecting the client's ONU.

**Diagnostic Context & Required Action:** > * The average port signal remains stable (**{port_avg:.2f} dBm**), suggesting an isolated physical layer issue at the client's premises. If the user experiences intermittent connectivity, please generate a support ticket for a technician visit to inspect the fiber terminations.

Thank you."""
        if target_ont.get('rstate') == 1 and is_power_poor and is_port_average_poor:
            power_display = f"{current_power:.2f} dBm" if current_power is not None else current_power_str
            loss_warning = " **PORT HIGH LOSS DETECTED**" if port_high_loss else ""
            return f"""

🟡 **ONLINE** | Signal: **Marginal**{loss_warning}

**Diagnostic Report:** > **{ont_name}** is currently utilizing a **{vendor}** GPON device (SN: **{serial_number}**).

**Location Details:**
- **OLT:** {olt_name}
- **Port:** {port_id}
While the status is **Online**, the current signal strength is recorded at **{power_display}**. This indicates significant optical power loss affecting the client's ONU.

**Diagnostic Context & Required Action:** > * Diagnostic data indicates the entire port is experiencing high optical power loss (**{port_avg:.2f} dBm** average), impacting most connected ONUs. Please verify if this port is flagged; if not, urgently alert NOC to investigate the port.

Thank you."""
        if target_ont.get('rstate') == 0:
            port_context = ""
            if port_avg is not None:
                if port_high_loss:
                    port_context = f" The average power on this port is **{port_avg:.2f} dBm (HIGH LOSS)**."
                else:
                    port_context = f" The average power on this port is **{port_avg:.2f} dBm**."
            else:
                port_context = " No port average power data available."
            return f"""

🔴 **OFFLINE**

**Diagnostic Report:** > **{ont_name}** is currently **Offline**. The **{vendor}** GPON device (SN: **{serial_number}**) is not reachable from the OLT.

**Location Details:**
- **OLT:** {olt_name}
- **Port:** {port_id}
{port_context}

**Action Item:** > The PON port is currently with a good average signal, Please investigate the cause of the outage. If the client confirms LOS light to be blinking, Kindly raise a support ticket.

Thank you."""
    return f"""🔵 **PORT STATUS** | Online Clients Present

**Diagnostic Report:** > The device was not found on this port, but the port has **{port_stats.get('online_onts', 0)}** online ONTs.

**Location Details:**
- **OLT:** {olt_name}
- **Port:** {port_id}
Port average power: **{port_avg:.2f} dBm**{" (HIGH LOSS)" if port_high_loss else ""}

**Action Item:** > The specific ONT may have moved or been reconfigured. Please verify the location.

Thank you."""

def search_selenium_olt(search_term: str):
    debug_print(f"Starting Selenium OLT search for: {search_term}", "SELENIUM")
    stats = get_selenium_database_stats()
    if stats['total'] == 0:
        debug_print("Selenium database is empty. No data available.", "WARNING")
        return None
    
    location = get_ont_location_from_selenium_db(search_term)
    if not location:
        debug_print(f"No record found in Selenium database for: {search_term}", "WARNING")
        return None
    
    olt_name = location['olt_name']
    debug_print(f"Found in Selenium database:")
    debug_print(f"   OLT: {olt_name} ({location['olt_ip']})", "SELENIUM")
    debug_print(f"   Port: {location['port_id']}", "SELENIUM")
    debug_print(f"   Name: {location['ont_name']}", "SELENIUM")
    debug_print(f"   Serial: {location['serial_number']}", "SELENIUM")
    debug_print(f"   MAC: {location['mac_address']}", "SELENIUM")
    
    olt_ip = location['olt_ip']
    olt_config = OLT_DICT.get(olt_ip)
    if not olt_config:
        debug_print(f"OLT {olt_ip} not found in configuration", "ERROR")
        return None
    
    if not check_reachability(olt_ip, 23, 3):
        debug_print(f"Selenium OLT {olt_name} ({olt_ip}) is unreachable", "SELENIUM")
        report = f"❌ {olt_name.upper()} - OLT is currently DOWN"
        return {"report": report, "port_stats": None, "target_ont": None, "olt_down": True}
    
    if update_in_progress:
        debug_print("Background update is currently running.", "WARNING")
        debug_print("Search is running in its own Chrome instance.", "INFO")
    
    debug_print(f"Launching search Chrome to get current status...", "INFO")
    temp_dir = tempfile.mkdtemp(prefix="selenium_search_")
    driver = None
    
    try:
        debug_print("Waiting for search Chrome resources...", "SELENIUM")
        if not search_chrome_semaphore.acquire(timeout=60):
            debug_print("Could not acquire search semaphore, search cancelled", "WARNING")
            return None
        
        debug_print("Launching isolated Chrome instance for search...", "SELENIUM")
        driver = create_selenium_driver(temp_dir, is_search=True)
        login_to_selenium_olt(driver, olt_ip, olt_config["username"], olt_config["password"], is_search=True)
        
        mac_entries = get_mac_table_selenium(driver, olt_ip)
        mac_lookup = create_mac_lookup_selenium(mac_entries)
        load_status_page_selenium(driver, olt_ip)
        
        port_stats = collect_port_statistics_selenium(driver, olt_ip, olt_name, location['port_id'], mac_lookup, verbose=True, is_search=True)
        
        # SAFE CHECK - Ensure port_stats is a dictionary
        if not isinstance(port_stats, dict):
            debug_print(f"Port stats returned invalid type: {type(port_stats)}", "ERROR")
            return None
        
        if port_stats.get('online_onts', 0) == 0:
            debug_print(f"Port has zero online clients", "WARNING")
            report = generate_selenium_diagnostic_report({}, port_stats, olt_name)
            return {"report": report, "port_stats": port_stats, "target_ont": None}
        
        # SAFE SEARCH for target ONT
        target_ont = None
        onts_list = port_stats.get('onts', [])
        
        if isinstance(onts_list, list):
            for ont in onts_list:
                if not isinstance(ont, dict):
                    continue
                
                ont_name = str(ont.get('ont_name', '')).lower()
                ont_sn = str(ont.get('ont_sn', '')).lower()
                ont_mac = str(ont.get('macaddr', '')).lower()
                search_lower = search_term.lower()
                
                if (search_lower in ont_name or 
                    search_lower in ont_sn or 
                    search_lower in ont_mac):
                    target_ont = ont
                    break
        
        if target_ont:
            report = generate_selenium_diagnostic_report(target_ont, port_stats, olt_name)
            debug_print("Search completed successfully", "SUCCESS")
            return {"report": report, "port_stats": port_stats, "target_ont": target_ont}
        else:
            debug_print(f"Device not found on expected port {location['port_id']}, showing port status", "WARNING")
            report = generate_selenium_diagnostic_report({}, port_stats, olt_name)
            return {"report": report, "port_stats": port_stats, "target_ont": None}
            
    except Exception as e:
        debug_print(f"Error during search: {e}", "ERROR")
        import traceback
        debug_print(f"Traceback: {traceback.format_exc()}", "ERROR")
        return None
    finally:
        if driver:
            driver.quit()
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
        search_chrome_semaphore.release()
        debug_print("Search Chrome instance closed and resources released.", "SELENIUM")

def update_single_selenium_olt(olt_ip: str, olt_config: Dict, result_queue: queue.Queue, olt_index: int, total_olts: int):
    debug_print(f"[Update Thread {olt_index+1}/{total_olts}] Starting update for {olt_config['name']} ({olt_ip})", "SELENIUM")
    if not check_reachability(olt_ip, 23, 3):
        debug_print(f"[Update Thread {olt_index+1}] OLT {olt_config['name']} unreachable, skipping", "SELENIUM")
        olt_result = {"olt_ip": olt_ip, "olt_name": olt_config["name"], "total_onts": 0, "ports": [], "error": "OLT unreachable"}
        result_queue.put(olt_result)
        return
    temp_dir = tempfile.mkdtemp(prefix=f"selenium_update_{olt_index}_")
    driver = None
    olt_result = {"olt_ip": olt_ip, "olt_name": olt_config["name"], "total_onts": 0, "ports": [], "error": None}
    try:
        debug_print(f"[Update Thread {olt_index+1}] Waiting for update Chrome resources...", "SELENIUM")
        update_chrome_semaphore.acquire()
        debug_print(f"[Update Thread {olt_index+1}] Launching update Chrome instance...", "SELENIUM")
        driver = create_selenium_driver(temp_dir, is_search=False)
        login_to_selenium_olt(driver, olt_ip, olt_config["username"], olt_config["password"], is_search=False)
        mac_entries = get_mac_table_selenium(driver, olt_ip)
        mac_lookup = create_mac_lookup_selenium(mac_entries)
        load_status_page_selenium(driver, olt_ip)
        for port in range(1, 9):
            port_stats = collect_port_statistics_selenium(driver, olt_ip, olt_config["name"], port, mac_lookup, verbose=False, is_search=False)
            olt_result["ports"].append(port_stats)
            olt_result["total_onts"] += port_stats['total_onts']
            global_update_status["progress"][olt_ip] = {"name": olt_config["name"], "port": port, "total_onts": olt_result["total_onts"], "status": f"Scanning port {port}/8"}
            DEBUG_DATA["selenium_update_status"]["progress"][olt_ip] = global_update_status["progress"][olt_ip]
            if port < 8:
                load_status_page_selenium(driver, olt_ip)
        debug_print(f"[Update Thread {olt_index+1}] ✓ Completed {olt_config['name']}: {olt_result['total_onts']} ONTs", "SELENIUM")
    except Exception as e:
        debug_print(f"[Update Thread {olt_index+1}] ❌ Error: {e}", "ERROR")
        olt_result["error"] = str(e)
    finally:
        if driver:
            driver.quit()
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
        update_chrome_semaphore.release()
        debug_print(f"[Update Thread {olt_index+1}] Update Chrome instance closed.", "SELENIUM")
    result_queue.put(olt_result)

def run_selenium_manual_update():
    global update_in_progress, global_update_status
    if update_in_progress:
        debug_print("Manual update already running, skipping", "SELENIUM")
        return
    update_in_progress = True
    start_time = datetime.now()
    global_update_status = {"running": True, "progress": {}, "total_onts": 0, "start_time": start_time, "end_time": None, "last_successful_update": global_update_status.get("last_successful_update"), "update_count": global_update_status.get("update_count", 0) + 1}
    DEBUG_DATA["selenium_update_status"] = global_update_status.copy()
    debug_print(f"MANUAL UPDATE STARTED", "SELENIUM")
    debug_print(f"Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}", "SELENIUM")
    debug_print(f"Update #{global_update_status['update_count']}", "SELENIUM")
    debug_print(f"Max concurrent Chrome instances: {MAX_CONCURRENT_CHROME}", "SELENIUM")
    result_queue = queue.Queue()
    threads = []
    olt_items = list(OLT_DICT.items())
    for idx, (olt_ip, olt_config) in enumerate(olt_items):
        thread = threading.Thread(target=update_single_selenium_olt, args=(olt_ip, olt_config, result_queue, idx, len(olt_items)))
        thread.daemon = True
        thread.start()
        threads.append(thread)
        time.sleep(3)
    for thread in threads:
        thread.join()
    all_results = {}
    total_onts = 0
    debug_print(f"COLLECTING RESULTS", "SELENIUM")
    while not result_queue.empty():
        result = result_queue.get()
        all_results[result["olt_ip"]] = result["ports"]
        total_onts += result["total_onts"]
        status = "✓" if not result["error"] else "❌"
        debug_print(f"  {status} {result['olt_name']}: {result['total_onts']} ONTs", "SELENIUM")
    final_data = {"gpon_ont_ports": all_results, "metadata": {"last_updated": datetime.now().isoformat(), "total_onts": total_onts, "olts_updated": list(OLT_DICT.keys()), "update_number": global_update_status["update_count"]}}
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(final_data, f, indent=4)
        debug_print(f"Update data saved to {OUTPUT_FILE}", "SELENIUM")
    except Exception as e:
        debug_print(f"Could not save to JSON: {e}", "WARNING")
    end_time = datetime.now()
    global_update_status["end_time"] = end_time
    global_update_status["total_onts"] = total_onts
    global_update_status["last_successful_update"] = end_time
    global_update_status["running"] = False
    DEBUG_DATA["selenium_update_status"] = global_update_status.copy()
    duration = (end_time - start_time).total_seconds()
    log_update_history_selenium(start_time, end_time, total_onts, "SUCCESS" if total_onts > 0 else "PARTIAL")
    update_in_progress = False
    debug_print(f"✅ MANUAL UPDATE COMPLETE", "SUCCESS")
    debug_print(f"   Update #{global_update_status['update_count']}", "SUCCESS")
    debug_print(f"   Total ONTs: {total_onts}", "SUCCESS")
    debug_print(f"   Duration: {duration:.2f} seconds", "SUCCESS")

def manual_selenium_update():
    if update_in_progress:
        st.warning("⚠️ Update already in progress! Please wait.")
        return
    with st.spinner("Starting manual Selenium OLT update in background..."):
        update_thread = threading.Thread(target=run_selenium_manual_update, daemon=True)
        update_thread.start()
        st.success("✅ Manual update started in background! Check console for progress.")

init_selenium_database()
if not cdata_mac_name_map_global and os.path.exists(CDATA_MAC_ADDRESS_FILE):
    with cdata_mac_lock:
        cdata_mac_name_map_global = cdata_load_mac_address_list(CDATA_MAC_ADDRESS_FILE)
    debug_print(f"Loaded {len(cdata_mac_name_map_global)} CDATA MAC mappings", "CDATA")
if get_selenium_database_stats()['total'] == 0:
    debug_print("Selenium database is empty. Please use 'Update Selenium OLTs Now' button to populate data.", "WARNING")

DIAMETER_SESSION_ID = get_phpsessid_from_env()
local_ip = get_local_ip()

st.markdown("""
<style>
.stApp {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    max-width: 800px;
    margin: 0 auto;
}
.main-title {
    font-size: 2.5rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    letter-spacing: -0.025em;
    color: #111827;
}
.version-badge {
    font-size: 0.8rem;
    color: #6b7280;
    margin-left: 0.5rem;
    font-weight: normal;
}
.search-container {
    margin: 2rem 0;
}
.stTextInput > div > div > input {
    padding: 12px 16px !important;
    font-size: 1rem !important;
    border-radius: 12px !important;
    border: 1px solid #e5e7eb !important;
    background: #f9fafb !important;
    color: #111827 !important;
    transition: all 0.2s ease;
}
.stTextInput > div > div > input:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 3px rgba(59,130,246,0.1) !important;
    background: #ffffff !important;
}
.stButton > button {
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 12px;
    padding: 12px 24px;
    font-size: 1rem;
    font-weight: 500;
    transition: all 0.2s ease;
    width: auto;
    margin: 1rem 0 2rem 0;
}
.stButton > button:hover {
    background: #2563eb;
    transform: translateY(-1px);
}
.response-box {
    background: #f9fafb;
    border-radius: 16px;
    padding: 2rem;
    margin: 1rem 0;
    border: 1px solid #f3f4f6;
    line-height: 1.6;
    color: #1f2937;
}
.multiple-onu-header {
    font-size: 1.2rem;
    font-weight: 600;
    margin-bottom: 1rem;
    color: #1f2937;
}
.onu-entry {
    background: white;
    border-radius: 8px;
    padding: 1rem;
    margin: 0.5rem 0;
    border: 1px solid #e5e7eb;
    color: #111827;
}
.selenium-entry {
    background: white;
    border-radius: 8px;
    padding: 1rem;
    margin: 0.5rem 0;
    border: 1px solid #fbbf24;
    color: #111827;
}
.cdata-entry {
    background: white;
    border-radius: 8px;
    padding: 1rem;
    margin: 0.5rem 0;
    border: 1px solid #36c9c9;
    color: #111827;
}
.olt-down-entry {
    background: #f8d7da;
    border-radius: 8px;
    padding: 1rem;
    margin: 0.5rem 0;
    border: 1px solid #f5c6cb;
    color: #721c24;
}
.port-analysis-box {
    background: #f9fafb;
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0;
    border: 1px solid #e5e7eb;
    color: #1f2937;
}
.network-analysis-box {
    background: #e8f0fe;
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0 2rem 0;
    border-left: 4px solid #3b82f6;
    color: #1f2937;
}
.network-analysis-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: #1e40af;
    margin-bottom: 1rem;
}
.radio-message-box {
    background: #fff3cd;
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0 2rem 0;
    border-left: 4px solid #ffc107;
    color: #856404;
}
.radio-message-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: #856404;
    margin-bottom: 1rem;
}
.gpon-request-box {
    background: #f0f0f0;
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0 2rem 0;
    border-left: 4px solid #8c8c8c;
    color: #262626;
}
.gpon-request-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: #262626;
    margin-bottom: 1rem;
}
@media (prefers-color-scheme: dark) {
    .stApp { background: #1e1e1e; }
    .main-title { color: #f3f4f6; }
    .onu-entry, .selenium-entry, .cdata-entry { background: #2b2b2b; color: #f3f4f6; }
    .response-box, .port-analysis-box { background: #2b2b2b; color: #f3f4f6; }
    .network-analysis-box { background: #1e2a3a; color: #f3f4f6; }
    .radio-message-box { background: #332e1c; border-left-color: #ffc107; color: #ffe58a; }
    .radio-message-title { color: #ffe58a; }
    .gpon-request-box { background: #2b2b2b; border-left-color: #8c8c8c; color: #f0f0f0; }
    .gpon-request-title { color: #f0f0f0; }
    .stTextInput > div > div > input { background: #2b2b2b !important; color: #f3f4f6 !important; border: 1px solid #4b5563 !important; }
}
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="main-title">🤖 MINITRON 🤖 <span class="version-badge">v0.007</span></h1>', unsafe_allow_html=True)

# SIDEBAR WITH AUTHENTICATION
with st.sidebar:
    if st.session_state.sidebar_locked:
        # Locked sidebar - only show authentication form
        st.markdown("### 🔒 Sidebar Locked")
        st.markdown("---")
        st.markdown("Authentication required to access system controls.")
        
        auth_password = st.text_input("Enter Password", type="password", key="sidebar_auth")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔓 Unlock", use_container_width=True):
                if authenticate_sidebar(auth_password):
                    st.success("✅ Access granted!")
                    st.rerun()
                else:
                    st.error("❌ Invalid password")
        with col2:
            if st.button("🔒 Dismiss", use_container_width=True):
                st.rerun()
        
        st.markdown("---")
        st.caption("🔐 Sidebar is locked. Enter password to access settings.")
        
    else:
        # Unlocked sidebar - show all controls
        # Add a lock button at the top to re-lock
        if st.button("🔒 Lock Sidebar", use_container_width=True):
            lock_sidebar()
            st.rerun()
        
        st.markdown("---")
        
        # ============ SYSTEM STATUS SECTION ============
        st.markdown("### 🔧 System Status")
        st.markdown("---")
        st.success("✅ SmartOLT: Replaced with CSV Lookup")
        if DIAMETER_SESSION_ID:
            st.success("✅ Diameter: Authenticated")
            st.code(f"PHPSESSID: {DIAMETER_SESSION_ID[:20]}...", language="text")
        else:
            st.warning("⚠️ Diameter: Not Authenticated")
            st.info("Run launch.bat first to authenticate")
        st.markdown("---")
        # ============ END SYSTEM STATUS ============
        
        # Your existing sidebar content continues here
        st.markdown("### 🔄 Selenium OLT Status")
        sel_stats = get_selenium_database_stats()
        if sel_stats['total'] > 0:
            st.success(f"✅ Selenium DB: {sel_stats['total']} ONTs")
            st.caption(f"🟢 Online: {sel_stats['online']} | 🔴 Offline: {sel_stats['offline']}")
            st.caption(f"🕐 Last Update: {sel_stats['last_update']}")
        else:
            st.warning("⚠️ Selenium DB: Empty. Click 'Update Selenium OLTs Now' to populate.")
        st.markdown("---")
        
        st.markdown("### 📡 CDATA OLT Status")
        cdata_count = sum(len(ports) for olt in st.session_state.cdata_monitoring_results.values() for ports in olt.values())
        if cdata_count > 0:
            st.success(f"✅ CDATA Data: {cdata_count} ONUs cached")
        else:
            st.info("ℹ️ CDATA Data: No cached data. Run monitoring.")
        
        with cdata_status_lock:
            running = cdata_monitor_status["running"]
            progress = cdata_monitor_status["progress"]
            last_run = cdata_monitor_status["last_run"]
        
        if running:
            st.info(f"🔄 CDATA Monitor: {progress}")
        elif last_run:
            st.success(f"✅ Last CDATA run: {last_run.strftime('%H:%M:%S')}")
        
        st.markdown("---")
        st.markdown("### ⚙️ Selenium Settings")
        headless_mode = st.checkbox("Run Selenium in Headless Mode (No visible windows)", value=not USE_VISIBLE_MODE)
        if headless_mode != (not USE_VISIBLE_MODE):
            USE_VISIBLE_MODE = not headless_mode
            debug_print(f"Selenium mode changed to: {'HEADLESS' if not USE_VISIBLE_MODE else 'VISIBLE'}", "SELENIUM")
            st.rerun()
        
        st.markdown("---")
        st.markdown("### 🔄 Manual Update")
        if st.button("🔄 Update Selenium OLTs Now", use_container_width=True):
            manual_selenium_update()
        
        st.markdown("---")
        if DEBUG_DATA["selenium_update_status"]["running"]:
            st.info("🔄 Manual update in progress...")
            progress = DEBUG_DATA["selenium_update_status"]["progress"]
            for olt_ip, prog in progress.items():
                st.caption(f"📍 {prog['name']}: {prog['status']}")
        elif DEBUG_DATA["selenium_update_status"]["last_successful_update"]:
            last_up = DEBUG_DATA["selenium_update_status"]["last_successful_update"]
            st.success(f"✅ Last update: {last_up.strftime('%H:%M:%S')}")
            st.caption(f"📈 Updates: {DEBUG_DATA['selenium_update_status']['update_count']}")
        
        st.markdown("---")
        st.markdown("### 📡 CDATA Monitoring")
        cdata_olt_options = list(CDATA_OLT_DEVICES.keys())
        if cdata_olt_options:
            selected_cdata_olt = st.selectbox("Select CDATA OLT", cdata_olt_options, format_func=lambda x: CDATA_OLT_DEVICES[x]["name"])
            ports_str = st.text_input("Ports (comma-separated, e.g., 1,2,3)", "1,2,3,4,5,6,7,8", label_visibility="collapsed")
            if st.button("🚀 Run CDATA Monitoring", use_container_width=True):
                with cdata_status_lock:
                    if cdata_monitor_status["running"]:
                        st.warning("CDATA monitoring already in progress.")
                    else:
                        try:
                            ports = [int(p.strip()) for p in ports_str.split(',') if p.strip()]
                        except:
                            ports = list(range(1,9))
                        thread = threading.Thread(target=run_cdata_monitoring_background, args=(selected_cdata_olt, ports), daemon=True)
                        thread.start()
                        st.success("CDATA monitoring started in background.")
                        st.rerun()
        else:
            st.warning("No CDATA OLTs configured in config.json")
        
        st.markdown("---")
        st.markdown("### 🌐 Network Access")
        st.caption(f"Local: http://localhost:8501")
        st.caption(f"LAN: http://{local_ip}:8501")
        
        st.markdown("---")
        st.markdown("### 📋 Info")
        st.caption("MINITRON v0.007")
        st.caption("Network Diagnostic Tool")
        st.caption("SmartOLT replaced with CSV lookup")

st.markdown('<div class="search-container">', unsafe_allow_html=True)

if st.session_state.get('selected_serial'):
    auto_search_term = st.session_state.selected_serial
    st.session_state.selected_serial = None
    st.session_state.search_input = auto_search_term
    st.rerun()

if 'search_input' not in st.session_state:
    st.session_state.search_input = ""

search_query = st.text_input("Search", placeholder="Enter username or serial number...", label_visibility="collapsed", key="search_input")
search_clicked = st.button("Search", use_container_width=False)
st.markdown('</div>', unsafe_allow_html=True)

if search_clicked and search_query:
    selenium_search_term = clean_search_input_for_selenium(search_query)
    csv_search_term = clean_search_input_for_smartolt(search_query)
    cdata_search_term = search_query.strip()
    print_debug_header()
    debug_print(f"Searching for: '{search_query}'", "INFO")
    
    with st.spinner("Analyzing..."):
        csv_results = search_proctor_csv(csv_search_term)
        
        if csv_results and len(csv_results) > 0:
            debug_print(f"Found {len(csv_results)} result(s) in CSV Proctor database", "SUCCESS")
            
            if len(csv_results) == 1:
                debug_print(f"*** SINGLE MATCH - PROCESSING DIRECTLY ***", "SUCCESS")
                csv_result = csv_results[0]
                smartolt_name = csv_result["smartolt_name"]
                serial_number = csv_result["serial_number"]
                olt_full = csv_result["olt_full"]
                
                onu_match = re.search(r'(\S+onu_\d+/\d+/\d+:\d+)', olt_full)
                if onu_match:
                    onu_part = onu_match.group(1)
                    olt_name_full = olt_full.replace(onu_part, "").strip()
                    
                    if "gpon-onu_" in onu_part:
                        onu_type = "gpon"
                    elif "epon-onu_" in onu_part:
                        onu_type = "epon"
                    else:
                        onu_type = "gpon"
                    
                    port_onu_part = onu_part.split("_")[1] if "_" in onu_part else onu_part
                    port_part = port_onu_part.split(":")[0] if ":" in port_onu_part else port_onu_part
                    onu_id = int(port_onu_part.split(":")[1]) if ":" in port_onu_part else 0
                    port_parts = port_part.split('/')
                    
                    if len(port_parts) >= 3:
                        board = port_parts[1]
                        port = port_parts[2]
                        olt_port = f"olt_{port_parts[0]}/{port_parts[1]}/{port_parts[2]}"
                    else:
                        board = "N/A"
                        port = "N/A"
                        olt_port = f"olt_{port_part}"
                    
                    device_name = get_device_type(serial_number)
                    olt_ip = OLT_IPS.get(olt_name_full)
                    
                    if not olt_ip:
                        olt_name_clean = re.sub(r'\s+OLT$', '', olt_name_full)
                        olt_ip = OLT_IPS.get(olt_name_clean)
                    
                    if not olt_ip:
                        st.markdown(f'<div class="onu-entry">❌ No IP mapping found for OLT "{olt_name_full}"</div>', unsafe_allow_html=True)
                        debug_print(f"❌ OLT '{olt_name_full}' not found in OLT_IPS. Available keys: {list(OLT_IPS.keys())}", "ERROR")
                    elif not check_reachability(olt_ip):
                        st.markdown(f'<div class="onu-entry">❌ {smartolt_name.upper()} - BTS or OLT {olt_name_full} is currently DOWN</div>', unsafe_allow_html=True)
                        debug_print(f"❌ OLT {olt_name_full} ({olt_ip}) is not reachable", "ERROR")
                    else:
                        st.markdown(f'<div class="onu-entry">🔍 Found in the database! Connecting to {olt_name_full} OLT...</div>', unsafe_allow_html=True)
                        debug_print(f"✅ OLT reachable. Starting telnet connection to {olt_ip}...", "SUCCESS")
                        
                        try:
                            results, client_status, avg_port_power, is_high_loss, rx_power_val, online_duration, downtime_reason, time_ago, optical_issue_message = asyncio.run(
                                connect_to_olt(olt_name_full, olt_ip, onu_type, olt_port, onu_id, smartolt_name))
                            debug_print(f"connect_to_olt returned successfully", "SUCCESS")
                        except Exception as e:
                            debug_print(f"❌ Error in connect_to_olt: {e}", "ERROR")
                            import traceback
                            debug_print(f"Traceback: {traceback.format_exc()}", "ERROR")
                            results = []
                            client_status = "error"
                            avg_port_power = 0
                            is_high_loss = False
                            rx_power_val = None
                            online_duration = "N/A"
                            downtime_reason = None
                            time_ago = None
                            optical_issue_message = ""
                        
                        print_port_statistics()
                        print_status_flags()
                        print_downtime_info()
                        
                        response = format_llm_response(smartolt_name, device_name, onu_type, serial_number,
                                                     client_status, rx_power_val, online_duration, downtime_reason,
                                                     avg_port_power, is_high_loss, olt_name_full, board, port, time_ago,
                                                     optical_issue_message)
                        st.markdown(f'<div class="onu-entry">{response}</div>', unsafe_allow_html=True)

                        # Store last search data for Access ONU button
                        st.session_state.last_device_vendor = device_name
                        st.session_state.last_onu_type = onu_type.upper()
                        st.session_state.last_board = board
                        st.session_state.last_port = port
                        st.session_state.last_olt_name = olt_name_full
                        st.session_state.last_client_status = client_status
                        st.session_state.last_onu_id = onu_id
                        st.session_state.last_smartolt_name = smartolt_name
                        
                        if client_status == "online" and rx_power_val is not None and rx_power_val >= -28 and DIAMETER_SESSION_ID:
                            diameter_data = get_diameter_user_data(smartolt_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                            if diameter_data and diameter_data.get('found', False):
                                network_analysis = format_network_analysis(diameter_data)
                                # Store CPE IP and ping status
                                st.markdown(f'<div class="network-analysis-box"><div class="network-analysis-title">🌐 Network Analysis</div>{network_analysis}</div>', unsafe_allow_html=True)
                                st.session_state.last_cpe_ip = diameter_data.get('cpe_ip', 'N/A')
                                st.session_state.last_ping_reachable = diameter_data.get('ping_reachable', False)
                                mac_addr = diameter_data.get('mac_address', 'N/A')
                                st.session_state.last_mac_vendor = get_mac_vendor(mac_addr) if mac_addr != 'N/A' else ""
                                # Only update device_vendor from Diameter if not already set by serial (CSV/OLT path)
                                if 'device_name' in dir():
                                    st.session_state.last_device_vendor = device_name
                                # else: keep the value set by CSV/OLT path (serial-based, more reliable)
                                # Store ALL Access ONU data (for ALL searches)
                                st.session_state.last_cpe_ip = diameter_data.get('cpe_ip', 'N/A')
                                st.session_state.last_ping_reachable = diameter_data.get('ping_reachable', False)
                                mac_addr = diameter_data.get('mac_address', 'N/A')
                                if mac_addr != 'N/A':
                                    st.session_state.last_mac_vendor = get_mac_vendor(mac_addr)
                                else:
                                    st.session_state.last_mac_vendor = ""
                        
                        if client_status == "offline":
                            percentages = DEBUG_DATA["port_stats"].get("percentages", {})
                            flags = DEBUG_DATA["status_flags"]
                            port_analysis = find_port_analysis_match(percentages, flags)
                            port_analysis_text = format_port_analysis(port_analysis, flags["MST"] == 1, DEBUG_DATA["mst_clients"],
                                                                      flags["JCU"] == 1, DEBUG_DATA["jcu_clients"],
                                                                      flags["JWD"] == 1, DEBUG_DATA["jwd_clients"])
                            st.markdown(f'<div class="port-analysis-box">{port_analysis_text}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="response-box">⚠️ Invalid OLT data format in CSV</div>', unsafe_allow_html=True)
                    debug_print(f"❌ Could not parse ONU part from olt_full: '{olt_full}'", "ERROR")
            
            else:
                debug_print(f"*** MULTIPLE MATCHES ({len(csv_results)}) - PROCESSING ALL ***", "INFO")
                st.markdown(f'<div class="multiple-onu-header">Found {len(csv_results)} devices - Processing all automatically</div>', unsafe_allow_html=True)

                for idx, csv_result in enumerate(csv_results):
                    smartolt_name = csv_result["smartolt_name"]
                    serial_number = csv_result["serial_number"]
                    olt_full = csv_result["olt_full"]

                    st.markdown(f'<div class="onu-entry">', unsafe_allow_html=True)
                    st.markdown(f"**Device {idx+1}/{len(csv_results)}:** {smartolt_name} (SN: {serial_number})")

                    onu_match = re.search(r'(\S+onu_\d+/\d+/\d+:\d+)', olt_full)
                    if onu_match:
                        onu_part = onu_match.group(1)
                        olt_name_full = olt_full.replace(onu_part, "").strip()

                        if "gpon-onu_" in onu_part:
                            onu_type = "gpon"
                        elif "epon-onu_" in onu_part:
                            onu_type = "epon"
                        else:
                            onu_type = "gpon"

                        port_onu_part = onu_part.split("_")[1] if "_" in onu_part else onu_part
                        port_part = port_onu_part.split(":")[0] if ":" in port_onu_part else port_onu_part
                        onu_id = int(port_onu_part.split(":")[1]) if ":" in port_onu_part else 0
                        port_parts = port_part.split('/')

                        if len(port_parts) >= 3:
                            board = port_parts[1]
                            port = port_parts[2]
                            olt_port = f"olt_{port_parts[0]}/{port_parts[1]}/{port_parts[2]}"
                        else:
                            board = "N/A"
                            port = "N/A"
                            olt_port = f"olt_{port_part}"

                        device_name = get_device_type(serial_number)
                        olt_ip = OLT_IPS.get(olt_name_full)

                        if not olt_ip:
                            olt_name_clean = re.sub(r'\s+OLT$', '', olt_name_full)
                            olt_ip = OLT_IPS.get(olt_name_clean)

                        if not olt_ip:
                            st.markdown(f'No IP mapping for OLT "{olt_name_full}"')
                        elif not check_reachability(olt_ip):
                            st.markdown(f'{smartolt_name.upper()} - OLT {olt_name_full} is DOWN')
                        else:
                            try:
                                results, client_status, avg_port_power, is_high_loss, rx_power_val, online_duration, downtime_reason, time_ago, optical_issue_message = asyncio.run(
                                    connect_to_olt(olt_name_full, olt_ip, onu_type, olt_port, onu_id, smartolt_name))

                                response = format_llm_response(smartolt_name, device_name, onu_type, serial_number,
                                                             client_status, rx_power_val, online_duration, downtime_reason,
                                                             avg_port_power, is_high_loss, olt_name_full, board, port, time_ago,
                                                             optical_issue_message)
                                st.markdown(response, unsafe_allow_html=True)

                                if client_status == "online" and rx_power_val is not None and rx_power_val >= -28 and DIAMETER_SESSION_ID:
                                    diameter_data = get_diameter_user_data(smartolt_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                                    if diameter_data and diameter_data.get('found', False):
                                        network_analysis = format_network_analysis(diameter_data)
                                        st.markdown(f'<div class="network-analysis-box"><div class="network-analysis-title">Network Analysis</div>{network_analysis}</div>', unsafe_allow_html=True)

                                if client_status == "offline":
                                    percentages = DEBUG_DATA["port_stats"].get("percentages", {})
                                    flags = DEBUG_DATA["status_flags"]
                                    port_analysis = find_port_analysis_match(percentages, flags)
                                    port_analysis_text = format_port_analysis(port_analysis, flags["MST"] == 1, DEBUG_DATA["mst_clients"],
                                                                              flags["JCU"] == 1, DEBUG_DATA["jcu_clients"],
                                                                              flags["JWD"] == 1, DEBUG_DATA["jwd_clients"])
                                    st.markdown(f'<div class="port-analysis-box">{port_analysis_text}</div>', unsafe_allow_html=True)
                            except Exception as e:
                                st.markdown(f'Error: {e}')
                    else:
                        st.markdown(f'Invalid OLT data format')

                    st.markdown(f'</div>', unsafe_allow_html=True)
                    st.markdown("---")

        
        else:
            debug_print("No CSV results found, trying Selenium OLT...", "INFO")
            
            selenium_result = search_selenium_olt(selenium_search_term)
            found_in_selenium = selenium_result is not None and selenium_result.get("report") is not None
            
            if found_in_selenium:
                if selenium_result.get("olt_down"):
                    st.markdown(f'<div class="olt-down-entry">{selenium_result["report"]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="selenium-entry">{selenium_result["report"]}</div>', unsafe_allow_html=True)
                    debug_print("Found result in Selenium OLT", "SUCCESS")
                    if selenium_result.get("target_ont"):
                        target = selenium_result["target_ont"]
                        if target.get('rstate') == 1:
                            current_power = parse_power_dbm_selenium(target.get('receive_power', 'N/A'))
                            if current_power is not None and current_power >= POOR_SIGNAL_THRESHOLD and DIAMETER_SESSION_ID:
                                ont_name = target.get('ont_name', 'N/A')
                                if ont_name != 'N/A':
                                    diameter_data = get_diameter_user_data(ont_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                                    if diameter_data and diameter_data.get('found', False):
                                        network_analysis = format_network_analysis(diameter_data)
                                        st.markdown(f'<div class="network-analysis-box"><div class="network-analysis-title">🌐 Network Analysis</div>{network_analysis}</div>', unsafe_allow_html=True)
                                # Store ALL Access ONU data (for ALL searches)
                                st.session_state.last_cpe_ip = diameter_data.get('cpe_ip', 'N/A')
                                st.session_state.last_ping_reachable = diameter_data.get('ping_reachable', False)
                                mac_addr = diameter_data.get('mac_address', 'N/A')
                                if mac_addr != 'N/A':
                                    st.session_state.last_mac_vendor = get_mac_vendor(mac_addr)
                                else:
                                    st.session_state.last_mac_vendor = ""
            else:
                matched_cdata, port_data, olt_ip, port_str, error_msg = cdata_search_and_monitor_port(cdata_search_term)
                if error_msg:
                    st.markdown(f'<div class="olt-down-entry">{error_msg}</div>', unsafe_allow_html=True)
                elif matched_cdata and port_data and olt_ip and port_str:
                    olt_name = get_cdata_olt_name_by_ip(olt_ip)
                    report = cdata_generate_diagnostic_report(matched_cdata, port_data, olt_name, int(port_str))
                    st.markdown(f'<div class="cdata-entry">{report}</div>', unsafe_allow_html=True)
                    debug_print("Found result in CDATA OLT", "SUCCESS")
                    if matched_cdata.get("Status") == "🟢":
                        signal_str = matched_cdata.get("Onu signal", "N/A")
                        signal_val = cdata_extract_signal_value(signal_str)
                        if signal_val is not None and signal_val >= POOR_SIGNAL_THRESHOLD and DIAMETER_SESSION_ID:
                            onu_name = matched_cdata.get("Name", "")
                            if onu_name:
                                diameter_data = get_diameter_user_data(onu_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                                if diameter_data and diameter_data.get('found', False):
                                    network_analysis = format_network_analysis(diameter_data)
                                    st.markdown(f'<div class="network-analysis-box"><div class="network-analysis-title">🌐 Network Analysis</div>{network_analysis}</div>', unsafe_allow_html=True)
                                # Store ALL Access ONU data (for ALL searches)
                                st.session_state.last_cpe_ip = diameter_data.get('cpe_ip', 'N/A')
                                st.session_state.last_ping_reachable = diameter_data.get('ping_reachable', False)
                                mac_addr = diameter_data.get('mac_address', 'N/A')
                                if mac_addr != 'N/A':
                                    st.session_state.last_mac_vendor = get_mac_vendor(mac_addr)
                                else:
                                    st.session_state.last_mac_vendor = ""
                else:
                    if DIAMETER_SESSION_ID:
                        diameter_data = get_diameter_user_data(csv_search_term, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                        if diameter_data and diameter_data.get('found', False):
                            radio_type = identify_radio_type(diameter_data.get('mac_address', 'N/A'))
                            if radio_type:
                                radio_message = format_radio_message(radio_type, diameter_data.get('nas_bts', 'N/A'),
                                                                   diameter_data.get('session_ip', 'N/A'),
                                                                   diameter_data.get('ping_reachable', False))
                                if radio_message:
                                    st.markdown(f'<div class="radio-message-box"><div class="radio-message-title">📡 Radio Client Detected</div>{radio_message}</div>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'<div class="gpon-request-box"><div class="gpon-request-title">🔍 GPON Serial Number Required</div>{format_gpon_request_message()}</div>', unsafe_allow_html=True)
                            network_analysis = format_network_analysis(diameter_data)
                            st.markdown(f'<div class="network-analysis-box"><div class="network-analysis-title">🌐 Network Analysis</div>{network_analysis}</div>', unsafe_allow_html=True)
                        else:
                            if diameter_data and diameter_data.get('user_not_found', False):
                                st.markdown('<div class="response-box">⚠️ This PPPoE username does not exist in the system. Please confirm the correct PPPoE username with the client.</div>', unsafe_allow_html=True)
                            elif diameter_data and diameter_data.get('login_page', False):
                                st.markdown('<div class="response-box">⚠️ Diameter session invalid. Please refresh PHPSESSID.</div>', unsafe_allow_html=True)
                            else:
                                st.markdown('<div class="response-box">⚠️ No results found in any system.</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="response-box">⚠️ No results found in any system.</div>', unsafe_allow_html=True)

# ---- ACCESS ONU BUTTON ----
# Show if: ping reachable + CPE IP available + (Huawei MAC vendor OR Huawei serial OR ZTE GPON)
# Block: ZTE EPON (not supported by Access ONU page)
mac_vendor = st.session_state.get('last_mac_vendor', '')
device_vendor = st.session_state.get('last_device_vendor', '').upper()
onu_type = st.session_state.get('last_onu_type', '').upper()

is_huawei = (mac_vendor and is_huawei_vendor(mac_vendor)) or device_vendor == 'HUAWEI'
is_zte_gpon = device_vendor == 'ZTE' and onu_type == 'GPON'

show_access = (
    st.session_state.get('last_ping_reachable', False) and 
    st.session_state.get('last_cpe_ip', 'N/A') != 'N/A' and
    (is_huawei or is_zte_gpon)
)

if show_access:
    st.markdown("---")
    if st.button("🔧 Access clients ONU/ONT", use_container_width=True):
        st.session_state.onu_access_data = {
            'device_vendor': st.session_state.get('last_device_vendor', 'N/A'),
            'cpe_ip': st.session_state.get('last_cpe_ip', 'N/A'),
            'device_type': st.session_state.get('last_onu_type', 'N/A'),
            'status': st.session_state.get('last_client_status', 'N/A'),
            'smartolt_name': st.session_state.get('last_smartolt_name', 'N/A')
        }
        st.switch_page("pages/1_Access_ONU.py")

# MAC Vendor lookup for Access ONU button
import urllib.request


# MAC Vendor lookup for Network Analysis


import atexit
@atexit.register
def cleanup():
    debug_print("Application shutdown complete", "INFO")

# PASTE THE ENTIRE SCRIPT HERE


# PASTE THE ENTIRE SCRIPT HERE



# PASTE YOUR ENTIRE FIXED radius_auth.py HERE

