"""
ZTE/EPON telnet I/O — Full logic including downtime and optical issues.
"""
import asyncio
import re
from datetime import datetime, timedelta
import telnetlib3

from backend.app.config import TELNET_USERNAME, TELNET_PASSWORD
from backend.app import state
from backend.app.state import DEBUG_DATA
from backend.app.core.logger import debug_print
from backend.app.core.utils import (
    parse_olt_time, calculate_time_offset, format_time_ago,
    calculate_uptime_from_duration, round_percentages_to_10
)

# --- Copied from Home.py ---
GPON_STATE_REGEX = re.compile(r"(?m)^(\d+/\d+/\d+:\d+)\s+enable\s+\w+\s+(working|OffLine|LOS|DyingGasp)\s+\d+\(GPON\)", re.IGNORECASE)
EPON_STATE_REGEX = re.compile(r"(?m)^epon-onu_(\d+/\d+/\d+:\d+)\s+(Online|Offline|Power Off)\s+\w+\s+", re.IGNORECASE)
ONU_RX_POWER_REGEX = re.compile(r"down\s+Tx\s*:[\d\.\-]+\(dbm\)\s+Rx\s*:([\-\d\.]+)\(dbm\)", re.IGNORECASE)

def parse_onu_states(raw_output, onu_type="gpon"):
    grouped, working = {}, []
    if onu_type.lower() == "gpon":
        for onu_id, st in GPON_STATE_REGEX.findall(raw_output):
            if st.lower() == "working": working.append(onu_id)
            else: grouped.setdefault(st.upper(), []).append(onu_id)
    else:
        for onu_id, st in EPON_STATE_REGEX.findall(raw_output):
            if st.lower() == "online": working.append(onu_id)
            else: grouped.setdefault(st.upper(), []).append(onu_id)
    return grouped, working

def parse_onu_rx_power_single(raw_output):
    m = ONU_RX_POWER_REGEX.search(raw_output)
    return float(m.group(1)) if m else None

def extract_client_info(detail_output):
    name = re.sub(r'\s+', ' ', m.group(1).strip()) if (m := re.search(r'Name:\s*(\S.+)', detail_output)) else None
    serial = m.group(1).strip() if (m := re.search(r'Serial number:\s*(\S+)', detail_output, re.IGNORECASE)) else None
    return name, serial

def parse_epon_detail_info(raw_output, time_offset=None):
    offline_times, online_duration, last_down_time, last_down_cause = [], None, None, None
    name, serial = extract_client_info(raw_output)
    is_online = False
    if m := re.search(r'Physical State:\s*(\w+)', raw_output, re.IGNORECASE):
        is_online = m.group(1).lower() == "online"
    
    if table_start := re.search(r'------------------------------------------', raw_output):
        lines = raw_output[table_start.end():].strip().split('\n')[1:]
        for line in lines:
            m = re.match(r'^\s*(\d+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)$', line.strip())
            if m:
                authpass_str = f"{m.group(4)} {m.group(5)}"
                offline_str = f"{m.group(6)} {m.group(7)}"
                cause = m.group(8).strip()
                
                if is_online:
                    try:
                        authpass_dt = datetime.strptime(authpass_str, "%Y/%m/%d %H:%M:%S")
                        if time_offset: authpass_dt += time_offset
                        if not last_down_time or authpass_dt > last_down_time:
                            uptime_sec = (datetime.now() - authpass_dt).total_seconds()
                            if uptime_sec >= 0:
                                days = int(uptime_sec // 86400)
                                hours = int((uptime_sec % 86400) // 3600)
                                mins = int((uptime_sec % 3600) // 60)
                                secs = int(uptime_sec % 60)
                                parts = []
                                if days > 0: parts.append(f"{days}d")
                                if hours > 0 or days > 0: parts.append(f"{hours}h")
                                if mins > 0 or hours > 0 or days > 0: parts.append(f"{mins}m")
                                if secs > 0 and not parts: parts.append(f"{secs}s")
                                online_duration = " ".join(parts) if parts else "0m"
                    except: pass
                else:
                    if offline_str != "0000/00/00 00:00:00":
                        try:
                            offline_dt = datetime.strptime(offline_str, "%Y/%m/%d %H:%M:%S")
                            if time_offset: offline_dt += time_offset
                            last_down_cause = cause
                            if not last_down_time or offline_dt > last_down_time:
                                last_down_time = offline_dt
                        except: pass
    
    if not is_online and not last_down_cause and 'Physical State' in locals():
        ps = re.search(r'Physical State:\s*(\w+)', raw_output, re.IGNORECASE)
        if ps: last_down_cause = "Pow" if ps.group(1).lower() == "power off" else ps.group(1).capitalize()
    return offline_times, online_duration, name, serial, last_down_time, last_down_cause

def parse_onu_detail_info(raw_output, time_offset=None):
    offline_times = []
    name, serial = extract_client_info(raw_output)
    online_duration = m.group(1).strip() if (m := re.search(r"Online Duration:\s*([^\n]+)", raw_output)) else None
    for m in re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})').finditer(raw_output):
        ts = m.group(1)
        if ts != "0000-00-00 00:00:00":
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                if time_offset: dt += time_offset
                offline_times.append(dt)
            except: pass
    return offline_times, online_duration, name, serial

def parse_gpon_history_for_optical_issues(detail_output, time_offset=None):
    optical_keywords = ['LOS', 'LOSi', 'LOFi']
    optical_events = []
    if not re.search(r'Authpass Time\s+OfflineTime\s+Cause', detail_output, re.IGNORECASE):
        return 0, None
    pattern = re.compile(r'^\s*(\d+)\s+([\d-]+)\s+([\d:]+)\s+([\d-]+)\s+([\d:]+)\s+(.+?)$', re.MULTILINE)
    for match in pattern.finditer(detail_output):
        authpass_str = f"{match.group(2)} {match.group(3)}"
        offline_str = f"{match.group(4)} {match.group(5)}"
        cause = match.group(6).strip()
        try:
            authpass_dt = datetime.strptime(authpass_str, "%Y-%m-%d %H:%M:%S")
            if time_offset: authpass_dt += time_offset
            if any(opt in cause for opt in optical_keywords):
                optical_events.append({'authpass': authpass_dt, 'cause': cause})
                if offline_str != "0000-00-00 00:00:00":
                    offline_dt = datetime.strptime(offline_str, "%Y-%m-%d %H:%M:%S")
                    if time_offset: offline_dt += time_offset
                    optical_events[-1]['offline'] = offline_dt
        except: continue
    if not optical_events: return 0, None
    start = optical_events[0]['authpass']
    last = optical_events[-1]
    end = last.get('offline') or last['authpass']
    dur = end - start
    if dur.days > 0: tf = f"{dur.days} days"
    elif dur.seconds >= 3600: tf = f"{dur.seconds // 3600} hours"
    elif dur.seconds >= 60: tf = f"{dur.seconds // 60} minutes"
    else: tf = "a few moments"
    return len(optical_events), tf

def parse_epon_history_for_optical_issues(detail_output, time_offset=None):
    optical_events = []
    lines = detail_output.split('\n')
    table_start = -1
    for i, line in enumerate(lines):
        if 'Register time' in line and 'Authpass Time' in line and 'OfflineTime' in line:
            table_start = i; break
    if table_start == -1: return 0, None
    i = table_start + 1
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r'^\s*(\d+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)$', line)
        if m:
            authpass_str = f"{m.group(4)} {m.group(5)}"
            offline_str = f"{m.group(6)} {m.group(7)}"
            cause = m.group(8).strip()
            try:
                authpass_dt = datetime.strptime(authpass_str, "%Y/%m/%d %H:%M:%S")
                if time_offset: authpass_dt += time_offset
                if "Lin" in cause:
                    optical_events.append({'authpass': authpass_dt, 'cause': cause, 'offline': None})
                    if offline_str != "0000/00/00 00:00:00":
                        offline_dt = datetime.strptime(offline_str, "%Y/%m/%d %H:%M:%S")
                        if time_offset: offline_dt += time_offset
                        optical_events[-1]['offline'] = offline_dt
            except: pass
        i += 1
    if not optical_events: return 0, None
    start = optical_events[0]['authpass']
    last = optical_events[-1]
    end = last.get('offline') or last['authpass']
    dur = end - start
    if dur.days > 0: tf = f"{dur.days} days"
    elif dur.seconds >= 3600: tf = f"{dur.seconds // 3600} hours"
    elif dur.seconds >= 60: tf = f"{dur.seconds // 60} minutes"
    else: tf = "a few moments"
    return len(optical_events), tf

def format_optical_issue_message(count, tf, onu_type):
    if count >= 2: return f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced {count} optical-related outages within the last {tf} before its current state."
    elif count == 1: return f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced 1 optical-related issue recently. Please monitor the connection."
    return ""

# --- Telnet Connections ---
async def telnet_connect(olt_ip):
    async def _login(reader, writer, label=""):
        try:
            await asyncio.wait_for(reader.read(1024), timeout=3)
            writer.write(f"{TELNET_USERNAME}\n"); await asyncio.sleep(0.5)
            await asyncio.wait_for(reader.read(1024), timeout=3)
            writer.write(f"{TELNET_PASSWORD}\n"); await asyncio.sleep(0.5)
            for _ in range(10):
                chunk = await asyncio.wait_for(reader.read(1024), timeout=5)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            writer.write("terminal length 0\n"); await asyncio.sleep(0.5)
            await asyncio.wait_for(reader.read(1024), timeout=3)
            return reader, writer
        except Exception as e:
            raise
    ips = str(olt_ip).split(",")
    last_err = None
    for addr in ips:
        addr = addr.strip()
        try:
            host, port = addr, 23
            if ":" in addr and addr.count(":") <= 2:
                host, p_str = addr.rsplit(":", 1)
                port = int(p_str)
            reader, writer = await telnetlib3.open_connection(host, port, connect_minwait=0.05, connect_maxwait=1)
            return await _login(reader, writer, f"{host}:{port}")
        except Exception as e:
            last_err = e
    raise last_err if last_err else Exception("All connection attempts failed")

async def send_command_with_pagination(reader, writer, command):
    writer.write(command + "\n")
    await asyncio.sleep(1.5)
    out = ""
    pages = 0
    while pages < 20:
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=3)
        except asyncio.TimeoutError: break
        if not chunk: break
        out += chunk
        if "--More--" in chunk:
            writer.write(" "); pages += 1; await asyncio.sleep(0.8)
        if "ZXAN>" in chunk or "ZXAN#" in chunk: break
        await asyncio.sleep(0.2)
    return out

async def get_olt_time_correction(reader, writer):
    try:
        out = await send_command_with_pagination(reader, writer, "show clock")
        return calculate_time_offset(parse_olt_time(out))
    except: return timedelta(0)

async def get_port_signal_average(reader, writer, olt_port, onu_type):
    try:
        cmd = f"show {onu_type.lower()} onu state {onu_type.lower()}-{olt_port}\n"
        writer.write(cmd); await writer.drain()
        out = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=8)
                if not chunk: break
                out += chunk
                if '--More--' in chunk: writer.write(' '); await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            except asyncio.TimeoutError: break
        _, working = parse_onu_states(out, onu_type)
        if not working: return 0, 0, 0, 0
        rx_vals = []
        for onu in working[:20]:
            cmd = f"show pon power attenuation {onu_type.lower()}-onu_{onu}\n"
            writer.write(cmd); await writer.drain()
            p_out = ""
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(1024), timeout=5)
                    if not chunk: break
                    p_out += chunk
                    if "ZXAN>" in chunk or "ZXAN#" in chunk: break
                except asyncio.TimeoutError: break
            for line in p_out.split('\n'):
                if 'down' in line.lower():
                    m = re.search(r'Rx:([-\d\.]+)\(dbm\)', line, re.IGNORECASE)
                    if m: rx_vals.append(float(m.group(1))); break
            await asyncio.sleep(0.3)
        if not rx_vals: return 0, 0, 0, 0
        avg = sum(rx_vals) / len(rx_vals)
        return avg, sum(1 for s in rx_vals if s < -28), sum(1 for s in rx_vals if s < -29), len(rx_vals)
    except: return 0, 0, 0, 0

async def get_onu_details(reader, writer, onu_id, onu_type, time_offset=None):
    try:
        cmd = f"show {onu_type.lower()} onu detail-info {onu_type.lower()}-onu_{onu_id}\n" if onu_type.lower() == "gpon" else f"show onu detail-info epon-onu_{onu_id}\n"
        writer.write(cmd); await writer.drain()
        out = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=8)
                if not chunk: break
                out += chunk
                if "--More--" in chunk: writer.write(" "); await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            except asyncio.TimeoutError: break
        if onu_type.lower() == "gpon":
            offline, dur, name, sn = parse_onu_detail_info(out, time_offset)
            ld = max(offline) if offline else None
            return {"client_name": name or "Unknown", "serial": sn or "N/A", "last_down": ld, "time_ago": format_time_ago(ld) if ld else "N/A", "online_duration": dur or "N/A"}
        else:
            _, dur, name, sn, ld, cause = parse_epon_detail_info(out, time_offset)
            return {"client_name": name or "Unknown", "serial": sn or "N/A", "last_down": ld, "time_ago": format_time_ago(ld) if ld else "N/A", "online_duration": dur or "N/A", "cause": cause}
    except: return {"client_name": "Unknown", "serial": "N/A", "last_down": None, "time_ago": "N/A", "online_duration": "N/A"}

async def get_detailed_port_analysis(reader, writer, olt_port, onu_type, time_offset, state, total, online):
    from collections import defaultdict
    mst, jcu, jwd = [], [], []
    try:
        cmd = f"show {onu_type.lower()} onu state {onu_type.lower()}-{olt_port}\n"
        writer.write(cmd); await writer.drain()
        out = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk: break
                out += chunk
                if '--More--' in chunk: writer.write(' '); await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            except asyncio.TimeoutError: break
        grouped, working = parse_onu_states(out, onu_type)
        for onu in working[:30]:
            info = await get_onu_details(reader, writer, onu, onu_type, time_offset)
            mins = calculate_uptime_from_duration(info.get("online_duration", "N/A"))
            if mins is not None and mins <= 5 and info.get("client_name") != "Unknown": jcu.append(info["client_name"])
        non_working = [(onu, s) for s, onus in grouped.items() for onu in onus]
        los = []
        for onu, s in non_working[:30]:
            info = await get_onu_details(reader, writer, onu, onu_type, time_offset)
            if info.get("last_down"):
                ld = info["last_down"]
                if (datetime.now() - ld).total_seconds() <= 300 and info.get("client_name") != "Unknown": jwd.append(info["client_name"])
                if s.upper() == "LOS": los.append({"onu_id": onu, "client_name": info.get("client_name", "Unknown"), "last_down": ld})
        if len(los) >= 2:
            groups = defaultdict(list)
            for r in los:
                if r["last_down"]:
                    k = r["last_down"].replace(second=0, microsecond=0)
                    k = k.replace(minute=(k.minute // 2) * 2)
                    groups[k].append(r)
            for g in groups.values():
                if 2 <= len(g) <= 8:
                    for r in g:
                        if r["client_name"] != "Unknown": mst.append(r["client_name"])
    except: pass
    return [], mst, jcu, jwd

async def connect_to_olt(OLT, olt_ip, onu_type, olt_port, onu_id, smartolt_name):
    result_lines = []
    # Initialize ALL return variables to prevent UnboundLocalError
    status, rx_power_val, avg_port_power = "unknown", None, 0
    downtime_reason, online_duration, time_ago, optical_issue_message = None, "N/A", None, ""
    is_high_loss = False

    DEBUG_DATA["smartolt_name"] = smartolt_name
    DEBUG_DATA["downtime_info"] = {"reason": None, "time_ago": None, "last_down": None}
    DEBUG_DATA["mst_clients"], DEBUG_DATA["jcu_clients"], DEBUG_DATA["jwd_clients"] = [], [], []

    try:
        try:
            reader, writer = await telnet_connect(olt_ip)
        except Exception as e:
            debug_print(f"❌ OLT {smartolt_name} ({olt_ip}) is DOWN: {e}", "ERROR")
            # Return immediately with status 'olt_down' so the frontend shows a clean message
            return result_lines, "olt_down", 0, False, None, "N/A", None, None, ""

        time_offset = await get_olt_time_correction(reader, writer)

        cmd = f"show {onu_type.lower()} onu state {onu_type.lower()}-{olt_port}\n"
        writer.write(cmd); await writer.drain()
        state_out = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk: break
                state_out += chunk
                if "--More--" in chunk: writer.write(" "); await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            except asyncio.TimeoutError: break

        cmd = f"show pon power attenuation {onu_type.lower()}-onu_{olt_port.replace('olt_', '')}:{onu_id}\n"
        writer.write(cmd); await writer.drain()
        p_out = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk: break
                p_out += chunk
                if "--More--" in chunk: writer.write(" "); await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            except asyncio.TimeoutError: break
        rx_power_val = parse_onu_rx_power_single(p_out)

        target = f"{olt_port.replace('olt_', '')}:{onu_id}"
        cmd = f"show {onu_type.lower()} onu detail-info {onu_type.lower()}-onu_{target}\n" if onu_type.lower() == "gpon" else f"show onu detail-info epon-onu_{target}\n"
        writer.write(cmd); await writer.drain()
        detail_out = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=8)
                if not chunk: break
                detail_out += chunk
                if "--More--" in chunk: writer.write(" "); await asyncio.sleep(1.0)
                if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            except asyncio.TimeoutError: break

        grouped, working = parse_onu_states(state_out, onu_type)

        if onu_type.lower() == "gpon":
            off_times, online_duration, _, _ = parse_onu_detail_info(detail_out, time_offset)
            opt_count, opt_frame = parse_gpon_history_for_optical_issues(detail_out, time_offset)
            if opt_count >= 2: optical_issue_message = format_optical_issue_message(opt_count, opt_frame, onu_type)

            found = False
            for onu in working:
                if onu == target:
                    found, status = True, "online"
                    if off_times:
                        last = max(off_times)
                        up = (datetime.now() - last).total_seconds()
                        if up >= 0:
                            parts = []
                            d, h, m, s = int(up // 86400), int((up % 86400) // 3600), int((up % 3600) // 60), int(up % 60)
                            if d > 0: parts.append(f"{d}d")
                            if h > 0 or d > 0: parts.append(f"{h}h")
                            if m > 0 or h > 0 or d > 0: parts.append(f"{m}m")
                            if s > 0 and not parts: parts.append(f"{s}s")
                            online_duration = " ".join(parts) if parts else "0m"
                    break
            if not found:
                for st, onus in grouped.items():
                    for onu in onus:
                        if onu == target:
                            found, status = True, "offline"
                            if off_times:
                                last = max(off_times)
                                time_ago = format_time_ago(last)
                                reason = "Loss of Signal" if st.upper() == "LOS" else ("Power Failure" if st.upper() == "DYINGGASP" else st)
                                downtime_reason = f"{reason} ({time_ago})"
                                DEBUG_DATA["downtime_info"] = {"reason": downtime_reason, "time_ago": time_ago, "last_down": last}
                            break
                    if found: break
            if not found:
                status = "not_found"
                result_lines.append(f"❌ ONU ID {onu_id} not found in the list.")
        else:
            _, online_duration, _, _, last_down, cause = parse_epon_detail_info(detail_out, time_offset)
            opt_count, opt_frame = parse_epon_history_for_optical_issues(detail_out, time_offset)
            if opt_count >= 2: optical_issue_message = format_optical_issue_message(opt_count, opt_frame, onu_type)

            ps = re.search(r"Physical State:\s*(\w+)", detail_out, re.IGNORECASE)
            if ps and ps.group(1).lower() == "online":
                status = "online"
            else:
                status = "offline"
                if last_down:
                    time_ago = format_time_ago(last_down)
                    downtime_reason = cause if cause else "Unknown"
                    DEBUG_DATA["downtime_info"] = {"reason": downtime_reason, "time_ago": time_ago, "last_down": last_down}

        total_clients = len(working) + sum(len(onus) for onus in grouped.values())
        online_clients = len(working)
        los_c = len(grouped.get("LOS", []))
        dg_c = len(grouped.get("DYINGGASP", []))
        off_c = len(grouped.get("OFFLINE", [])) + len(grouped.get("POWER OFF", []))

        DEBUG_DATA["port_stats"] = {"total_onu": total_clients, "online": online_clients, "los": los_c, "dyinggasp": dg_c, "offline": off_c, "percentages": {}}
        if total_clients > 0:
            pct = round_percentages_to_10({"onl": online_clients, "LOS": los_c, "pf": dg_c, "ofl": off_c})
            DEBUG_DATA["port_stats"]["percentages"] = {"onl": pct.get("onl", 0), "los": pct.get("LOS", 0), "pf": pct.get("pf", 0), "ofl": pct.get("ofl", 0)}

        avg_port_power, below_28, below_29, total_onus = await get_port_signal_average(reader, writer, olt_port, onu_type)
        DEBUG_DATA["status_flags"] = {"JCU": 0, "JWD": 0, "HL": 0, "MPI": 0, "MST": 0}
        is_high_loss = False
        if avg_port_power < -29 or (total_onus > 0 and (below_29 / total_onus) >= 0.7) or (total_onus > 0 and (below_28 / total_onus) >= 0.85):
            is_high_loss = True
            DEBUG_DATA["status_flags"]["HL"] = 1

        _, mst, jcu, jwd = await get_detailed_port_analysis(reader, writer, olt_port, onu_type, time_offset, downtime_reason or "unknown", total_clients, online_clients)
        DEBUG_DATA["mst_clients"], DEBUG_DATA["jcu_clients"], DEBUG_DATA["jwd_clients"] = mst, jcu, jwd
        if len(mst) >= 2: DEBUG_DATA["status_flags"]["MST"] = 1
        if len(jcu) >= 3: DEBUG_DATA["status_flags"]["JCU"] = 1
        if len(jwd) >= 3: DEBUG_DATA["status_flags"]["JWD"] = 1
        if total_clients > 0 and (online_clients == 0 or (online_clients / total_clients) <= 0.2):
            DEBUG_DATA["status_flags"]["MPI"] = 1

        writer.close()
    except Exception as e:
        result_lines.append(f"Error connecting to OLT: {str(e)}")
        status = "error"
        debug_print(f"Error in connect_to_olt: {e}", "ERROR")

    return result_lines, status, avg_port_power, is_high_loss, rx_power_val, online_duration, downtime_reason, time_ago, optical_issue_message
