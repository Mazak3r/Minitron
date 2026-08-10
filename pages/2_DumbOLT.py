#!/usr/bin/env python3
"""
DumbOLT for Cdata — EPON monitor & ONU management
Dual account access: admin (full) / noc (view + reboot)
Now includes Learned MAC addresses per ONU.
"""

import asyncio
import json
import os
import sys
import time
import re
import socket
import streamlit as st
import nest_asyncio
import threading
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ---------- LOAD CONFIG (same config.json as main app) ----------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

CDATA_OLT_DEVICES = CONFIG.get("cdata_olts", {})
CDATA_USERNAME = CONFIG.get("cdata_credentials", {}).get("username", "admin")
CDATA_PASSWORD = CONFIG.get("cdata_credentials", {}).get("password", "admin123")
SAVE_FILE = CONFIG.get("cdata_save_file", "onu_status.json")
MAC_ADDRESS_FILE = CONFIG.get("cdata_mac_file", r"C:\Users\HP\Downloads\mac_address_list.txt")

# ---------- USER ACCOUNTS (change passwords here) ----------
USERS = {
    "admin": "admin",   # full access
    "noc":   "admin"      # view + reboot only
}

nest_asyncio.apply()

st.set_page_config(
    page_title="DumbOLT for Cdata",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# ---------- Session state for authentication ----------
if "dumbolt_role" not in st.session_state:
    st.session_state.dumbolt_role = None

# ------------------- CDATA FUNCTIONS -------------------
cdata_mac_name_map_global = {}
cdata_mac_lock = threading.Lock()

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
        return mac_name_map
    except Exception as e:
        print(f"Error loading MAC list: {e}")
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
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading previous results: {e}")
    return {}

def check_reachability(ip, port=23, timeout=3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except:
        return False

async def cdata_get_full_command_output(reader, writer, command: str, max_pages: int = 10) -> str:
    full_output = ""
    cmd = command + "\r\n"
    writer.write(cmd.encode())
    await writer.drain()
    for page in range(max_pages):
        await asyncio.sleep(1)
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=2)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="ignore")
            full_output += text
            if "epon#" in text or "#" in text or ">" in text:
                break
        except asyncio.TimeoutError:
            pass
    return full_output

async def cdata_get_onu_signal(reader, writer, port: int, onu_id: str) -> str:
    try:
        command = f"show olt {port} onu {onu_id} ctc optical"
        output = await cdata_get_full_command_output(reader, writer, command)
        match = re.search(r'rx power\s+(-?\d+\.\d+)\s*d?Bm?', output, re.IGNORECASE)
        if match:
            return match.group(1) + " dBm"
        return "N/A"
    except Exception:
        return "N/A"

async def cdata_get_mac_address_table(reader, writer, port: int) -> Dict[str, List[str]]:
    """
    Fetch MAC address table - handles pagination (Press any key to continue).
    """
    onu_macs = defaultdict(list)
    try:
        command = f"show olt {port} mac-address-table\r\n"
        writer.write(command.encode())
        await writer.drain()
        
        full_output = ""
        pages_sent = 0
        
        for attempt in range(50):
            await asyncio.sleep(0.5)
            try:
                chunk = await asyncio.wait_for(reader.read(8192), timeout=2)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="ignore")
                full_output += text
                
                # Handle pagination: "Press any key to continue" or "--More--"
                if "Press any key to continue" in text or "--More--" in text:
                    pages_sent += 1
                    print(f"[MAC_TABLE] Page {pages_sent}: sending space to continue...")
                    writer.write(b" ")
                    await writer.drain()
                    await asyncio.sleep(0.5)
                    continue
                
                # Stop when we have the footer
                if "Entries Found" in text:
                    # One more quick read for trailing data
                    await asyncio.sleep(0.3)
                    try:
                        final = await asyncio.wait_for(reader.read(4096), timeout=1)
                        if final:
                            full_output += final.decode("utf-8", errors="ignore")
                    except:
                        pass
                    break
            except asyncio.TimeoutError:
                break
        
        print(f"[MAC_TABLE] Total: {len(full_output)} bytes, {pages_sent} pages sent")
        
        # Clean the output: remove "Press any key to continue (Q to quit)" lines
        # but keep the data that follows on the same or next line
        full_output = full_output.replace("Press any key to continue (Q to quit)", "")
        full_output = full_output.replace("Press any key to continue", "")
        full_output = full_output.replace("(Q to quit)", "")
        
        # Parse
        lines_parsed = 0
        for line in full_output.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Skip headers and footers
            if any(x in line for x in ['Index', 'MAC Address', '=====', 'MAC Address Table', 
                                       'Entries Found', 'SLOT', 'EVT_OAM_ALERT', 'Dying Gasp',
                                       'show olt', 'epon#']):
                continue
            
            parts = line.split()
            if len(parts) >= 4:
                # Check if parts[1] is a MAC address
                if re.match(r'[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}', parts[1]):
                    try:
                        int(parts[0])  # verify index is a number
                        mac_addr = parts[1]
                        onu_id = str(int(parts[2]))
                        onu_macs[onu_id].append(mac_addr)
                        lines_parsed += 1
                        continue
                    except (ValueError, IndexError):
                        pass
                
                # Fallback: MAC might be in a different position
                for i, part in enumerate(parts):
                    if re.match(r'[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}', part):
                        mac_addr = part
                        # ONU is typically the next part after MAC, or 2 parts after
                        if i + 1 < len(parts):
                            try:
                                onu_id = str(int(parts[i + 1]))
                                onu_macs[onu_id].append(mac_addr)
                                lines_parsed += 1
                            except ValueError:
                                pass
                        break
        
        print(f"[MAC_TABLE] Parsed {lines_parsed} entries for port {port}")
        
    except Exception as e:
        print(f"[MAC_TABLE] Error: {e}")
        import traceback
        traceback.print_exc()
    return dict(onu_macs)

def cdata_parse_online_onu(output: str, port: int, mac_name_map: Dict[str, str]) -> List[Dict]:
    onu_list = []
    lines = output.split('\n')
    for line in lines:
        line = line.strip()
        if re.match(r'^\d+\s+\d+\s+[0-9a-f:-]{10,}', line.lower()):
            parts = line.split()
            if len(parts) >= 3:
                onu_id = parts[1]
                mac = parts[2].lower().replace("-", ":")
                name = cdata_find_matching_name(mac, mac_name_map)
                onu_list.append({"onu_id": onu_id, "mac": mac, "name": name})
    return onu_list

async def cdata_monitor_olt(host: str, username: str, password: str, ports: List[int]) -> Dict[str, List[Dict]]:
    results = {}
    writer = None
    try:
        reader, writer = await asyncio.open_connection(host, 23)
        await reader.readuntil(b"Username:")
        writer.write((username + "\r\n").encode()); await writer.drain()
        await reader.readuntil(b"Password:")
        writer.write((password + "\r\n").encode()); await writer.drain()
        await asyncio.sleep(1)
        for port in ports:
            command = f"show olt online-onu {port}"
            full_output = await cdata_get_full_command_output(reader, writer, command)
            onu_list = cdata_parse_online_onu(full_output, port, st.session_state.cdatamon_mac_map)
            
            # Fetch MAC address table for this port
            mac_table = await cdata_get_mac_address_table(reader, writer, port)
            
            table_data = []
            for onu in onu_list:
                onu_id = onu["onu_id"]
                mac = onu["mac"]
                name = onu["name"]
                signal = await cdata_get_onu_signal(reader, writer, port, onu_id)
                # Try both formats: "4" and "04" and also the two-digit format
                learned_macs = mac_table.get(onu_id, [])
                if not learned_macs:
                    onu_id_zfill = str(onu_id).zfill(2)  # "4" → "04", "16" → "16"
                    learned_macs = mac_table.get(onu_id_zfill, [])
                if not learned_macs:
                    onu_id_int = str(int(onu_id))  # "04" → "4", "16" → "16"
                    learned_macs = mac_table.get(onu_id_int, [])
                print(f"[DEBUG] ONU {onu_id}: learned_macs = {learned_macs} (tried: {onu_id}, {onu_id_zfill if 'onu_id_zfill' in dir() else 'N/A'}, {onu_id_int if 'onu_id_int' in dir() else 'N/A'})")
                table_data.append({
                    "Status": "🟢",
                    "ID": onu_id,
                    "Name": name,
                    "Mac address": mac,
                    "Onu signal": signal,
                    "Learned MACs": learned_macs
                })
            results[str(port)] = table_data
        return results
    except Exception as e:
        st.error(f"Error monitoring OLT: {e}")
        return {}
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()

def cdata_search_in_saved_data(search_query: str) -> Tuple[Optional[str], Optional[str], Optional[Dict]]:
    data = cdata_load_previous_results()
    if not data:
        return None, None, None
    query_lower = search_query.lower().strip()
    query_mac_clean = re.sub(r'[:\-\s]', '', query_lower)
    query_name_clean = re.sub(r'[_\s]+', '', query_lower)
    for olt_ip, ports in data.items():
        for port, onu_list in ports.items():
            for onu in onu_list:
                onu_name = onu.get("Name", "")
                onu_mac = onu.get("Mac address", onu.get("mac", ""))
                name_norm = re.sub(r'[_\s]+', '', onu_name.lower()) if onu_name else ""
                mac_clean = re.sub(r'[:\-\s]', '', onu_mac.lower()) if onu_mac else ""
                if name_norm and query_name_clean in name_norm:
                    return olt_ip, port, onu
                if mac_clean and query_mac_clean in mac_clean:
                    return olt_ip, port, onu
    return None, None, None

# ------------------- SESSION STATE -------------------
if 'cdatamon_results' not in st.session_state:
    st.session_state.cdatamon_results = {}
if 'cdatamon_mac_map' not in st.session_state:
    st.session_state.cdatamon_mac_map = {}
if 'cdatamon_search_query' not in st.session_state:
    st.session_state.cdatamon_search_query = ""
if 'cdatamon_search_port' not in st.session_state:
    st.session_state.cdatamon_search_port = None
if 'cdatamon_search_olt_ip' not in st.session_state:
    st.session_state.cdatamon_search_olt_ip = None
if 'cdatamon_olt_choice' not in st.session_state:
    st.session_state.cdatamon_olt_choice = list(CDATA_OLT_DEVICES.keys())[0]
if 'cdatamon_reboot' not in st.session_state:
    st.session_state.cdatamon_reboot = {"active": False, "olt_ip": None, "port": None, "onu_id": None, "success": None, "message": ""}

# ------------------- HELPER FUNCTIONS -------------------
def olt_name_by_ip(ip):
    for oid, info in CDATA_OLT_DEVICES.items():
        if info.get("ip") == ip:
            return info.get("name", ip)
    return ip

def olt_id_by_ip(ip):
    for oid, info in CDATA_OLT_DEVICES.items():
        if info.get("ip") == ip:
            return oid
    return None

def load_mac_map():
    if not st.session_state.cdatamon_mac_map:
        st.session_state.cdatamon_mac_map = cdata_load_mac_address_list(MAC_ADDRESS_FILE)

def save_results(results):
    try:
        tmp = SAVE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(results, f, indent=2)
        os.replace(tmp, SAVE_FILE)
    except Exception as e:
        print(f"Error saving: {e}")

def merge_results(current_online, previous_port_data):
    curr_macs = {onu["Mac address"].lower().replace(":", "").replace("-", "") for onu in current_online}
    merged = list(current_online)
    for onu in merged:
        mac = onu.get("Mac address", "").lower().replace(":", "").replace("-", "")
        saved_name = None
        for prev in previous_port_data:
            prev_mac = prev.get("Mac address", prev.get("mac", "")).lower().replace(":", "").replace("-", "")
            if prev_mac == mac:
                saved_name = prev.get("Name", "").strip()
                if saved_name and saved_name != "Unknown":
                    break
        if saved_name:
            onu["Name"] = saved_name
        elif not onu.get("Name") or onu["Name"] == "Unknown":
            onu["Name"] = cdata_find_matching_name(onu.get("Mac address", ""), st.session_state.cdatamon_mac_map) or "Unknown"
    for prev in previous_port_data:
        prev_mac = prev.get("Mac address", prev.get("mac", "")).lower().replace(":", "").replace("-", "")
        if prev_mac not in curr_macs:
            offline = prev.copy()
            offline["Status"] = "🔴"
            if "mac" in offline:
                offline["Mac address"] = offline.pop("mac")
            if "onu_id" in offline:
                offline["ID"] = offline.pop("onu_id")
            if "Onu signal" not in offline:
                offline["Onu signal"] = "N/A"
            if "Learned MACs" not in offline:
                offline["Learned MACs"] = []
            if not offline.get("Name"):
                offline["Name"] = cdata_find_matching_name(offline.get("Mac address", ""), st.session_state.cdatamon_mac_map) or "Unknown"
            merged.append(offline)
    return merged

def resolve_online_names(online_list, olt_ip):
    prev_data = cdata_load_previous_results()
    olt_prev = prev_data.get(olt_ip, {})
    for onu in online_list:
        mac = onu.get("Mac address", "").lower().replace(":", "").replace("-", "")
        saved_name = None
        for port_str, prev_onus in olt_prev.items():
            for prev in prev_onus:
                prev_mac = prev.get("Mac address", prev.get("mac", "")).lower().replace(":", "").replace("-", "")
                if prev_mac == mac:
                    saved_name = prev.get("Name", "").strip()
                    if saved_name and saved_name != "Unknown":
                        break
            if saved_name:
                break
        if saved_name:
            onu["Name"] = saved_name
        elif not onu.get("Name") or onu["Name"] == "Unknown":
            onu["Name"] = cdata_find_matching_name(onu.get("Mac address", ""), st.session_state.cdatamon_mac_map) or "Unknown"

async def monitor_single_port(host, user, pw, port):
    current = await cdata_monitor_olt(host, user, pw, [port])
    online_list = current.get(str(port), [])
    resolve_online_names(online_list, host)
    return online_list

async def reboot_onu(host, user, pw, olt_port, onu_id):
    writer = None
    log = []
    try:
        reader, writer = await asyncio.open_connection(host, 23)
        banner = await reader.readuntil(b"Username:")
        log.append(banner.decode(errors="ignore"))
        writer.write((user + "\r\n").encode())
        await writer.drain()
        await asyncio.sleep(0.5)
        prompt = await reader.readuntil(b"Password:")
        log.append(prompt.decode(errors="ignore"))
        writer.write((pw + "\r\n").encode())
        await writer.drain()
        await asyncio.sleep(0.5)
        await reader.read(4096)
        writer.write(f"olt {olt_port}\r\n".encode())
        await writer.drain()
        await asyncio.sleep(1)
        writer.write(f"onu {onu_id}\r\n".encode())
        await writer.drain()
        await asyncio.sleep(1)
        writer.write("ctc reboot\r\n".encode())
        await writer.drain()
        await asyncio.sleep(2)
        confirmation = (await reader.read(4096)).decode(errors="ignore")
        if "please wait" in confirmation.lower() or "success" in confirmation.lower():
            success = True
            log.append("✅ Reboot command sent successfully")
        else:
            success = False
            log.append("❌ Reboot may have failed")
        writer.write(b"exit\r\nexit\r\nexit\r\n")
        await writer.drain()
        await asyncio.sleep(1)
        return success, "\n".join(log)
    except asyncio.TimeoutError:
        return False, "❌ Timeout! Device not responding."
    except Exception as e:
        return False, f"❌ Error: {e}"
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()

def execute_reboot():
    rb = st.session_state.cdatamon_reboot
    if not rb["active"]:
        return
    success, msg = asyncio.run(reboot_onu(rb["olt_ip"], CDATA_USERNAME, CDATA_PASSWORD, rb["port"], rb["onu_id"]))
    st.session_state.cdatamon_reboot = {"active": False, "olt_ip": None, "port": None, "onu_id": None, "success": success, "message": msg}
    if success:
        st.success(f"ONU {rb['onu_id']} rebooted")
    else:
        st.error(f"Reboot failed: {msg}")

def rename_onu(olt_ip, port, onu_id, new_name):
    port_str = str(port)
    data = cdata_load_previous_results()
    if olt_ip in data and port_str in data[olt_ip]:
        for onu in data[olt_ip][port_str]:
            if str(onu.get("ID", onu.get("onu_id", ""))) == str(onu_id):
                onu["Name"] = new_name
                break
        save_results(data)
    if olt_ip in st.session_state.cdatamon_results and port_str in st.session_state.cdatamon_results[olt_ip]:
        for onu in st.session_state.cdatamon_results[olt_ip][port_str]:
            if str(onu.get("ID", onu.get("onu_id", ""))) == str(onu_id):
                onu["Name"] = new_name
                break

def delete_offline_onu(olt_ip, port, onu_id, mac):
    port_str = str(port)
    data = cdata_load_previous_results()
    if olt_ip in data and port_str in data[olt_ip]:
        data[olt_ip][port_str] = [o for o in data[olt_ip][port_str] if not (
            str(o.get("ID", o.get("onu_id", ""))) == str(onu_id) and
            o.get("Status") == "🔴" and
            (o.get("Mac address", o.get("mac", "")).lower().replace(":", "").replace("-", "") == mac.lower().replace(":", "").replace("-", ""))
        )]
        save_results(data)
    if olt_ip in st.session_state.cdatamon_results and port_str in st.session_state.cdatamon_results[olt_ip]:
        st.session_state.cdatamon_results[olt_ip][port_str] = [o for o in st.session_state.cdatamon_results[olt_ip][port_str] if not (
            str(o.get("ID", o.get("onu_id", ""))) == str(onu_id) and
            o.get("Status") == "🔴" and
            (o.get("Mac address", o.get("mac", "")).lower().replace(":", "").replace("-", "") == mac.lower().replace(":", "").replace("-", ""))
        )]

# ------------------- LOGIN PAGE -------------------

def highlight_text(text, search_query):
    """Highlight the search query in yellow"""
    if not search_query or not text:
        return str(text)
    text_str = str(text)
    import re
    idx = text_str.lower().find(search_query.lower())
    if idx >= 0:
        matched = text_str[idx:idx+len(search_query)]
        return text_str[:idx] + f"<mark style='background-color: yellow;'>{matched}</mark>" + text_str[idx+len(search_query):]
    return text_str

def login_page():
    st.title("📡 DumbOLT for Cdata (FOR NOC ONLY)")
    st.subheader("Login required")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            if username in USERS and USERS[username] == password:
                st.session_state.dumbolt_role = username
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid username or password")

# ------------------- MAIN PAGE -------------------
def main_page():
    role = st.session_state.dumbolt_role
    is_admin = (role == "admin")

    col_title, col_logout = st.columns([6, 1])
    with col_logout:
        if st.button("Logout"):
            st.session_state.dumbolt_role = None
            st.rerun()

    st.title("📡 DumbOLT for Cdata")
    load_mac_map()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        st.subheader("🔧 OLT Selection")
        if st.session_state.get('_search_result_olt'):
            st.session_state.cdatamon_olt_choice = st.session_state.pop('_search_result_olt')
        
        olt_choice = st.selectbox(
            "Select OLT",
            options=list(CDATA_OLT_DEVICES.keys()),
            format_func=lambda x: CDATA_OLT_DEVICES[x]["name"],
            key="cdatamon_olt_choice"
        )

    with col2:
        st.subheader("🔍 Quick Search")
        def handle_search():
            q = st.session_state.cdatamon_search_input
            if q and q != st.session_state.cdatamon_search_query:
                st.session_state.cdatamon_search_query = q
                olt_ip, port, _ = cdata_search_in_saved_data(q)
                if olt_ip:
                    olt_id = olt_id_by_ip(olt_ip)
                    if olt_id:
                        st.session_state._search_result_olt = olt_id
                        st.session_state._search_result_ip = olt_ip
                        st.session_state._search_result_port = port
                        st.session_state._do_search_scan = True
        
        search_query = st.text_input(
            "MAC address or Name",
            value=st.session_state.cdatamon_search_query,
            placeholder="e.g. aa:bb:cc:dd:ee:ff",
            key="cdatamon_search_input",
            on_change=handle_search
        )

    # Run search scan if pending
    if st.session_state.get('_do_search_scan'):
        st.session_state._do_search_scan = False
        olt_ip = st.session_state.get('_search_result_ip')
        port = st.session_state.get('_search_result_port')
        if olt_ip and port:
            with st.spinner(f"Scanning {olt_name_by_ip(olt_ip)} Port {port}..."):
                online = asyncio.run(monitor_single_port(olt_ip, CDATA_USERNAME, CDATA_PASSWORD, int(port)))
                prev_data = cdata_load_previous_results()
                prev_port = prev_data.get(olt_ip, {}).get(str(port), [])
                merged = merge_results(online, prev_port)
                if olt_ip not in st.session_state.cdatamon_results:
                    st.session_state.cdatamon_results[olt_ip] = {}
                st.session_state.cdatamon_results[olt_ip][str(port)] = merged
                if olt_ip not in prev_data:
                    prev_data[olt_ip] = {}
                prev_data[olt_ip][str(port)] = merged
                save_results(prev_data)
            st.success(f"Scan complete!")
            st.rerun()

    with col3:
        st.subheader("📋 MAC List")
        if st.button("Reload MAC List"):
            st.session_state.cdatamon_mac_map = {}
            load_mac_map()
            st.success(f"Loaded {len(st.session_state.cdatamon_mac_map)} entries")
        st.caption(f"Entries: {len(st.session_state.cdatamon_mac_map)}")

    st.subheader("Select the port")
    ports_cols = st.columns(8)
    selected_ports = []
    for i in range(8):
        if ports_cols[i].checkbox(f"{i+1}", key=f"port_{i+1}"):
            selected_ports.append(i+1)

    if st.button("Run Monitoring", type="primary"):
        olt = CDATA_OLT_DEVICES[olt_choice]
        ports = selected_ports if selected_ports else list(range(1, 9))
        with st.spinner(f"Monitoring {olt['name']} …"):
            current_all = asyncio.run(cdata_monitor_olt(olt["ip"], CDATA_USERNAME, CDATA_PASSWORD, ports))
            prev_data = cdata_load_previous_results()
            olt_prev = prev_data.get(olt["ip"], {})
            final = {}
            for port in ports:
                port_str = str(port)
                online_list = current_all.get(port_str, [])
                resolve_online_names(online_list, olt["ip"])
                prev_port = olt_prev.get(port_str, [])
                merged = merge_results(online_list, prev_port)
                final[port_str] = merged
            st.session_state.cdatamon_results[olt["ip"]] = final
            if olt["ip"] not in prev_data:
                prev_data[olt["ip"]] = {}
            prev_data[olt["ip"]].update(final)
            save_results(prev_data)
            st.success("Monitoring complete!")
            st.rerun()

    if search_query and search_query != st.session_state.cdatamon_search_query:
        st.session_state.cdatamon_search_query = search_query
        olt_ip, port, _ = cdata_search_in_saved_data(search_query)
        if olt_ip:
            st.session_state.cdatamon_search_olt_ip = olt_ip
            st.session_state.cdatamon_search_port = port
            olt_id = olt_id_by_ip(olt_ip)
            if olt_id:
                st.session_state.cdatamon_olt_choice = olt_id
            st.info(f"Found: {olt_name_by_ip(olt_ip)} Port {port}. Running live scan…")
            st.rerun()
        else:
            st.warning("Not found in saved data.")



    results = st.session_state.cdatamon_results
    if results:
        olt = CDATA_OLT_DEVICES[olt_choice]
        olt_ip = olt["ip"]
        if olt_ip in results:
            st.markdown("---")
            # If searching, show only matching port
            search_q = st.session_state.get('cdatamon_search_query', '')
            if search_q:
                # Find which port has the matching ONU
                matching_port = None
                for p in results[olt_ip]:
                    for onu in results[olt_ip][p]:
                        name_match = search_q.lower().replace('_','').replace(' ','') in onu.get('Name','').lower().replace('_','').replace(' ','')
                        mac_match = search_q.lower().replace(':','').replace('-','') in onu.get('Mac address','').lower().replace(':','').replace('-','')
                        if name_match or mac_match:
                            matching_port = p
                            break
                    if matching_port:
                        break
                
                if matching_port:
                    st.subheader(f"📊 {olt['name']} Results - Port {matching_port}")
                    port_data = results[olt_ip][matching_port]
                    if port_data:
                        with st.expander(f"Port {matching_port} ({len(port_data)} ONUs)", expanded=True):
                            # ... display code continues below, we just changed the header
                            pass
                    # Skip the normal loop - we handle it differently
                    # Replace the for loop with just the matching port
            else:
                st.subheader(f"📊 {olt['name']} Results")
            
            # Determine which ports to show
            ports_to_show = {}
            if search_q:
                for p in results[olt_ip]:
                    for onu in results[olt_ip][p]:
                        name_match = search_q.lower().replace('_','').replace(' ','') in onu.get('Name','').lower().replace('_','').replace(' ','')
                        mac_match = search_q.lower().replace(':','').replace('-','') in onu.get('Mac address','').lower().replace(':','').replace('-','')
                        if name_match or mac_match:
                            ports_to_show[p] = results[olt_ip][p]
                            break
            else:
                ports_to_show = results[olt_ip]
            
            for port_str in sorted(ports_to_show.keys(), key=lambda x: int(x)):
                port_data = ports_to_show[port_str]
                if not port_data:
                    continue
                with st.expander(f"Port {port_str} ({len(port_data)} ONUs)", expanded=True):
                    if is_admin:
                        hc = st.columns([0.5, 0.5, 1.5, 2.0, 0.8, 1.8, 1.0, 0.7])
                        headers = ["Status", "ID", "Name", "MAC", "Signal", "Learned MACs", "Rename", "Action"]
                    else:
                        hc = st.columns([0.5, 0.5, 1.5, 2.0, 0.8, 1.8, 0.7])
                        headers = ["Status", "ID", "Name", "MAC", "Signal", "Learned MACs", "Action"]
                    for i, h in enumerate(headers):
                        hc[i].write(f"**{h}**")

                    for onu in port_data:
                        onu_id = str(onu.get("ID", onu.get("onu_id", "N/A")))
                        mac = onu.get("Mac address", onu.get("mac", "N/A"))
                        name = onu.get("Name", "Unknown")
                        status = onu.get("Status", "⏳")
                        signal = onu.get("Onu signal", "N/A")
                        learned = onu.get("Learned MACs", [])
                        learned_str = ", ".join(learned) if learned else "None"

                        if is_admin:
                            cols = st.columns([0.5, 0.5, 1.5, 2.0, 0.8, 1.8, 1.0, 0.7])
                            cols[0].write(status)
                            cols[1].write(onu_id)
                            name_html = highlight_text(name, st.session_state.cdatamon_search_query)
                            cols[2].markdown(name_html, unsafe_allow_html=True)
                            mac_html = highlight_text(mac, st.session_state.cdatamon_search_query)
                            cols[3].markdown(mac_html, unsafe_allow_html=True)
                            cols[4].write(signal)
                            cols[5].write(learned_str)
                            new_name = cols[6].text_input("New name", value=name, key=f"rename_{olt_ip}_{port_str}_{onu_id}", label_visibility="collapsed")
                            if new_name and new_name != name:
                                if cols[6].button("💾 Save", key=f"save_rename_{olt_ip}_{port_str}_{onu_id}"):
                                    rename_onu(olt_ip, port_str, onu_id, new_name)
                                    st.rerun()
                            if status == "🟢":
                                if cols[7].button("🔄 Reboot", key=f"reboot_{olt_ip}_{port_str}_{onu_id}"):
                                    st.session_state.cdatamon_reboot = {
                                        "active": True, "olt_ip": olt_ip, "port": int(port_str),
                                        "onu_id": onu_id, "success": None, "message": ""
                                    }
                                    st.rerun()
                            elif status == "🔴":
                                if cols[7].button("🗑️ Delete", key=f"delete_{olt_ip}_{port_str}_{onu_id}"):
                                    delete_offline_onu(olt_ip, int(port_str), onu_id, mac)
                                    st.rerun()
                        else:
                            cols = st.columns([0.5, 0.5, 1.5, 2.0, 0.8, 1.8, 0.7])
                            cols[0].write(status)
                            cols[1].write(onu_id)
                            name_html = highlight_text(name, st.session_state.cdatamon_search_query)
                            cols[2].markdown(name_html, unsafe_allow_html=True)
                            mac_html = highlight_text(mac, st.session_state.cdatamon_search_query)
                            cols[3].markdown(mac_html, unsafe_allow_html=True)
                            cols[4].write(signal)
                            cols[5].write(learned_str)
                            if status == "🟢":
                                if cols[6].button("🔄 Reboot", key=f"reboot_{olt_ip}_{port_str}_{onu_id}"):
                                    st.session_state.cdatamon_reboot = {
                                        "active": True, "olt_ip": olt_ip, "port": int(port_str),
                                        "onu_id": onu_id, "success": None, "message": ""
                                    }
                                    st.rerun()
    else:
        st.info("No results yet. Select an OLT and run monitoring.")

    reboot_state = st.session_state.cdatamon_reboot
    if reboot_state["active"]:
        st.warning(f"Rebooting ONU {reboot_state['onu_id']} on port {reboot_state['port']}...")
        execute_reboot()
        st.rerun()
    elif reboot_state["success"] is not None:
        if reboot_state["success"]:
            st.success(f"ONU {reboot_state['onu_id']} rebooted successfully!")
        else:
            st.error(f"Reboot failed: {reboot_state['message']}")
        if st.button("Continue"):
            st.session_state.cdatamon_reboot = {"active": False, "olt_ip": None, "port": None, "onu_id": None, "success": None, "message": ""}
            st.rerun()

# ------------------- PAGE ROUTING -------------------
if st.session_state.dumbolt_role is None:
    login_page()
else:
    main_page()
