#!/usr/bin/env python3
"""
Traffic Monitor — Real-time ONU traffic graph via ZTE OLT
Sleek UI: Info bar → Graph → Legend → Search
No login required. Direct connection for LAN server.
"""

import streamlit as st
import asyncio
import telnetlib3
import json
import os
import re
import time
import pandas as pd
from datetime import datetime
from collections import deque

st.set_page_config(page_title="Traffic Monitor", page_icon="📈", layout="wide")

# ---------- Load Config ----------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

OLT_IPS = CONFIG.get("olt_ips", {})
TELNET_USERNAME = CONFIG["credentials"]["telnet"]["username"]
TELNET_PASSWORD = CONFIG["credentials"]["telnet"]["password"]
PROCTOR_CSV_PATH = CONFIG.get("file_paths", {}).get("proctor_csv", os.path.join(SCRIPT_DIR, "banga.csv"))

# ---------- Service Plan Speed Limits ----------
SERVICE_PLAN_SPEEDS = {
    "FiberMax Home": 50,
    "FiberMax LitePlus": 20,
    "FiberMax Home Ultra": 100,
    "FibreHome-OutsideLagos": 50,
    "FibreHomeExtra-OutsideLagos": 75,
    "FibreHomeExtraVcIII": 75,
    "FiberMax Home Extra": 75,
    "FiberMax Ultimate": 145,
    "FiberMax Ultimate+": 220,
    "FiberMax Large": 30,
    "FiberMax Ultra": 95,
    "FiberMax Max": 60,
}

def get_speed_limit(service_plan):
    if not service_plan or service_plan == 'N/A':
        return None
    for plan, speed in SERVICE_PLAN_SPEEDS.items():
        if plan.lower() in service_plan.lower():
            return speed
    return None

# ---------- Session State ----------
if "traffic_data" not in st.session_state:
    st.session_state.traffic_data = deque(maxlen=90)
if "traffic_running" not in st.session_state:
    st.session_state.traffic_running = False
if "traffic_target" not in st.session_state:
    st.session_state.traffic_target = None
if "traffic_last_name" not in st.session_state:
    st.session_state.traffic_last_name = None

# Grab service plan directly from Home.py's session state
if st.session_state.get("last_service_plan") and st.session_state.get("last_service_plan") != 'N/A':
    st.session_state.traffic_service_plan = st.session_state.get("last_service_plan")

# Stop + clear when new name arrives
current_name = st.session_state.traffic_target.get("name") if st.session_state.traffic_target else None
if current_name and current_name != st.session_state.traffic_last_name:
    if "traffic_writer" in st.session_state and st.session_state.traffic_writer:
        try: st.session_state.traffic_writer.close()
        except: pass
    st.session_state.traffic_reader = None
    st.session_state.traffic_writer = None
    st.session_state.traffic_data = deque(maxlen=90)
    st.session_state.traffic_running = False
    st.session_state.traffic_last_name = current_name

# ---------- Helpers ----------
def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return executor.submit(asyncio.run, coro).result()

def bps_to_mbps(bps):
    return round(bps / 100_000, 3)

async def connect_and_login(olt_ip):
    host, port = olt_ip, 23
    if ':' in str(olt_ip) and not str(olt_ip).count(':') > 2:
        host, port_str = str(olt_ip).rsplit(':', 1)
        port = int(port_str)
    reader, writer = await telnetlib3.open_connection(host, port, connect_minwait=0.05, connect_maxwait=1)
    writer.write(f"{TELNET_USERNAME}\n")
    await asyncio.sleep(0.5)
    writer.write(f"{TELNET_PASSWORD}\n")
    await asyncio.sleep(0.5)
    while True:
        chunk = await asyncio.wait_for(reader.read(1024), timeout=5)
        if "ZXAN>" in chunk or "ZXAN#" in chunk:
            break
    return reader, writer

async def get_traffic_stats(reader, writer, pon_type, board, port, onu_id):
    command = f"show interface {pon_type}-onu_1/{board}/{port}:{onu_id}\n"
    writer.write(command)
    output = ""
    while True:
        try:
            chunk = await asyncio.wait_for(reader.read(2048), timeout=3)
            if not chunk: break
            output += chunk
            if "ZXAN>" in chunk or "ZXAN#" in chunk: break
            if '--More--' in chunk: writer.write(' ')
        except asyncio.TimeoutError: break
    input_rate = 0; output_rate = 0
    m = re.search(r'Input rate\s*:\s*(\d+)\s*Bps', output)
    if m: input_rate = int(m.group(1))
    m = re.search(r'Output rate\s*:\s*(\d+)\s*Bps', output)
    if m: output_rate = int(m.group(1))
    return input_rate, output_rate

def search_proctor(name):
    if not os.path.exists(PROCTOR_CSV_PATH): return None
    df = pd.read_csv(PROCTOR_CSV_PATH)
    sv = [name.strip().lower()]
    if ' ' in name: sv.append(name.replace(' ', '_').lower())
    if '_' in name: sv.append(name.replace('_', ' ').lower())
    for _, row in df.iterrows():
        sn = str(row.get('SN', '')).strip().lower()
        cn = str(row.get('Name', '')).strip().lower()
        for s in sv:
            if s == sn or s == cn or (s in cn and len(s) > 3):
                return {
                    "name": str(row.get('Name', '')).strip(),
                    "olt_name": str(row.get('OLT', '')).strip(),
                    "pon_type": str(row.get('PON Type', 'gpon')).strip().lower(),
                    "board": str(row.get('Board', '')).strip(),
                    "port": str(row.get('Port', '')).strip(),
                    "onu_id": str(row.get('Allocated ONU', '')).strip(),
                }
    return None

# ============================================================
# SLEEK UI
# ============================================================

if st.session_state.traffic_target:
    target = st.session_state.traffic_target
    sp = st.session_state.get('traffic_service_plan', 'N/A')
    limit = get_speed_limit(sp) if sp != 'N/A' else None

    # ---- INFO BAR ----
    col_name, col_plan, col_ctrl = st.columns([3, 2, 1.5])
    with col_name:
        st.markdown(f"### 📡 {target['name']}")
    with col_plan:
        if sp != 'N/A':
            limit_str = f" ({limit} Mbps)" if limit else ""
            st.markdown(f"**Plan:** {sp}{limit_str}")
        else:
            st.markdown("**Plan:** N/A")
    with col_ctrl:
        if st.session_state.traffic_running:
            if st.button("⏹️ Stop", use_container_width=True):
                st.session_state.traffic_running = False
                st.rerun()
        else:
            if st.button("▶️ Start", type="primary", use_container_width=True):
                st.session_state.traffic_running = True
                st.session_state.traffic_data = deque(maxlen=90)
                if "traffic_writer" in st.session_state and st.session_state.traffic_writer:
                    try: st.session_state.traffic_writer.close()
                    except: pass
                st.session_state.traffic_reader = None
                st.session_state.traffic_writer = None
                st.rerun()

    # Status line
    if st.session_state.traffic_running:
        st.caption(f"🟢 Live — {target['olt_name']} | Port {target['port']} | ONU {target['onu_id']} | {target['pon_type'].upper()} | Polling every 2s")
    else:
        st.caption(f"⚪ Stopped — {target['olt_name']} | Port {target['port']} | ONU {target['onu_id']} | {target['pon_type'].upper()}")

    st.markdown("---")

    # ---- POLLING ----
    if st.session_state.traffic_running:
        if "traffic_reader" not in st.session_state or st.session_state.traffic_reader is None:
            try:
                reader, writer = run_async(connect_and_login(target["olt_ip"]))
                st.session_state.traffic_reader = reader
                st.session_state.traffic_writer = writer
            except Exception as e:
                st.error(f"Connection error: {e}")
                st.session_state.traffic_running = False

        if st.session_state.traffic_running:
            try:
                reader = st.session_state.traffic_reader
                writer = st.session_state.traffic_writer
                input_bps, output_bps = run_async(get_traffic_stats(
                    reader, writer, target["pon_type"], target["board"], target["port"], target["onu_id"]
                ))
                st.session_state.traffic_data.append({
                    "time": datetime.now(),
                    "Download (Mbps)": bps_to_mbps(output_bps),
                    "Upload (Mbps)": bps_to_mbps(input_bps),
                })
            except Exception as e:
                st.error(f"Polling error: {e}")
                try: st.session_state.traffic_writer.close()
                except: pass
                st.session_state.traffic_reader = None
                st.session_state.traffic_writer = None

    else:
        if "traffic_writer" in st.session_state and st.session_state.traffic_writer:
            try: st.session_state.traffic_writer.close()
            except: pass
        st.session_state.traffic_reader = None
        st.session_state.traffic_writer = None

    # ---- CHART ----
    chart_placeholder = st.empty()
    if len(st.session_state.traffic_data) >= 1:
        df = pd.DataFrame(list(st.session_state.traffic_data))
        columns_to_plot = ["Download (Mbps)", "Upload (Mbps)"]
        colors = ["#3b82f6", "#ef4444"]
        if limit:
            df["Speed Limit"] = limit
            columns_to_plot.append("Speed Limit")
            colors.append("#f59e0b")
        chart_placeholder.line_chart(
            df.set_index("time")[columns_to_plot],
            y_label="Mbps",
            color=colors
        )
    else:
        chart_placeholder.info("No data yet. Click Start to begin monitoring.")

    # ---- LEGEND ----
    if len(st.session_state.traffic_data) >= 1:
        latest = st.session_state.traffic_data[-1]
        col_dl, col_ul, col_lim = st.columns(3)
        with col_dl:
            st.metric("📥 Download", f"{latest['Download (Mbps)']:.3f} Mbps")
        with col_ul:
            st.metric("📤 Upload", f"{latest['Upload (Mbps)']:.3f} Mbps")
        with col_lim:
            if limit:
                st.metric("🚦 Speed Limit", f"{limit} Mbps")
            else:
                st.metric("🚦 Speed Limit", "N/A")

else:
    st.info("👆 Search for an ONU name below or click 'View Traffic' from a search result")

# ---- SEARCH ----
st.markdown("---")
with st.expander("🔍 Search ONU", expanded=not st.session_state.traffic_target):
    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        search_name = st.text_input("ONU Name", placeholder="e.g., john_doe", key="traffic_search_name", label_visibility="collapsed")
    with col_s2:
        if st.button("🔍 Search", use_container_width=True):
            if search_name:
                result = search_proctor(search_name)
                if result:
                    olt_ip = OLT_IPS.get(result["olt_name"])
                    if not olt_ip:
                        olt_name_clean = re.sub(r'\s+OLT$', '', result["olt_name"])
                        olt_ip = OLT_IPS.get(olt_name_clean)
                    if olt_ip:
                        result["olt_ip"] = olt_ip
                        # Stop old session
                        if "traffic_writer" in st.session_state and st.session_state.traffic_writer:
                            try: st.session_state.traffic_writer.close()
                            except: pass
                        st.session_state.traffic_reader = None
                        st.session_state.traffic_writer = None
                        st.session_state.traffic_target = result
                        st.session_state.traffic_data = deque(maxlen=90)
                        st.session_state.traffic_running = False
                        st.session_state.traffic_last_name = result["name"]
                        st.success(f"Found: {result['name']}")
                        st.rerun()
                    else:
                        st.error(f"OLT '{result['olt_name']}' not in config")
                else:
                    st.error(f"'{search_name}' not found")

# Auto-rerun
if st.session_state.traffic_running and st.session_state.traffic_target:
    time.sleep(2)
    st.rerun()
