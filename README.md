# Minitron

**Network Diagnostic Automation Platform for ISPs**

MINITRON connects to ZTE GPON/EPON OLTs and CDATA FSeries OLTs via telnet to provide real-time ONU diagnostics, automated decision-making, and WiFi management.

---

## How It Works

### 1. Search Pipeline.

When a name is entered into the search bar, MINITRON searches in this order:

1. **ZTE OLT Database** (`ZTE OLT.csv`) — Proctor CSV with OLT, Board, Port, ONU ID mappings
2. **CDATA FSeries OLT** — Live telnet scan and persistent state (`onu_status.json`)
3. **Billing Server (RADIUS)** — Account lookup via PHP session

If the name is **not found** on any OLT database but exists on the billing server:
- If the MAC address belongs to a **radio device** (Ubiquiti or Cambium), a radio-specific troubleshooting response is shown
- Otherwise, the user is prompted to obtain the GPON serial number for manual troubleshooting

If the name is **not found anywhere**, the user is informed the name doesn't exist in the system.

### 2. ZTE OLT Diagnostic Flow

When a name is found in the ZTE database, the following happens:

1. **OLT, PON Type, Board, Port, and ONU ID** are extracted from the CSV
2. **Reachability check** — verifies the OLT is accessible before proceeding
3. **Telnet connection** via `telnetlib3` with asynchronous operations running multiple checks simultaneously
4. The following details are extracted from the OLT:

| Detail | Source Command |
|--------|---------------|
| ONU Status (Online/LOS/DyingGasp/Offline) | `show gpon onu state` |
| Serial Number | `show gpon onu detail-info` |
| Optical Signal (Rx Power dBm) | `show pon power attenuation` |
| Uptime / Online Duration | `show gpon onu detail-info` |
| Last Downtime Cause | `show gpon onu detail-info` (history table) |
| Last Downtime Time | `show gpon onu detail-info` |

### 3. Automated Decision Engine

The system makes automated decisions based on statistical analysis of the PON port state.

#### How It Works

Each ZTE GPON OLT port's ONUs are grouped into **4 categories**:
- **Online** — working ONUs
- **LOS** — Loss of Signal
- **Dying Gasp** — Power failure
- **Offline** — Other offline states

The ratios of these categories are calculated as percentages and **rounded to the nearest 10** (e.g., 10%, 20%, 30%... 100%). This reduces the infinite possible outputs to a manageable set.

Additionally, **5 flags** are tracked as binary (1 or 0):

| Flag | Meaning | Trigger Condition |
|------|---------|-------------------|
| **MST** | Splitter/MST Issue | 2+ ONUs go down within the same 2-minute window |
| **MPI** | Major Port Issue | 80%+ of ONUs offline or port empty |
| **HL** | High Optical Power Loss | Average port signal below -28 dBm |
| **JCU** | Just Came Up | 3+ ONUs came online within 5 minutes |
| **JWD** | Just Went Down | 3+ ONUs went offline within 5 minutes |

#### The Decision Matrix

With:
- 4 categories in 10% increments = 11 possible values each
- 5 binary flags (2⁵ = 32 combinations)
- **Total: ~9,512 possible scenarios** are accounted for

Each scenario maps to one of **14 possible responses** in `tron.json`, including:

- PON Port Outage
- Major Port Failure
- Splitter/MST Failure
- High Optical Power Loss (port-wide)
- Isolated ONU Issue (single client)
- General Downtime

This means every possible port state has a pre-determined response — the nature of an outage is detected automatically.

#### Example Decision

Port Stats: 10% Online, 80% LOS, 10% Dying Gasp, 0% Offline
Flags: MST=1, MPI=1, HL=0, JCU=0, JWD=0
→ Response: "Multiple clients are down with LOS and Power Failures.
There is a suspected MST/splitter issue with major port impact."

---

## Architecture

### Server
- **Python 3.11+** with **Streamlit** for the web interface
- Runs on Ubuntu Server (LAN deployment)
- Direct telnet connections to OLTs (no SSH tunnels required for LAN)

### Key Files

| File | Purpose |
|------|---------|
| `Home.py` | Main Streamlit app — search, diagnostics, decision engine |
| `pages/2_DumbOLT.py` | CDATA FSeries EPON monitor — login, rename, reboot, delete ONUs |
| `pages/1_Access_ONU.py` | Router WiFi management (Huawei ONUs) |
| `config.json` | All configuration (OLT IPs, credentials, CSV paths) |
| `testo.json` | Port analysis database — 9,512 scenarios mapped to responses |
| `onu_status.json` | CDATA ONU persistent state |
| `ZTE OLT.csv` | Proctor CSV — ONU name to OLT/Board/Port mapping |

### Connection
- **Direct telnet** to OLTs on port 23
- `check_reachability()` verifies OLT is online before connecting
- `telnetlib3` for asynchronous non-blocking operations

### Diameter/RADIUS
- Connects to Radius Manager web interface via HTTP
- Uses PHPSESSID cookie for authentication
- Extracts: account status, CPE IP, MAC address, service plan, expiry date

---

## Pages

- Home (Search)
Main diagnostic interface. Enter a name to search across all databases and get automated diagnostic reports with network analysis.

## DumbOLT (CDATA FSeries)
- EPON OLT monitor for CDATA devices. Features:

- Live port scanning with ONU status and signal

- MAC address learning and name resolution

- Reboot and delete ONUs

- Persistent state tracking

## Access ONU

Direct access to the client's router for WiFi management.

## Supported Devices
- Huawei HG8546M GPON ONUs

- ZTE F660 GPON ONUs (via unified_router_api.py)

Access Conditions
Button appears when:

- CPE IP is ping reachable

- CPE IP is available from Diameter

- MAC vendor is Huawei/GoodMan/Foxconn OR serial prefix is ZTE for GPON

Features

- Device scan: List all connected devices

- WiFi management: View and change SSID/password

- WAN management: Enable/disable WAN access on ONU

Connection

- Selenium WebDriver (Chrome headless) to automate router web interface

- HTTP connection to CPE IP address

## How Decisions Are Made
The decision engine is purely statistical. By rounding port percentages to 10s and using binary flags, every possible port state maps to a known scenario. The testo.json file contains all 9,512 scenarios with their corresponding human-readable responses.

No AI, no machine learning — just deterministic pattern matching against a complete decision matrix.



## API Backdoor

A standalone REST API server that exposes MINITRON's search and management functionality over HTTP.

### Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/health` | No | Health check |
| GET | `/search/{name}` | Yes | Full search pipeline (same as Home.py) |
| GET | `/traffic/{name}` | Yes | Single traffic snapshot (Mbps) |
| GET | `/traffic/stream/{name}` | Yes | 60-second live traffic stream (30 samples) |
| GET | `/onu/scan?username=...` | Yes | Scan devices on client's router |
| GET | `/onu/wifi?username=...` | Yes | Get WiFi SSID and password |
| POST | `/onu/wifi/change` | Yes | Change WiFi SSID/password |

### Authentication

- **Bearer token** auto-generated on first run and stored in `config/api_token.txt`
- **IP whitelist** via `config/allowed_ips.txt` (supports `*` for all IPs)
- **Rate limiting**: 30 requests per 60 seconds per IP

### Search Response

Returns JSON with diagnostic report, network analysis (Diameter data), and port analysis:

```
{
  "success": true,
  "source": "csv_olt",
  "report": "ONLINE | Signal: Good...",
  "status": "online",
  "network_analysis": { "html": "...", "diameter_data": {...} },
  "port_analysis": { "html": "...", "raw_debug_data": {...} }
}

##Traffic Response

{
  "success": true,
  "name": "john_doe",
  "olt": "ZTE_OLT1",
  "onu_type": "GPON",
  "input_mbps": 0.25,
  "output_mbps": 18.0
}

##Client Usage

python3 minitron_client.py
Enter username: john_doe           # Full diagnostic
Enter username: john_doe/traffic   # Traffic snapshot
Enter username: john_doe/live      # Live traffic (real-time)
Enter username: john_doe/report    # Initial report
Enter username: john_doe/status    # Account status only

```

---


### Traffic Monitor — Real-Time ONU Bandwidth Graph

Live traffic monitoring for individual ONUs via ZTE OLT telnet.

### Features

- **Search by name**: Proctor CSV lookup to find OLT/Board/Port/ONU ID
- **Live graph**: Auto-refreshing line chart at top of page (persistent across refreshes)
- **60-second streaming**: Polls the OLT every 2 seconds for 30 samples
- **Download/Upload**: Input rate = Upload, Output rate = Download (from ONU perspective)
- **Speed limit line**: Amber horizontal line showing the service plan's maximum speed
- **Service plan detection**: Reads plan from Home.py session state, displays with speed limit
- **Auto-stop**: Clears old data and stops polling when a new name is searched
- **No login required**: Opens instantly when linked from Home.py search results

### Metrics Displayed

| Metric | Source |
|--------|--------|
| Download (Mbps) | `Output rate` from `show interface gpon-onu_...` |
| Upload (Mbps) | `Input rate` from `show interface gpon-onu_...` |
| Speed Limit | Service plan lookup (e.g., FiberMax Home Extra = 75 Mbps) |

### Service Plan Speed Limits

| Plan | Speed (Mbps) |
|------|-------------|
| FiberMax Home | 50 |
| FiberMax LitePlus | 20 |
| FiberMax Home Extra | 75 |
| FiberMax Home Ultra | 100 |
| FiberMax Ultra | 95 |
| FiberMax Max | 60 |
| FiberMax Large | 30 |
| FiberMax Ultimate | 145 |
| FiberMax Ultimate+ | 220 |
| FibreHome-OutsideLagos | 50 |
| FibreHomeExtra-OutsideLagos | 75 |

### Usage

From Home.py search results: click **"📈 View Traffic"** button (appears when CPE IP is ping-reachable).

Or directly on the page: search for an ONU name and click Start.

### Connection

- **Direct telnet** to OLT (LAN deployment)
- Persistent telnet session — connects once, reuses across polls
- Auto-reconnects if session drops
