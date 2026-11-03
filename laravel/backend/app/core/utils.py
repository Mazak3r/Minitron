"""
Pure utility functions — Multi-IP fallback, Memory, Health Check, CSV lookups.
"""
import ast
import re
import socket
import subprocess
import tempfile
import os
import platform
from datetime import datetime
from typing import Optional, Dict, List

import pandas as pd

from backend.app.config import (
    HEALTH_CHECK, PROCTOR_CSV_PATH, KYLIAN_CSV_PATH,
)
from backend.app.core.logger import debug_print


# ========== Network Routing ==========

def check_reachability(ip, port=23, timeout=3):
    """Try multiple IPs (comma-separated). First reachable wins."""
    for addr in str(ip).split(","):
        addr = addr.strip()
        try:
            host, p = addr, port
            if ":" in addr and addr.count(":") <= 2:
                host, port_str = addr.rsplit(":", 1)
                p = int(port_str)
            with socket.create_connection((host, p), timeout=timeout):
                return True
        except Exception:
            continue
    return False


def ping_ip(ip, timeout=3, extended_timeout=False):
    if ip == "N/A" or not ip:
        return False
    ip = ip.strip()
    try:
        socket.inet_aton(ip)
    except socket.error:
        return False
    ping_timeout = 10 if extended_timeout else timeout
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as temp_file:
            temp_path = temp_file.name
        if platform.system().lower() == "windows":
            count = 4 if extended_timeout else 2
            command = ["ping", "-n", str(count), "-w", str(ping_timeout * 1000), ip]
        else:
            count = 4 if extended_timeout else 2
            command = ["ping", "-c", str(count), "-W", str(ping_timeout), ip]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=ping_timeout + 2)
        output = result.stdout.lower()
        failure_indicators = ["ttl expired in transit", "destination host unreachable",
                              "request timed out", "100% packet loss", "unreachable"]
        for ind in failure_indicators:
            if ind in output:
                return False
        success_indicators = [f"reply from {ip}", f"{ip} : bytes=",
                              f"64 bytes from {ip}", f"from {ip}: icmp_seq="]
        for ind in success_indicators:
            if ind in output:
                return True
        if result.returncode == 0 and not any(i in output for i in failure_indicators):
            return True
        return False
    except (subprocess.TimeoutExpired, Exception):
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


# ========== System Health ==========

def get_memory_usage():
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
        total_match = re.search(r"MemTotal:\s+(\d+)", meminfo)
        available_match = re.search(r"MemAvailable:\s+(\d+)", meminfo)
        if total_match and available_match:
            total_kb = int(total_match.group(1))
            available_kb = int(available_match.group(1))
            used_kb = total_kb - available_kb
            percentage = (used_kb / total_kb) * 100
            return percentage, used_kb // 1024, total_kb // 1024
    except Exception:
        pass
    return 0, 0, 0


def check_connection_health():
    """Check which connection methods are available (no NOC)."""
    results = {"ssh_tunnel": False, "direct_ping": False}
    test_tunnel_ip = HEALTH_CHECK.get("tunnel_test", "127.0.0.1:2323")
    host, port = test_tunnel_ip, 23
    if ":" in test_tunnel_ip:
        host, port_str = test_tunnel_ip.rsplit(":", 1)
        port = int(port_str)
    results["ssh_tunnel"] = check_reachability(host, port, timeout=2)
    test_ping_ip = HEALTH_CHECK.get("ping_test", "192.168.44.1")
    results["direct_ping"] = ping_ip(test_ping_ip, timeout=2)
    return results


# ========== Misc Utilities ==========

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
        if olt_name.strip().startswith("{") and olt_name.strip().endswith("}"):
            try:
                parsed = ast.literal_eval(olt_name)
                if isinstance(parsed, dict) and "name" in parsed:
                    return str(parsed["name"])
                return str(parsed)
            except (ValueError, SyntaxError, Exception):
                match = re.search(r"'name':\s*'([^']+)'", olt_name)
                if match:
                    return match.group(1)
                return olt_name
        return olt_name
    return str(olt_name)


def format_online_duration(duration_str):
    if not duration_str or duration_str == "N/A":
        return None
    years = months = days = hours = minutes = seconds = 0
    try:
        if "y" in duration_str.lower():
            m = re.search(r"(\d+)\s*y", duration_str, re.IGNORECASE)
            if m: years = int(m.group(1))
        if "month" in duration_str.lower():
            m = re.search(r"(\d+)\s*month", duration_str, re.IGNORECASE)
            if m: months = int(m.group(1))
        if "d" in duration_str.lower():
            m = re.search(r"(\d+)\s*d", duration_str, re.IGNORECASE)
            if m: days = int(m.group(1))
        if "h" in duration_str.lower():
            m = re.search(r"(\d+)\s*h", duration_str, re.IGNORECASE)
            if m: hours = int(m.group(1))
        m = re.search(r"(\d+)\s*m(?!o)", duration_str, re.IGNORECASE)
        if m: minutes = int(m.group(1))
        if "s" in duration_str.lower():
            m = re.search(r"(\d+)\s*s", duration_str, re.IGNORECASE)
            if m: seconds = int(m.group(1))
        return {"years": years, "months": months, "days": days,
                "hours": hours, "minutes": minutes, "seconds": seconds}
    except Exception:
        return None


def calculate_uptime_from_duration(duration_str):
    if not duration_str or duration_str == "N/A":
        return None
    try:
        total_minutes = 0
        m = re.search(r"(\d+)\s*d", duration_str, re.IGNORECASE)
        if m: total_minutes += int(m.group(1)) * 24 * 60
        m = re.search(r"(\d+)\s*h", duration_str, re.IGNORECASE)
        if m: total_minutes += int(m.group(1)) * 60
        m = re.search(r"(\d+)\s*m", duration_str, re.IGNORECASE)
        if m: total_minutes += int(m.group(1))
        return total_minutes
    except Exception:
        return None


def get_device_type(serial_number):
    if not serial_number or serial_number == "N/A":
        return "Unknown"
    s = serial_number.upper()
    if s.startswith(("ZTE", "RTEGC", "F4E4", "B4DE", "F4B8", "ZXI", "DC71")):
        return "ZTE"
    elif s.startswith("E0"):
        return "Cdata"
    elif s.startswith(("HWTC", "C4B8", "208C", "002E", "0011")):
        return "Huawei"
    return "Unknown"


def round_percentages_to_10(data):
    total = sum(data.values())
    if total == 0:
        return {k: 0 for k in data}
    real = {k: (v / total) * 100 for k, v in data.items()}
    rounded, diffs = {}, {}
    for k, v in real.items():
        rv = round(v / 10) * 10
        rounded[k] = rv
        diffs[k] = v - rv
    remainder = 100 - sum(rounded.values())
    if remainder != 0:
        adj = 10 if remainder > 0 else -10
        steps = abs(remainder) // 10
        cands = sorted(diffs.items(), key=lambda x: x[1], reverse=(remainder > 0))
        for i in range(min(steps, len(cands))):
            rounded[cands[i][0]] += adj
    return rounded


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
    return "just now"


def calculate_time_offset(olt_time):
    return datetime.now() - olt_time


def parse_olt_time(raw_output):
    match = re.search(r"(\d{2}:\d{2}:\d{2})\s+\w+\s+(\w+)\s+(\d{1,2})\s+(\d{4})", raw_output)
    if not match:
        return datetime.now()
    time_part, month_str, day, year = match.groups()
    month_map = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                 "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    month = month_map.get(month_str)
    if not month:
        return datetime.now()
    return datetime.strptime(f"{year}-{month:02d}-{int(day):02d} {time_part}", "%Y-%m-%d %H:%M:%S")


def is_account_expired(expiry_date):
    if not expiry_date or expiry_date == "N/A":
        return False
    try:
        expiry_dt = datetime.strptime(expiry_date.split()[0], "%Y-%m-%d")
        return expiry_dt < datetime.now()
    except Exception:
        return False


def clean_search_input_for_smartolt(search_text):
    if not search_text:
        return ""
    return " ".join(search_text.replace("_", " ").split()).strip()


def clean_search_input_for_selenium(search_text):
    return (search_text or "").strip()


# ========== CSV Lookups ==========

def search_proctor_csv(search_term: str) -> List[Dict]:
    if not os.path.exists(PROCTOR_CSV_PATH):
        debug_print(f"Proctor CSV not found: {PROCTOR_CSV_PATH}", "ERROR")
        return []
    try:
        df = pd.read_csv(PROCTOR_CSV_PATH)
        original = search_term.strip()
        variations = [original.lower()]
        if " " in original:
            variations.append(original.replace(" ", "_").lower())
        if "_" in original:
            variations.append(original.replace("_", " ").lower())
        variations = list(dict.fromkeys(variations))
        debug_print(f"CSV searching for variations: {variations}", "CSV")

        matches = []
        for idx, row in df.iterrows():
            sn = str(row.get("SN", "")).strip().lower() if pd.notna(row.get("SN")) else ""
            name = str(row.get("Name", "")).strip().lower() if pd.notna(row.get("Name")) else ""
            for sv in variations:
                if sv == sn or sv == name or (sv in name and len(sv) > 3):
                    pon_type = str(row.get("PON Type", "gpon")).strip().lower()
                    olt_full = f"{row.get('OLT')} {pon_type}-onu_1/{row.get('Board')}/{row.get('Port')}:{row.get('Allocated ONU')}"
                    matches.append({
                        "smartolt_name": str(row.get("Name")).strip(),
                        "serial_number": str(row.get("SN")).strip(),
                        "olt_full": olt_full,
                        "row_index": idx + 1,
                    })
                    break
        return matches
    except Exception as e:
        debug_print(f"Error reading Proctor CSV: {e}", "ERROR")
        return []


def search_kylian_csv(search_term: str) -> List[Dict]:
    if not os.path.exists(KYLIAN_CSV_PATH):
        return []
    try:
        df = pd.read_csv(KYLIAN_CSV_PATH)
        original = search_term.strip()
        variations = [original.lower()]
        if " " in original:
            variations.append(original.replace(" ", "_").lower())
        if "_" in original:
            variations.append(original.replace("_", " ").lower())
        variations = list(dict.fromkeys(variations))

        matches = []
        for idx, row in df.iterrows():
            sn = str(row.get("SN", "")).strip().lower() if pd.notna(row.get("SN")) else ""
            name = str(row.get("Name", "")).strip().lower() if pd.notna(row.get("Name")) else ""
            for sv in variations:
                if sv == sn or sv == name or (sv in name and len(sv) > 3):
                    pon_type = str(row.get("PON Type", "gpon")).strip().lower()
                    olt_full = f"{row.get('OLT')} {pon_type}-onu_1/{row.get('Board')}/{row.get('Port')}:{row.get('Allocated ONU')}"
                    matches.append({
                        "smartolt_name": str(row.get("Name")).strip(),
                        "serial_number": str(row.get("SN")).strip(),
                        "olt_full": olt_full,
                        "row_index": idx + 1,
                    })
                    break
        return matches
    except Exception as e:
        debug_print(f"Error reading Kylian CSV: {e}", "ERROR")
        return []
