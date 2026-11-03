"""
CDATA EPON telnet monitoring.
"""
import asyncio
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from backend.app import state
from backend.app.config import (
    CDATA_OLT_DEVICES, CDATA_SAVE_FILE, CDATA_MAC_ADDRESS_FILE,
    CDATA_USERNAME, CDATA_PASSWORD,
)
from backend.app.core.logger import debug_print
from backend.app.core.utils import check_reachability


def cdata_load_mac_address_list(file_path: str) -> Dict[str, str]:
    mac_map = {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        for line in content.split("\n"):
            match = re.search(
                r"^\s*\d+\.\s+([a-zA-Z_]+)\s*-?\s*([0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2}[:-][0-9A-F]{2})",
                line.strip(), re.IGNORECASE,
            )
            if match:
                name = match.group(1).strip()
                mac = match.group(2).strip().lower().replace(":", "").replace("-", "")
                mac_map[mac] = name
        return mac_map
    except Exception:
        return {}


def cdata_find_matching_name(mac_address: str, mac_map: Dict[str, str]) -> str:
    if not mac_address or not mac_map:
        return ""
    clean = mac_address.lower().replace(":", "").replace("-", "")
    if clean in mac_map: return mac_map[clean]
    if len(clean) == 12:
        partial = clean[:11]
        for stored, name in mac_map.items():
            if stored.startswith(partial) and len(stored) == 12: return name
    elif len(clean) == 11:
        for stored, name in mac_map.items():
            if stored.startswith(clean) and len(stored) == 12: return name
    return ""


def cdata_load_previous_results() -> Dict:
    try:
        if os.path.exists(CDATA_SAVE_FILE):
            with open(CDATA_SAVE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def cdata_search_in_saved_data(search_query: str):
    data = cdata_load_previous_results()
    if not data:
        return None, None, None
    query_lower = search_query.strip().lower()
    query_norm = re.sub(r"[_\s]+", "", query_lower)
    query_mac = re.sub(r"[:\-\s]", "", query_lower)
    
    for olt_ip, ports in data.items():
        for port, onus in ports.items():
            for onu in onus:
                name = onu.get("Name", "")
                mac = onu.get("Mac address", onu.get("mac", ""))
                name_n = re.sub(r"[_\s]+", "", name.lower()) if name else ""
                mac_c = re.sub(r"[:\-\s]", "", mac.lower()) if mac else ""
                
                if name_n and query_norm in name_n: return olt_ip, port, onu
                if mac_c and query_mac:
                    if query_mac in mac_c: return olt_ip, port, onu
                    if mac_c.startswith(query_mac) and len(mac_c) - len(query_mac) <= 2: return olt_ip, port, onu
    return None, None, None


def get_cdata_olt_name_by_ip(ip: str) -> str:
    for _, olt in CDATA_OLT_DEVICES.items():
        if olt.get("ip") == ip: return olt.get("name", ip)
    return ip


async def cdata_get_full_command_output(reader, writer, command: str, max_pages: int = 10) -> str:
    out = ""
    writer.write((command + "\r\n").encode())
    await writer.drain()
    for _ in range(max_pages):
        await asyncio.sleep(1)
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=2)
            if not chunk: break
            txt = chunk.decode("utf-8", errors="ignore")
            out += txt
            if "epon#" in txt or "#" in txt or ">" in txt: break
        except asyncio.TimeoutError: pass
    return out


async def cdata_get_onu_signal(reader, writer, port, onu_id) -> str:
    try:
        out = await cdata_get_full_command_output(reader, writer, f"show olt {port} onu {onu_id} ctc optical")
        m = re.search(r"rx power\s+(-?\d+\.\d+)\s*d?Bm?", out, re.IGNORECASE)
        if m: return m.group(1) + " dBm"
        return "N/A"
    except Exception:
        return "N/A"


def cdata_parse_online_onu(output: str, port: int) -> List[Dict]:
    onus = []
    for line in output.split("\n"):
        line = line.strip()
        if re.match(r"^\d+\s+\d+\s+[0-9a-f:-]{10,}", line.lower()):
            parts = line.split()
            if len(parts) >= 3:
                onu_id = parts[1]
                mac = parts[2].lower().replace("-", ":")
                with state.cdata_mac_lock:
                    name = cdata_find_matching_name(mac, state.cdata_mac_name_map_global)
                onus.append({"onu_id": onu_id, "mac": mac, "name": name})
    return onus


async def cdata_monitor_olt(host, username, password, ports):
    results = {}
    writer = None
    try:
        for addr in str(host).split(","):
            addr = addr.strip()
            try:
                h, p = addr, 23
                if ":" in addr and addr.count(":") <= 2:
                    h, p_str = addr.rsplit(":", 1)
                    p = int(p_str)
                reader, writer = await asyncio.open_connection(h, p)
                break
            except Exception:
                continue
        if not writer:
            return {}
            
        await reader.readuntil(b"Username:")
        writer.write((username + "\r\n").encode()); await writer.drain()
        await reader.readuntil(b"Password:")
        writer.write((password + "\r\n").encode()); await writer.drain()
        await asyncio.sleep(1)
        await reader.read(1024)

        for port in ports:
            out = await cdata_get_full_command_output(reader, writer, f"show olt online-onu {port}")
            onus = cdata_parse_online_onu(out, port)
            table = []
            for onu in onus:
                signal = await cdata_get_onu_signal(reader, writer, port, onu["onu_id"])
                table.append({"Status": "🟢", "ID": onu["onu_id"], "Name": onu["name"], "Mac address": onu["mac"], "Onu signal": signal})
            results[str(port)] = table
        return results
    except Exception:
        return {}
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


def cdata_run_monitoring(olt_id: str, ports: Optional[List[int]] = None):
    if olt_id not in CDATA_OLT_DEVICES:
        raise ValueError(f"Invalid OLT ID: {olt_id}")
    olt = CDATA_OLT_DEVICES[olt_id]
    if ports is None: ports = list(range(1, 9))
    if not check_reachability(olt["ip"], 23, 3): return {}

    current = _run_async(cdata_monitor_olt(olt["ip"], CDATA_USERNAME, CDATA_PASSWORD, ports))
    if not current: return {}

    prev_data = cdata_load_previous_results()
    olt_prev = prev_data.get(olt["ip"], {})
    final = {}
    for port in ports:
        p_str = str(port)
        curr_list = current.get(p_str, [])
        prev_list = olt_prev.get(p_str, [])
        curr_macs = {o["Mac address"] for o in curr_list}
        merged = list(curr_list)
        for p_onu in prev_list:
            mac = p_onu.get("Mac address", p_onu.get("mac", ""))
            if mac not in curr_macs:
                off = p_onu.copy()
                off["Status"] = "🔴"
                if "mac" in off: off["Mac address"] = off.pop("mac")
                if "onu_id" in off: off["ID"] = off.pop("onu_id")
                if "Onu signal" not in off: off["Onu signal"] = "N/A"
                merged.append(off)
        final[p_str] = merged
    state.cdata_monitoring_results[olt["ip"]] = final
    return final


def cdata_search_and_monitor_port(query: str):
    olt_ip, port_str, saved_onu = cdata_search_in_saved_data(query)
    if not olt_ip: return None, None, None, None, None
    if not check_reachability(olt_ip, 23, 3):
        return None, None, olt_ip, port_str, f"❌ {get_cdata_olt_name_by_ip(olt_ip).upper()} - OLT is currently DOWN"

    port = int(port_str)
    current = _run_async(cdata_monitor_olt(olt_ip, CDATA_USERNAME, CDATA_PASSWORD, [port]))
    curr_list = current.get(str(port), [])
    
    prev_data = cdata_load_previous_results()
    prev_list = prev_data.get(olt_ip, {}).get(str(port), [])
    curr_macs = {o["Mac address"] for o in curr_list}
    final = list(curr_list)
    for p_onu in prev_list:
        mac = p_onu.get("Mac address", p_onu.get("mac", ""))
        if mac not in curr_macs:
            off = p_onu.copy()
            off["Status"] = "🔴"
            if "mac" in off: off["Mac address"] = off.pop("mac")
            if "onu_id" in off: off["ID"] = off.pop("onu_id")
            if "Onu signal" not in off: off["Onu signal"] = "N/A"
            final.append(off)

    existing = cdata_load_previous_results()
    if olt_ip not in existing: existing[olt_ip] = {}
    existing[olt_ip][str(port)] = final
    state.cdata_monitoring_results[olt_ip] = existing[olt_ip]

    matched = None
    query_lower = query.lower()
    q_mac = re.sub(r"[:\-\s]", "", query_lower)
    for onu in curr_list:
        mac = onu.get("Mac address", "").lower().replace(":", "").replace("-", "")
        name_n = re.sub(r"[_\s]+", "", onu.get("Name", "").lower())
        if mac.startswith(q_mac) or q_mac in mac or query_lower in name_n:
            matched = onu; break
    if not matched:
        for onu in final:
            if onu.get("Status") == "🔴":
                mac = onu.get("Mac address", "").lower().replace(":", "").replace("-", "")
                name_n = re.sub(r"[_\s]+", "", onu.get("Name", "").lower())
                if mac.startswith(q_mac) or q_mac in mac or query_lower in name_n:
                    matched = onu; break
    if not matched: matched = saved_onu
    return matched, final, olt_ip, port_str, None


def run_cdata_monitoring_background(olt_id: str, ports: List[int]):
    with state.cdata_status_lock:
        state.cdata_monitor_status["running"] = True
        state.cdata_monitor_status["progress"] = f"Monitoring {olt_id}..."
    try:
        res = cdata_run_monitoring(olt_id, ports)
        with state.cdata_status_lock:
            state.cdata_monitor_status["last_run"] = datetime.now()
            state.cdata_monitor_status["progress"] = "Completed" if res else "OLT unreachable or no data"
    except Exception as e:
        with state.cdata_status_lock:
            state.cdata_monitor_status["progress"] = f"Error: {e}"
    finally:
        with state.cdata_status_lock:
            state.cdata_monitor_status["running"] = False


def init_cdata_mac_map():
    import os as _os
    from backend.app import state as _state
    from backend.app.config import CDATA_MAC_ADDRESS_FILE as _FILE
    if not _state.cdata_mac_name_map_global and _os.path.exists(_FILE):
        with _state.cdata_mac_lock:
            _state.cdata_mac_name_map_global = cdata_load_mac_address_list(_FILE)


def cdata_extract_signal_value(signal_str: str):
    """Extract numeric dBm value from a signal string like '-22.5 dBm'."""
    if not signal_str or signal_str == "N/A":
        return None
    match = re.search(r"(-?\d+\.?\d*)", signal_str)
    return float(match.group(1)) if match else None


def cdata_generate_diagnostic_report(matched_onu, port_data, olt_name, port):
    """Generate markdown diagnostic report for a CDATA EPON ONU."""
    onu_status = matched_onu.get("Status", "🔴")
    onu_name = matched_onu.get("Name", "Unknown")
    onu_mac = matched_onu.get("Mac address", matched_onu.get("mac", "N/A"))
    signal_str = matched_onu.get("Onu signal", "N/A")
    signal_val = cdata_extract_signal_value(signal_str)
    online_onus = [o for o in port_data if o.get("Status") == "🟢"]
    online_count = len(online_onus)
    signals = [cdata_extract_signal_value(o.get("Onu signal", "")) for o in online_onus if o.get("Onu signal", "N/A") != "N/A"]
    avg_signal = sum(signals) / len(signals) if signals else None
    POOR = -28.0

    if onu_status == "🟢" and signal_val is not None and signal_val >= POOR:
        return (
            f"🟢 **ONLINE** | **Signal:** **GOOD** **({signal_str})**\n\n"
            f"**Diagnostic Report:** > **{onu_name}** EPON device (**{onu_mac}**) is currently **Online**.\n\n"
            f"**Location Details:**\n\n**OLT**: **{olt_name}**\n\n**Port details**: Port {port}\n\n"
            f"The unit is running within the optimal operating range.\n\n"
            f"**Action Item:** > If the client reports a total loss of service despite these readings, please check Network Analysis below to confirm if the Ping is reachable before escalating the issue to the G-NOC group chat.\nThank you."
        )
    elif onu_status == "🟢" and signal_val is not None and signal_val < POOR:
        if avg_signal is not None and avg_signal >= POOR:
            return (
                f"🔴 **ONLINE** | **Signal:** **Poor** **({signal_str})**\n\n"
                f"**Diagnostic Report:** > **{onu_name}** is currently utilizing a Epon device **({onu_mac})**.\n\n"
                f"**Location Details:**\n\n**OLT**: **{olt_name}**\n\n**Port details**: Port {port}\n\n"
                f"While the status is Online, the current signal strength is recorded at **{signal_val:.2f}** **dBm**. This indicates significant optical power loss affecting the client's ONU.\n\n"
                f"**Diagnostic Context & Required Action:** > * The average port signal remains **stable**, suggesting an isolated physical layer issue at the client's premises. If the user experiences intermittent connectivity, please generate a support ticket for a technician visit to inspect the fiber terminations.\nThank you."
            )
        else:
            return (
                f"🔴 **ONLINE** | **Signal**: **Poor** **({signal_str})**\n\n"
                f"**Diagnostic Report:** > **{onu_name}** is currently utilizing a Epon device **({onu_mac})**.\n\n"
                f"**Location Details:**\n\n**OLT**: **{olt_name}**\n\n**Port details**: Port {port}\n\n"
                f"While the status is Online, the current signal strength is recorded at **{signal_val:.2f}** dBm. This indicates significant optical power loss affecting the client's ONU.\n\n"
                f"**Diagnostic Context & Required Action:** > * Diagnostic data indicates the entire port is experiencing **high optical power loss**, impacting most connected ONUs. Please verify if this port is flagged; if not, urgently alert **NOC** to investigate the OLT port.\nThank you."
            )
    else:
        if online_count == 0:
            return (
                f"🔴 **OFFLINE**\n\n**Diagnostic Report:** > **{onu_name}** EPON device **({onu_mac})** is currently **OFFLINE**.\n\n"
                f"**Location Details:**\n\n**OLT:** **{olt_name}**\n\n**Port details:** Port {port}\n\n\n"
                f"**Port diagnosis:** **The Pon Port is currently down**. Kindly confirm the port has been flagged, if not urgently inform **NOC** to check"
            )
        else:
            return (
                f"🔴 **OFFLINE**\n\n**Diagnostic Report:** > **{onu_name}** EPON device **({onu_mac})** is currently **OFFLINE**.\n\n"
                f"**Location Details:**\n\n**OLT:** **{olt_name}**\n\n**Port details:** Port {port}\n\n"
                f"**Port diagnosis:** The PON PORT looks stable with **{online_count}** ONU(s) online. If the client is experiencing LOS **Kindly raise a support ticket for the client.**"
            )
    return "Unable to generate report."
