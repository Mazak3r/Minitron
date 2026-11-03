import re
from typing import Dict, List

from backend.app.config import POOR_SIGNAL_THRESHOLD
from backend.app.core.utils import format_online_duration, extract_olt_name

def format_llm_response(smartolt_name, device_name, onu_type, serial_number,
                        client_status, rx_power_val, uptime, downtime_reason,
                        avg_port_power, is_high_loss, olt_name, board, port, time_ago,
                        optical_issue_message=""):
    if client_status == "olt_down":
        return f"""🔴 **OLT IS UNREACHABLE**

The OLT **{olt_name}** is currently down and cannot be reached."""

    if client_status == "online":
        uptime_parts = format_online_duration(uptime)
        if uptime_parts:
            parts = []
            if uptime_parts["years"] > 0: parts.append(f"{uptime_parts['years']}y")
            if uptime_parts["months"] > 0: parts.append(f"{uptime_parts['months']}m")
            if uptime_parts["days"] > 0: parts.append(f"{uptime_parts['days']}d")
            if uptime_parts["hours"] > 0: parts.append(f"{uptime_parts['hours']}h")
            if uptime_parts["minutes"] > 0: parts.append(f"{uptime_parts['minutes']}m")
            if uptime_parts["seconds"] > 0: parts.append(f"{uptime_parts['seconds']}s")
            uptime_str = " ".join(parts) if parts else "a few moments"
        else:
            uptime_str = "Unknown"

        signal_quality = "Good"
        signal_emoji = "🟢"
        if rx_power_val is not None:
            if rx_power_val < -29:
                signal_quality = "Poor"; signal_emoji = "🔴"
            elif rx_power_val < -28:
                signal_quality = "Marginal"; signal_emoji = "🟡"
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
            formatted_reason = {"Lin": "Loss of Signal", "Pow": "Power Failure"}.get(downtime_reason, downtime_reason)
        else:
            reason_map = {"Loss of Signal": "Loss of Signal", "Power Failure": "Power Failure (Dying Gasp)", "Power Off": "Power Off", "Offline State": "Offline State"}
            base_reason = downtime_reason.split(" (")[0] if downtime_reason else "Unknown"
            formatted_reason = reason_map.get(base_reason, base_reason)

        response = f"""🔴 OFFLINE

**Diagnostic Report:** > **{smartolt_name.upper()}** is currently Offline. The **{device_name}** **{onu_type.upper()}** device (SN: **{serial_number.upper()}**) has been unreachable from the OLT since **{time_ago}**.

**Location Details:**

- **OLT:** {olt_name}
- **Port details:** Board **{board}** | Port **{port}**
- **Reason for Outage:** The outage is attributed to: **{formatted_reason}**"""
        if optical_issue_message:
            response += optical_issue_message
        return response

def format_port_analysis(port_analysis, is_mst_detected, mst_clients=None, 
                         is_jcu_detected=None, jcu_clients=None,
                         is_jwd_detected=None, jwd_clients=None,
                         local_debug_data=None):
    result = "\n---\n\n## Port Analysis\n\n"
    if not port_analysis:
        stats = local_debug_data.get("port_stats", {}) if local_debug_data else {}
        percentages = stats.get("percentages", {})
        flags = local_debug_data.get("status_flags", {}) if local_debug_data else {}
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
        result += f"""- **Explanation:** {port_analysis.get('Explanation', 'No explanation available')}

- **Action:** {port_analysis.get('Action', 'No action specified')}

- **Severity:** {port_analysis.get('Severity', 'Unknown')}
"""

    stats = local_debug_data.get("port_stats", {}) if local_debug_data else {}
    if is_mst_detected and mst_clients and len(mst_clients) >= 2:
        if stats.get("online", 0) > 0:
            result += "\n**Clients experiencing suspect MST issue:**\n"
            for client in mst_clients[:10]: result += f"- {client}\n"
            if len(mst_clients) > 10: result += f"- ... and {len(mst_clients) - 10} more\n"

    if is_jcu_detected and jcu_clients and len(jcu_clients) >= 3:
        if stats.get("online", 0) > 0:
            result += "\n**Clients that just came up (within last 5 minutes):**\n"
            for client in jcu_clients[:10]: result += f"- {client}\n"
            if len(jcu_clients) > 10: result += f"- ... and {len(jcu_clients) - 10} more\n"

    if is_jwd_detected and jwd_clients and len(jwd_clients) >= 3:
        if stats.get("online", 0) > 0:
            result += "\n**Clients that just went down (within last 5 minutes):**\n"
            for client in jwd_clients[:10]: result += f"- {client}\n"
            if len(jwd_clients) > 10: result += f"- ... and {len(jwd_clients) - 10} more\n"
    return result
