"""
Telnet output parsers — all regex/logic from Home.py (verbatim).
"""
import re
from datetime import datetime
from collections import defaultdict
from backend.app.core.logger import debug_print


GPON_STATE_REGEX = re.compile(
    r"(?m)^(\d+/\d+/\d+:\d+)\s+enable\s+\w+\s+(working|OffLine|LOS|DyingGasp)\s+\d+\(GPON\)",
    re.IGNORECASE,
)
EPON_STATE_REGEX = re.compile(
    r"(?m)^epon-onu_(\d+/\d+/\d+:\d+)\s+(Online|Offline|Power Off)\s+\w+\s+",
    re.IGNORECASE,
)
ONU_RX_POWER_REGEX = re.compile(
    r"down\s+Tx\s*:[\d\.\-]+\(dbm\)\s+Rx\s*:([\-\d\.]+)\(dbm\)",
    re.IGNORECASE,
)


def parse_onu_states(raw_output, onu_type="gpon"):
    grouped, working = defaultdict(list), []
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
        except Exception:
            return None
    return None


def extract_client_info(detail_output):
    name = serial = None
    name_match = re.search(r"Name:\s*(\S.+)", detail_output)
    if name_match:
        name = re.sub(r"\s+", " ", name_match.group(1).strip())
    serial_match = re.search(r"Serial number:\s*(\S+)", detail_output, re.IGNORECASE)
    if serial_match:
        serial = serial_match.group(1).strip()
    return name, serial


def parse_epon_detail_info(raw_output, time_offset=None):
    offline_times, online_duration, last_down_time, last_down_cause = [], None, None, None
    name, serial = extract_client_info(raw_output)
    is_online = False
    physical_state_match = re.search(r"Physical State:\s*(\w+)", raw_output, re.IGNORECASE)
    if physical_state_match and physical_state_match.group(1).lower() == "online":
        is_online = True

    table_start = re.search(r"------------------------------------------", raw_output)
    if table_start:
        table_content = raw_output[table_start.end():]
        lines = table_content.strip().split("\n")
        if len(lines) > 1:
            for line in lines[1:]:
                match = re.match(
                    r"^\s*(\d+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
                    r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
                    r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)$",
                    line.strip(),
                )
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
                                    parts = []
                                    d = int(uptime_seconds // 86400)
                                    if d > 0:
                                        parts.append(f"{d}d")
                                    h = int((uptime_seconds % 86400) // 3600)
                                    if h > 0 or d > 0:
                                        parts.append(f"{h}h")
                                    m = int((uptime_seconds % 3600) // 60)
                                    if m > 0 or h > 0 or d > 0:
                                        parts.append(f"{m}m")
                                    s = int(uptime_seconds % 60)
                                    if s > 0 and not parts:
                                        parts.append(f"{s}s")
                                    online_duration = " ".join(parts) if parts else "0m"
                        except Exception:
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
                            except Exception:
                                pass

    if not is_online and not last_down_cause and physical_state_match:
        ps = physical_state_match.group(1).lower()
        last_down_cause = "Pow" if ps == "power off" else ps.capitalize()

    return offline_times, online_duration, name, serial, last_down_time, last_down_cause


def parse_onu_detail_info(raw_output, time_offset=None):
    offline_times, online_duration = [], None
    name, serial = extract_client_info(raw_output)
    dur_match = re.search(r"Online Duration:\s*([^\n]+)", raw_output)
    if dur_match:
        online_duration = dur_match.group(1).strip()

    for match in re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})").finditer(raw_output):
        ts = match.group(1)
        if ts != "0000-00-00 00:00:00":
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                if time_offset:
                    dt = dt + time_offset
                offline_times.append(dt)
            except Exception:
                continue
    return offline_times, online_duration, name, serial


def parse_gpon_history_for_optical_issues(detail_output, time_offset=None):
    optical_keywords = ["LOS", "LOSi", "LOFi"]
    optical_events = []
    if not re.search(r"Authpass Time\s+OfflineTime\s+Cause", detail_output, re.IGNORECASE):
        return 0, None
    pattern = re.compile(
        r"^\s*(\d+)\s+([\d-]+)\s+([\d:]+)\s+([\d-]+)\s+([\d:]+)\s+(.+?)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(detail_output):
        authpass_str = f"{match.group(2)} {match.group(3)}"
        offline_str = f"{match.group(4)} {match.group(5)}"
        cause = match.group(6).strip()
        try:
            authpass_dt = datetime.strptime(authpass_str, "%Y-%m-%d %H:%M:%S")
            if time_offset:
                authpass_dt = authpass_dt + time_offset
            if any(opt in cause for opt in optical_keywords):
                optical_events.append({"authpass": authpass_dt, "cause": cause})
                if offline_str != "0000-00-00 00:00:00":
                    offline_dt = datetime.strptime(offline_str, "%Y-%m-%d %H:%M:%S")
                    if time_offset:
                        offline_dt = offline_dt + time_offset
                    optical_events[-1]["offline"] = offline_dt
        except Exception:
            continue

    if not optical_events:
        return 0, None
    start = optical_events[0]["authpass"]
    last = optical_events[-1]
    end = last.get("offline") or last["authpass"]
    dur = end - start
    if dur.days > 0:
        tf = f"{dur.days} days"
    elif dur.seconds >= 3600:
        tf = f"{dur.seconds // 3600} hours"
    elif dur.seconds >= 60:
        tf = f"{dur.seconds // 60} minutes"
    else:
        tf = "a few moments"
    return len(optical_events), tf


def parse_epon_history_for_optical_issues(detail_output, time_offset=None):
    optical_events = []
    lines = detail_output.split("\n")
    table_start = -1
    for i, line in enumerate(lines):
        if "Register time" in line and "Authpass Time" in line and "OfflineTime" in line:
            table_start = i
            break
    if table_start == -1:
        for i, line in enumerate(lines):
            if "Register time" in line and "Authpass" in line:
                table_start = i
                break
    if table_start == -1:
        return 0, None

    i = table_start + 1
    while i < len(lines):
        line = lines[i].strip()
        match = re.match(
            r"^\s*(\d+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
            r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
            r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)$",
            line,
        )
        if match:
            authpass_str = f"{match.group(4)} {match.group(5)}"
            offline_str = f"{match.group(6)} {match.group(7)}"
            cause = match.group(8).strip()
            try:
                authpass_dt = datetime.strptime(authpass_str, "%Y/%m/%d %H:%M:%S")
                if time_offset:
                    authpass_dt = authpass_dt + time_offset
                if "Lin" in cause:
                    optical_events.append({"authpass": authpass_dt, "cause": cause, "offline": None})
                    if offline_str != "0000/00/00 00:00:00":
                        offline_dt = datetime.strptime(offline_str, "%Y/%m/%d %H:%M:%S")
                        if time_offset:
                            offline_dt = offline_dt + time_offset
                        optical_events[-1]["offline"] = offline_dt
            except Exception:
                pass
        i += 1

    if not optical_events:
        return 0, None
    start = optical_events[0]["authpass"]
    last = optical_events[-1]
    end = last.get("offline") or last["authpass"]
    dur = end - start
    if dur.days > 0:
        tf = f"{dur.days} days"
    elif dur.seconds >= 3600:
        tf = f"{dur.seconds // 3600} hours"
    elif dur.seconds >= 60:
        tf = f"{dur.seconds // 60} minutes"
    else:
        tf = "a few moments"
    return len(optical_events), tf


def format_optical_issue_message(optical_count, time_frame, onu_type):
    if optical_count >= 2:
        return (f"\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced "
                f"{optical_count} optical-related outages within the last {time_frame} "
                f"before its current state.")
    elif optical_count == 1:
        if onu_type.lower() == "gpon":
            return "\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced 1 optical-related issue recently. Please monitor the connection."
        return "\n\n- **⚠️ Optical Issue Detected:** This ONU has experienced 1 Link disconnect recently. Please monitor the connection."
    return ""


def compute_avg_from_rx_values(rx_values):
    if not rx_values:
        return 0, 0, 0, 0
    avg = sum(rx_values) / len(rx_values)
    below_29 = sum(1 for s in rx_values if s < -29)
    below_28 = sum(1 for s in rx_values if s < -28)
    return avg, below_28, below_29, len(rx_values)
