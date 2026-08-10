import streamlit as st
import pandas as pd
import time
import sys
import os
from datetime import datetime
import urllib.request
import urllib.error
import re

# Add parent directory to path to import the router API
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unified_router_api import UnifiedRouterAPI

# ========== MAC VENDOR LOOKUP ==========
@st.cache_data(ttl=86400)
def get_mac_vendor(mac_address):
    """Look up vendor for a MAC address using macvendors.com API"""
    if not mac_address or mac_address == 'N/A':
        return "Unknown"
    
    clean_mac = mac_address.replace(':', '').replace('-', '').replace('.', '').upper()
    if len(clean_mac) < 6:
        return "Invalid MAC"
    
    formatted_mac = ':'.join(clean_mac[i:i+2] for i in range(0, 12, 2))
    url = f"https://api.macvendors.com/{formatted_mac}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Python-Mac-Lookup'})
        with urllib.request.urlopen(req, timeout=5) as response:
            vendor = response.read().decode('utf-8')
            return vendor.strip()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "Vendor Not Found"
        elif e.code == 429:
            return "Rate Limited"
        else:
            return f"Error {e.code}"
    except Exception:
        return "Lookup Failed"

def lookup_vendors_for_devices(devices, progress_bar=None):
    """Look up vendors for a list of devices"""
    vendors = {}
    total = len(devices)
    
    for idx, device in enumerate(devices):
        mac = device.get('mac', 'N/A')
        if mac and mac != 'N/A' and mac not in vendors:
            vendor = get_mac_vendor(mac)
            vendors[mac] = vendor
            if vendor != "Rate Limited":
                time.sleep(1.0)
        
        if progress_bar:
            progress_bar.progress((idx + 1) / total, text=f"Looking up vendors... {idx + 1}/{total}")
    
    return vendors


def format_speed_value(rate_value):
    """
    Format speed value intelligently:
    - If >= 1 Mbps, display in Mbps with 0 decimal places
    - If < 1 Mbps (but > 0), display in Kbps
    - If None or N/A, return 'N/A'
    """
    if rate_value is None or rate_value == 'N/A' or rate_value == "N/A" or rate_value == '':
        return "N/A"
    
    try:
        val = float(rate_value)
        if val <= 0:
            return "N/A"
        elif val < 1:
            # Convert to Kbps (Mbps * 1000)
            kbps = val * 1000
            return f"{kbps:.0f} Kbps"
        else:
            return f"{val:.0f} Mbps"
    except (ValueError, TypeError):
        return str(rate_value)


st.set_page_config(
    page_title="Access ONU/ONT", 
    page_icon="🔧", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .success-box {
        background-color: #d4edda;
        border-left: 4px solid #28a745;
        padding: 0.75rem;
        border-radius: 0.25rem;
        margin: 0.5rem 0;
        color: #155724;
    }
    .error-box {
        background-color: #f8d7da;
        border-left: 4px solid #dc3545;
        padding: 0.75rem;
        border-radius: 0.25rem;
        margin: 0.5rem 0;
        color: #721c24;
    }
    .info-box {
        background-color: #d1ecf1;
        border-left: 4px solid #17a2b8;
        padding: 0.75rem;
        border-radius: 0.25rem;
        margin: 0.5rem 0;
        color: #0c5460;
    }
    .warning-box {
        background-color: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 0.75rem;
        border-radius: 0.25rem;
        margin: 0.5rem 0;
        color: #856404;
    }
    .metric-card {
        background-color: #262730;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #4a4a5a;
        margin: 0.5rem 0;
    }
    .metric-card .metric-label {
        font-size: 0.85rem;
        color: #9a9ac0;
    }
    .metric-card .metric-value {
        font-size: 1.1rem;
        font-weight: bold;
        margin-top: 0.3rem;
        color: #ffffff;
    }
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.5rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: bold;
    }
    .status-online { background-color: #28a745; color: white; }
    .status-offline { background-color: #dc3545; color: white; }
    .status-unknown { background-color: #6c757d; color: white; }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="main-header">🔧 Access Clients ONU/ONT</div>', unsafe_allow_html=True)

# Initialize session state
if 'router_connected' not in st.session_state:
    st.session_state.router_connected = False
if 'router_instance' not in st.session_state:
    st.session_state.router_instance = None
if 'wifi_cache' not in st.session_state:
    st.session_state.wifi_cache = None
if 'last_scan_time' not in st.session_state:
    st.session_state.last_scan_time = None
if 'vendor_cache' not in st.session_state:
    st.session_state.vendor_cache = {}

# Check if we have device data
if 'onu_access_data' not in st.session_state or not st.session_state.onu_access_data:
    st.warning("🚧 No device selected. Please search for a client on the main page first.")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.info("👈 **How to get started:**\n\n1. Go to the main page\n2. Search for a client using their name\n3. Click **Access clients ONU/ONT** when the CPE IP is reachable")
    st.stop()

# Get device data
data = st.session_state.onu_access_data

# Extract required fields
smartolt_name = data.get('smartolt_name', '')
device_vendor = data.get('device_vendor', '').upper()
device_type = data.get('device_type', 'N/A')
status = data.get('status', 'N/A')
cpe_ip = data.get('cpe_ip', '')

# Validate required fields
if not cpe_ip:
    st.error("❌ CPE IP address not found in device data. Cannot connect to router.")
    st.stop()

# Determine status badge
status_lower = status.lower()
if status_lower == 'online':
    status_badge = '<span class="status-badge status-online">🟢 ONLINE</span>'
elif status_lower == 'offline':
    status_badge = '<span class="status-badge status-offline">🔴 OFFLINE</span>'
else:
    status_badge = '<span class="status-badge status-unknown">⚪ UNKNOWN</span>'

# ==================== DEVICE INFORMATION SECTION ====================
st.markdown("---")
st.subheader("📋 Device Information")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">SmartOLT Name</div>
        <div class="metric-value">{smartolt_name or "N/A"}</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Device Vendor</div>
        <div class="metric-value">{device_vendor}</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">CPE IP Address</div>
        <div class="metric-value">{cpe_ip}</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Status</div>
        <div class="metric-value">{status_badge}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ==================== ROUTER TYPE DETECTION ====================
st.subheader("🔍 Router Type Detection")

if device_vendor and 'HUAWEI' in device_vendor.upper():
    router_type = "huawei"
    onu_username = None
    st.markdown("""
    <div class="info-box">
        <strong>✅ Huawei Router Detected</strong><br>
        ⚠️NOTE: THIS WILL TAKE LONGER THAN ZTE.
    </div>
    """, unsafe_allow_html=True)
    
elif device_vendor and 'ZTE' in device_vendor.upper():
    router_type = "zte"
    onu_username = smartolt_name
    if not onu_username:
        st.warning("⚠️ SmartOLT Name is missing. WAN access may not work properly.")
    st.markdown(f"""
    <div class="info-box">
        <strong>✅ ZTE Router Detected</strong><br>
        WAN access will be automatically enabled/disabled using SmartOLT Name.
    </div>
    """, unsafe_allow_html=True)
    
else:
    st.error(f"❌ Unsupported device vendor: {device_vendor}. Only HUAWEI and ZTE are supported. If this is a Huawei device, the MAC vendor API may have returned an OEM name.")
    st.stop()

st.markdown("---")

# ==================== CONNECTION SETTINGS ====================
st.subheader("🔌 Connection Management")

status_col1, status_col2, status_col3 = st.columns([1, 1, 2])

with status_col1:
    if st.session_state.router_connected:
        st.success("🟢 **Status:** Connected")
    else:
        st.warning("⚪ **Status:** Not Connected")

with status_col2:
    if st.session_state.router_connected and st.session_state.router_instance:
        st.info(f"📡 **Router:** {device_vendor} ({router_type.upper()})")

col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    if not st.session_state.router_connected:
        if st.button("🔌 Connect to Router", type="primary", use_container_width=True):
            with st.spinner(f"Connecting to {router_type.upper()} router at {cpe_ip}..."):
                try:
                    router = UnifiedRouterAPI(
                        router_ip=cpe_ip,
                        router_type=router_type,
                        onu_username=onu_username,
                        verbose=True,
                        headless=True
                    )
                    if router.login():
                        st.session_state.router_instance = router
                        st.session_state.router_connected = True
                        st.success(f"✅ Successfully connected to {device_vendor} router at {cpe_ip}")
                        st.rerun()
                    else:
                        st.error("❌ Failed to connect to router. Check credentials and network connectivity.")
                except Exception as e:
                    st.error(f"❌ Connection error: {str(e)}")
    else:
        if st.button("🔌 Disconnect", use_container_width=True):
            if st.session_state.router_instance:
                st.session_state.router_instance.close()
            st.session_state.router_instance = None
            st.session_state.router_connected = False
            st.session_state.wifi_cache = None
            st.session_state.last_scan_time = None
            st.session_state.vendor_cache = {}
            st.success("✅ Disconnected successfully")
            st.rerun()

st.markdown("---")

# ==================== OPERATIONS SECTION ====================
if st.session_state.router_connected and st.session_state.router_instance:
    router = st.session_state.router_instance
    
    st.subheader("🛠️ Router Management Operations")
    
    tab1, tab2, tab3 = st.tabs(["📱 Connected Devices", "📡 WiFi Settings", "⚙️ Change WiFi"])
    
    # ==================== TAB 1: SCAN DEVICES ====================
    with tab1:
        st.markdown("### 📱 Network Device Scanner")
        st.markdown("Scan your network to see all devices currently connected to this router.")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            scan_button = st.button("🔍 Start Scan", type="primary", use_container_width=True)
        with col2:
            if st.session_state.last_scan_time:
                st.caption(f"Last scan: {st.session_state.last_scan_time}")
        with col3:
            lookup_vendors = st.checkbox("Lookup MAC Vendors", value=True, 
                                        help="Use macvendors.com API to identify device manufacturers (slower)")
        
        if scan_button:
            with st.spinner("Scanning for connected devices... This may take a moment..."):
                result = router.scan_devices()
                
                if result.get("success"):
                    devices = result.get("devices", [])
                    st.session_state.last_scan_time = datetime.now().strftime("%H:%M:%S")
                    
                    # Summary metrics
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Devices", result.get('total_count', 0))
                    with col2:
                        st.metric("🟢 Online", result.get('online_count', 0))
                    with col3:
                        st.metric("⚫ Offline", result.get('offline_count', 0))
                    with col4:
                        wifi_count = len([d for d in devices if d.get('port_type') == 'WIFI'])
                        st.metric("📡 WiFi", wifi_count)
                    
                    if devices:
                        # Look up MAC vendors if enabled
                        vendor_map = {}
                        if lookup_vendors:
                            with st.spinner("Looking up device manufacturers via MAC address..."):
                                progress_bar = st.progress(0)
                                vendor_map = lookup_vendors_for_devices(devices, progress_bar)
                                st.session_state.vendor_cache.update(vendor_map)
                                progress_bar.empty()
                        
                        # Build table data
                        df_data = []
                        for device in devices:
                            mac = device.get('mac', 'N/A')
                            vendor = vendor_map.get(mac, st.session_state.vendor_cache.get(mac, ''))
                            
                            row = {
                                "Status": "🟢 Online" if device.get('status') == 'Online' else "⚫ Offline",
                                "Hostname": (device.get('hostname', 'Unknown') or 'Unknown')[:30],
                                "IP Address": device.get('ip', 'N/A'),
                                "MAC Address": mac,
                                "Manufacturer": vendor if vendor else "—",
                                "Connection": device.get('port_type', 'N/A'),
                            }
                            
                            # Add ZTE-specific WiFi capacity fields
                            if router_type == 'zte':
                                tx_rate = device.get('tx_rate', 'N/A')
                                rx_rate = device.get('rx_rate', 'N/A')
                                
                                row["WiFi Capacity (Upload)"] = format_speed_value(tx_rate)
                                row["WiFi Capacity (Download)"] = format_speed_value(rx_rate)
                                
                                # Signal strength
                                signal = device.get('signal_strength', 'N/A')
                                if signal and signal != 'N/A' and signal != "N/A":
                                    try:
                                        signal_val = int(signal)
                                        row["Signal"] = f"{signal_val}%"
                                    except (ValueError, TypeError):
                                        row["Signal"] = str(signal)
                                else:
                                    row["Signal"] = "N/A"
                            else:
                                # Huawei signal
                                signal = device.get('signal_strength', 'N/A')
                                row["Signal"] = f"{signal}%" if signal and signal != 'N/A' else "N/A"
                            
                            df_data.append(row)
                        
                        df = pd.DataFrame(df_data)
                        
                        # Configure column order based on router type
                        if router_type == 'zte':
                            column_order = ["Status", "Hostname", "IP Address", "MAC Address", "Manufacturer", 
                                          "Connection", "WiFi Capacity (Upload)", "WiFi Capacity (Download)", "Signal"]
                        else:
                            column_order = ["Status", "Hostname", "IP Address", "MAC Address", "Manufacturer",
                                          "Connection", "Signal"]
                        
                        # Only show columns that exist
                        show_columns = [c for c in column_order if c in df.columns]
                        st.dataframe(df[show_columns], use_container_width=True, hide_index=True)
                        
                        # Export option
                        csv = df[show_columns].to_csv(index=False)
                        st.download_button(
                            label="📥 Export to CSV",
                            data=csv,
                            file_name=f"connected_devices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
                    else:
                        st.info("📭 No devices found on the network.")
                else:
                    st.error(f"❌ Scan failed: {result.get('error', 'Unknown error')}")
    
    # ==================== TAB 2: VIEW WIFI SETTINGS ====================
    with tab2:
        st.markdown("### 📡 Current WiFi Configuration")
        
        if st.button("📡 Fetch Current Settings", type="primary", use_container_width=True):
            with st.spinner("Retrieving current WiFi configuration..."):
                result = router.get_wifi_details()
                
                if result.get("success"):
                    st.session_state.wifi_cache = result
                    st.success("✅ WiFi settings retrieved successfully")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**📡 SSID:**")
                        st.code(result.get('ssid', 'N/A'), language=None)
                    with col2:
                        st.markdown("**🔐 Password:**")
                        st.code(result.get('password', 'N/A'), language=None)
                else:
                    st.error(f"❌ Failed to retrieve WiFi settings: {result.get('error', 'Unknown error')}")
        
        if st.session_state.wifi_cache:
            st.markdown("---")
            st.markdown("### 📋 Cached Configuration")
            wifi = st.session_state.wifi_cache
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("SSID", value=wifi.get('ssid', 'N/A'), disabled=True, key="cached_ssid")
            with col2:
                st.text_input("Password", value=wifi.get('password', 'N/A'), disabled=True, type="password", key="cached_password")
            st.caption("ℹ️ This is the last retrieved configuration. Click 'Fetch Current Settings' to refresh.")
    
    # ==================== TAB 3: CHANGE WIFI ====================
    with tab3:
        st.markdown("### ⚙️ Change WiFi Configuration")
        st.warning("⚠️ **Warning:** Changing WiFi settings will disconnect all connected devices!")
        
        with st.expander("🔐 Password Requirements"):
            st.markdown("""
            - Minimum **8 characters** length
            - Can contain letters, numbers, and special characters
            - Recommended to use a mix of uppercase, lowercase, numbers, and symbols
            """)
        
        col1, col2 = st.columns(2)
        with col1:
            new_ssid = st.text_input("📡 New SSID", placeholder="Enter new WiFi name", key="new_ssid_input")
        with col2:
            new_password = st.text_input("🔐 New Password", placeholder="Enter new password (min 8 chars)", 
                                        type="password", key="new_password_input")
        
        if new_password:
            strength = "Weak"
            color = "red"
            if len(new_password) >= 12:
                strength = "Strong"; color = "green"
            elif len(new_password) >= 8:
                strength = "Medium"; color = "orange"
            st.markdown(f"**Password strength:** <span style='color:{color}'>{strength}</span>", unsafe_allow_html=True)
        
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("💾 Apply Changes", type="primary", use_container_width=True):
                if not new_ssid and not new_password:
                    st.error("❌ Please enter at least one change")
                elif new_password and len(new_password) < 8:
                    st.error("❌ Password must be at least 8 characters")
                else:
                    with st.spinner("Applying WiFi configuration changes..."):
                        result = router.change_wifi(
                            new_ssid if new_ssid else None,
                            new_password if new_password else None
                        )
                        if result.get("success"):
                            st.success("✅ WiFi settings changed successfully!")
                            if result.get("ssid_changed"):
                                st.info(f"📡 **New SSID:** `{result.get('new_ssid')}`")
                            if result.get("password_changed"):
                                st.info(f"🔐 **New Password:** `{result.get('new_password')}`")
                            st.warning("⚠️ **Important:** All devices will need to reconnect with the new credentials.")
                            st.balloons()
                            st.session_state.wifi_cache = None
                            st.rerun()
                        else:
                            st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")

else:
    st.info("👈 **Not Connected**")
    st.markdown("""
    ### 🔌 How to Connect:
    1. Review the **Device Information** above
    2. Click **Connect to Router** button
    
    ### 💡 Notes:
    - Please always disconnect from the router when you are done
    - Huawei devices take longer than ZTE devices so please be patient
    - Huawei devices encrypt their password so you can't see existing passwords but you can change them
    - If the device resets, kindly forward it to NOC if it's a ZTE device. If it's Huawei there is nothing NOC can do remotely
    - ZTE devices will only show you devices connected over Wi-Fi, not LAN or Extenders
    """)

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("## ℹ️ About")
    st.markdown("""
    This tool allows remote management of Huawei and ZTE routers/ONUs.
    
    ---
    
    ### ✅ Supported Operations
    
    | Operation | Description |
    |-----------|-------------|
    | 📱 Scan Devices | List all connected devices |
    | 📡 View WiFi | See current SSID & password |
    | ⚙️ Change WiFi | Update SSID and/or password |
    
    ---
    
    ### 📡 Supported Devices
    
    | Vendor | Model |
    |--------|-------|
    | Huawei | HG8546M |
    | ZTE | F460 |
    
    ---
    
    ### 📊 Session Info
    """)
    
    if st.session_state.router_connected:
        st.success("🟢 Active Session")
        st.caption(f"Router: {device_vendor}")
        st.caption(f"IP: {cpe_ip}")
    else:
        st.warning("⚪ No Active Session")
    
    st.markdown("---")
    st.caption(f"Page loaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")