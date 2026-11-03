"""
Search orchestrator — direct port of the `if search_clicked:` block.
"""
import re
from typing import Dict, List, Any

from backend.app import state
from backend.app.config import OLT_IPS
from backend.app.core.logger import debug_print, print_debug_header
from backend.app.core.utils import (
    get_device_type, check_reachability,
    clean_search_input_for_smartolt, clean_search_input_for_selenium,
    search_proctor_csv, search_kylian_csv,
)
from backend.app.core.telnet.zte import connect_to_olt
from backend.app.core.diameter import get_diameter_user_data, format_network_analysis
from backend.app.core.radio import identify_radio_type, format_radio_message, get_mac_vendor
from backend.app.core.selenium.search import search_selenium_olt
from backend.app.core.reporting.reports import (
    format_llm_response, format_port_analysis,

)
from backend.app.core.cdata import (
    cdata_generate_diagnostic_report,
    cdata_search_and_monitor_port, get_cdata_olt_name_by_ip, cdata_extract_signal_value,
)
from backend.app.core.port_analysis import find_port_analysis_match


POOR_SIGNAL_THRESHOLD = -28


def _empty_state() -> Dict[str, Any]:
    return {
        "last_ping_reachable": False, "last_cpe_ip": "N/A", "last_mac_vendor": "",
        "last_device_vendor": "N/A", "last_onu_type": "N/A", "last_service_plan": "N/A",
        "last_board": "N/A", "last_port": "N/A", "last_olt_name": "N/A",
        "last_client_status": "N/A", "last_onu_id": "N/A", "last_smartolt_name": "N/A",
    }


def _parse_olt_full(olt_full: str):
    m = re.search(r"(\S+onu_\d+/\d+/\d+:\d+)", olt_full)
    if not m: return None
    onu_part = m.group(1)
    olt_name = olt_full.replace(onu_part, "").strip()
    onu_type = "gpon" if "gpon-onu_" in onu_part else ("epon" if "epon-onu_" in onu_part else "gpon")
    port_onu = onu_part.split("_")[1] if "_" in onu_part else onu_part
    port_part = port_onu.split(":")[0] if ":" in port_onu else port_onu
    onu_id = int(port_onu.split(":")[1]) if ":" in port_onu else 0
    parts = port_part.split("/")
    if len(parts) >= 3:
        board, port = parts[1], parts[2]
        olt_port = f"olt_{parts[0]}/{parts[1]}/{parts[2]}"
    else:
        board, port = "N/A", "N/A"
        olt_port = f"olt_{port_part}"
    return {"olt_name_full": olt_name, "onu_type": onu_type, "board": board, "port": port, "onu_id": onu_id, "olt_port": olt_port}


def _resolve_olt_ip(name: str):
    ip = OLT_IPS.get(name)
    if not ip:
        ip = OLT_IPS.get(re.sub(r"\s+OLT$", "", name))
    return ip


def _attach_network(blocks: List[Dict], session_id: str, username: str):
    if not session_id: return None
    try:
        data = get_diameter_user_data(username, session_id)
    except Exception as e:
        debug_print(f"Diameter fetch failed: {e}", "ERROR")
        return None
    if not data or not data.get("found", False): return data
    md = format_network_analysis(data)
    if md: blocks.append({"type": "network_analysis", "content": md})
    return data


def _process_csv_single(csv_result, blocks, search_state, session_id):
    parsed = _parse_olt_full(csv_result["olt_full"])
    if not parsed:
        blocks.append({"type": "error", "content": "⚠️ Invalid OLT data format in CSV"})
        return
    olt_name = parsed["olt_name_full"]
    onu_type = parsed["onu_type"]
    board, port, onu_id = parsed["board"], parsed["port"], parsed["onu_id"]
    olt_port = parsed["olt_port"]
    serial = csv_result["serial_number"]
    smartolt = csv_result["smartolt_name"]
    dev_name = get_device_type(serial)
    olt_ip = _resolve_olt_ip(olt_name)

    if not olt_ip:
        blocks.append({"type": "error", "content": f'❌ No IP mapping for OLT "{olt_name}"'})
        return
    if not check_reachability(olt_ip):
        blocks.append({"type": "error", "content": f"❌ {smartolt.upper()} - OLT {olt_name} is DOWN"})
        return

    blocks.append({"type": "info", "content": f"🔍 Connecting to {olt_name} OLT..."})

    import asyncio
    try:
        (_, client_status, avg_power, is_high_loss, rx, dur, reason, ago, optical) = asyncio.run(
            connect_to_olt(olt_name, olt_ip, onu_type, olt_port, onu_id, smartolt)
        )
        # Snapshot the debug data for THIS specific search
        import copy
        local_debug_data = copy.deepcopy(state.DEBUG_DATA)
    except Exception as e:
        blocks.append({"type": "error", "content": f"Error: {e}"})
        return

    response = format_llm_response(
        smartolt, dev_name, onu_type, serial, client_status, rx, dur, reason,
        avg_power, is_high_loss, olt_name, board, port, ago, optical,
    )
    blocks.append({"type": "onu_entry", "content": response})

    search_state.update({
        "last_device_vendor": dev_name, "last_onu_type": onu_type.upper(),
        "last_board": board, "last_port": port, "last_olt_name": olt_name,
        "last_client_status": client_status, "last_onu_id": onu_id, "last_smartolt_name": smartolt,
    })

    if client_status == "online" and rx is not None and rx >= -28:
        dd = _attach_network(blocks, session_id, smartolt)
        if dd and dd.get("found", False):
            search_state["last_cpe_ip"] = dd.get("cpe_ip", "N/A")
            search_state["last_service_plan"] = dd.get("service_plan", "N/A")
            search_state["last_ping_reachable"] = dd.get("ping_reachable", False)
            mac = dd.get("mac_address", "N/A")
            search_state["last_mac_vendor"] = get_mac_vendor(mac) if mac != "N/A" else ""

    if client_status == "offline":
        pct = state.DEBUG_DATA["port_stats"].get("percentages", {})
        flags = state.DEBUG_DATA["status_flags"]
        pa = find_port_analysis_match(pct, flags)
        txt = format_port_analysis(pa, flags["MST"] == 1, local_debug_data["mst_clients"],
                                    flags["JCU"] == 1, local_debug_data["jcu_clients"],
                                    flags["JWD"] == 1, local_debug_data["jwd_clients"], local_debug_data)
        blocks.append({"type": "port_analysis", "content": txt})


def _process_selenium(sel, blocks, search_state, session_id):
    if sel.get("olt_down"):
        blocks.append({"type": "olt_down", "content": sel["report"]})
        return
    blocks.append({"type": "selenium_entry", "content": sel["report"]})
    target = sel.get("target_ont")
    if not target or target.get("rstate") != 1: return
    if not session_id: return
    ont_name = target.get("ont_name", "N/A")
    if ont_name == "N/A": return
    dd = _attach_network(blocks, session_id, ont_name)
    if dd and dd.get("found", False):
        search_state["last_cpe_ip"] = dd.get("cpe_ip", "N/A")
        search_state["last_service_plan"] = dd.get("service_plan", "N/A")
        search_state["last_ping_reachable"] = dd.get("ping_reachable", False)
        mac = dd.get("mac_address", "N/A")
        search_state["last_mac_vendor"] = get_mac_vendor(mac) if mac != "N/A" else ""


def _process_cdata(matched, port_data, olt_ip, port_str, err, blocks, search_state, session_id):
    if err:
        blocks.append({"type": "olt_down", "content": err})
        return
    if not (matched and port_data and olt_ip and port_str): return
    olt_name = get_cdata_olt_name_by_ip(olt_ip)
    report = cdata_generate_diagnostic_report(matched, port_data, olt_name, int(port_str))
    blocks.append({"type": "cdata_entry", "content": report})
    if matched.get("Status") != "🟢": return
    sig = cdata_extract_signal_value(matched.get("Onu signal", "N/A"))
    if sig is None or sig < POOR_SIGNAL_THRESHOLD or not session_id: return
    name = matched.get("Name", "")
    if not name: return
    dd = _attach_network(blocks, session_id, name)
    if dd and dd.get("found", False):
        search_state["last_cpe_ip"] = dd.get("cpe_ip", "N/A")
        search_state["last_service_plan"] = dd.get("service_plan", "N/A")
        search_state["last_ping_reachable"] = dd.get("ping_reachable", False)
        mac = dd.get("mac_address", "N/A")
        search_state["last_mac_vendor"] = get_mac_vendor(mac) if mac != "N/A" else ""


def _process_diameter(query, blocks, search_state, session_id):
    if not session_id:
        blocks.append({"type": "error", "content": "⚠️ No results found in any system."})
        return
    dd = get_diameter_user_data(query, session_id)
    if not dd or dd.get("user_not_found") or dd.get("login_page") or not dd.get("found"):
        blocks.append({"type": "error", "content": "⚠️ No results found in any system."})
        return
    rtype = identify_radio_type(dd.get("mac_address", "N/A"))
    if rtype:
        msg = format_radio_message(rtype, dd.get("nas_bts", "N/A"), dd.get("session_ip", "N/A"), dd.get("ping_reachable", False))
        if msg: blocks.append({"type": "radio_message", "content": msg})
    else:
        blocks.append({"type": "gpon_request", "content": "**Action Required:** Unable to identify connection type. Kindly request the GPON Serial Number from the client."})
    md = format_network_analysis(dd)
    if md: blocks.append({"type": "network_analysis", "content": md})
    search_state["last_cpe_ip"] = dd.get("cpe_ip", "N/A")
    search_state["last_service_plan"] = dd.get("service_plan", "N/A")
    search_state["last_ping_reachable"] = dd.get("ping_reachable", False)
    mac = dd.get("mac_address", "N/A")
    search_state["last_mac_vendor"] = get_mac_vendor(mac) if mac != "N/A" else ""
    search_state["last_smartolt_name"] = query


def execute_search(search_query: str, session_id: str = "") -> Dict[str, Any]:
    print_debug_header()
    debug_print(f"Searching: '{search_query}'", "INFO")

    sel_term = clean_search_input_for_selenium(search_query)
    csv_term = clean_search_input_for_smartolt(search_query)
    cdata_term = search_query.strip()

    blocks, search_state, sources = [], _empty_state(), []

    # 1. CSV
    sources.append("csv")
    csv_results = search_proctor_csv(csv_term) or search_kylian_csv(csv_term)
    if csv_results:
        if len(csv_results) == 1:
            _process_csv_single(csv_results[0], blocks, search_state, session_id)
        else:
            blocks.append({"type": "multiple_header", "content": f"Found {len(csv_results)} devices"})
            for i, r in enumerate(csv_results):
                blocks.append({"type": "device_header", "content": f"**Device {i+1}/{len(csv_results)}:** {r['smartolt_name']}"})
                _process_csv_single(r, blocks, search_state, session_id)
                blocks.append({"type": "divider", "content": "---"})
        return {"query": search_query, "blocks": blocks, "state": search_state, "sources_tried": sources}

    # 2. Selenium (Worker)
    sources.append("selenium")
    sel = search_selenium_olt(sel_term)
    if sel and sel.get("report"):
        _process_selenium(sel, blocks, search_state, session_id)
        return {"query": search_query, "blocks": blocks, "state": search_state, "sources_tried": sources}

    # 3. CDATA
    sources.append("cdata")
    matched, port_data, olt_ip, port_str, err = cdata_search_and_monitor_port(cdata_term)
    if err or (matched and port_data and olt_ip and port_str):
        _process_cdata(matched, port_data, olt_ip, port_str, err, blocks, search_state, session_id)
        return {"query": search_query, "blocks": blocks, "state": search_state, "sources_tried": sources}

    # 4. Diameter only
    sources.append("diameter")
    _process_diameter(csv_term, blocks, search_state, session_id)
    return {"query": search_query, "blocks": blocks, "state": search_state, "sources_tried": sources}
