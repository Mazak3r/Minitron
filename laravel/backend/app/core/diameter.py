"""
Diameter (Radius Manager) scraping — supports Primary + Backup URLs.
"""
import os
import re
from datetime import datetime, timedelta
from typing import Optional
import requests
import urllib3
from bs4 import BeautifulSoup

from backend.app.config import (
    DIAMETER_URL_LIST, DIAMETER_DOMAIN, DIAMETER_PATH, PHPSESSID_FILE
)
from backend.app.core.logger import debug_print
from backend.app.core.utils import ping_ip, is_account_expired
from backend.app.core.radio import get_mac_vendor


def get_phpsessid_from_env() -> str:
    session = os.environ.get("PHPSESSID", "")
    if session:
        return session
    try:
        if os.path.exists(PHPSESSID_FILE):
            with open(PHPSESSID_FILE, "r") as f:
                session = f.read().strip()
                if session:
                    return session
    except Exception:
        pass
    return ""


def create_diameter_session(session_id):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.verify = False
    session.encoding = "utf-8"
    
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry_strategy = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["HEAD", "GET", "OPTIONS"])
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        "Referer": DIAMETER_URL_LIST[0],
        "Origin": DIAMETER_URL_LIST[0],
        "Host": DIAMETER_DOMAIN if DIAMETER_DOMAIN else "41.79.65.47",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "text/html; charset=utf-8",
    })
    cookie_path = DIAMETER_PATH if DIAMETER_PATH else "/"
    session.cookies.set("PHPSESSID", session_id, path=cookie_path)
    return session


def parse_edit_user_page(html_content, username):
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="ignore")
    if "Secure login" in html_content:
        return {"found": False, "username": username, "login_page": True}
    if "User not found!" in html_content:
        return {"found": False, "username": username, "user_not_found": True}

    soup = BeautifulSoup(html_content, "html.parser")
    user_data = {
        "found": True, "username": username, "phone": "N/A", "mobile": "N/A",
        "first_name": "N/A", "last_name": "N/A", "email": "N/A", "address": "N/A",
        "city": "N/A", "state": "N/A", "country": "N/A", "company": "N/A",
        "service_plan": "N/A", "expiry_date": "N/A", "cpe_ip": "N/A", "cm_ip": "N/A",
        "cm_mac": "N/A", "nas_bts": "N/A", "registered_date": "N/A", "last_logoff": "N/A",
        "session_ip": "N/A", "mac_address": "N/A", "is_online": False, "status": "OFFLINE",
    }

    fields = ["phone", "mobile", "firstname", "lastname", "email", "address", "city",
              "state", "country", "company", "staticipcpe", "staticipcm", "cmmac",
              "createdon", "lastlogoff", "expiration"]
    for field in fields:
        input_elem = soup.find("input", {"name": field})
        if input_elem and input_elem.get("value"):
            val = input_elem.get("value").strip()
            if field == "firstname": user_data["first_name"] = val
            elif field == "lastname": user_data["last_name"] = val
            elif field == "staticipcpe": user_data["cpe_ip"] = val
            elif field == "staticipcm": user_data["cm_ip"] = val
            elif field == "cmmac": user_data["cm_mac"] = val
            elif field == "createdon": user_data["registered_date"] = val
            elif field == "lastlogoff": user_data["last_logoff"] = val
            elif field == "expiration": user_data["expiry_date"] = val
            else: user_data[field] = val

    # Fallbacks for Last Logoff, MAC, NAS
    try:
        for td in soup.find_all("td", class_="normal"):
            div = td.find("div", align="right")
            if div and "Last logoff:" in div.get_text():
                next_td = td.find_next_sibling("td", class_="normal")
                if next_td:
                    v = next_td.get_text(strip=True)
                    if v and v != "0000-00-00 00:00:00" and user_data.get("last_logoff") == "N/A":
                        user_data["last_logoff"] = v
                    break
    except Exception: pass

    try:
        for td in soup.find_all("td", class_="normal"):
            div = td.find("div", align="right")
            if div and "Caller ID:" in div.get_text():
                next_td = td.find_next_sibling("td", class_="normal")
                if next_td:
                    inner = next_td.find("div")
                    if inner and inner.get("onClick"):
                        m = re.search(r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}", inner.get("onClick"))
                        if m: user_data["mac_address"] = m.group(0)
                    if user_data["mac_address"] == "N/A":
                        a = next_td.find("a")
                        if a and re.match(r"[0-9a-fA-F:]{17}", a.get_text(strip=True)):
                            user_data["mac_address"] = a.get_text(strip=True)
                    break
    except Exception: pass

    try:
        for td in soup.find_all("td", class_="normal"):
            div = td.find("div", align="right")
            if div and "NAS:" in div.get_text():
                next_td = td.find_next_sibling("td", class_="normal")
                if next_td:
                    nas = next_td.find("a")
                    if nas: user_data["nas_bts"] = nas.get_text(strip=True)
                    else:
                        txt = next_td.get_text(strip=True)
                        if txt and txt.lower() not in ["n/a", "", "&nbsp;"]: user_data["nas_bts"] = txt
                    break
    except Exception: pass

    svc = soup.find("select", {"name": "srvid"})
    if svc:
        opt = svc.find("option", selected=True)
        if opt: user_data["service_plan"] = opt.get_text(strip=True)

    try:
        for td in soup.find_all("td", string=re.compile(r"Connection status:", re.IGNORECASE)):
            row = td.find_parent("tr")
            if row:
                cells = row.find_all("td")
                for i, c in enumerate(cells):
                    if "Connection status:" in c.get_text() and i + 1 < len(cells):
                        tbl = cells[i + 1].find("table")
                        if tbl and tbl.get("bgcolor", "").lower() in ["#95b8ff", "95b8ff"]:
                            user_data["is_online"] = True
                        break
            break
    except Exception: pass

    user_data["status"] = "ONLINE" if user_data["is_online"] else "OFFLINE"
    return user_data


def parse_traffic_report(html_content, username, from_date):
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html_content, "html.parser")
    if "Secure login" in html_content or "login" in html_content.lower():
        return "N/A", "N/A", "N/A", False
    if "no records found" in html_content.lower() or "no data" in html_content.lower():
        return "N/A", "N/A", "N/A", False

    rows = []
    for r in soup.find_all("tr", class_="normal"):
        if r.get("bgcolor", "").upper() != "#EAF1FF":
            cells = r.find_all("td")
            if len(cells) >= 15:
                rows.append(r)

    session_ip, mac, nas = "N/A", "N/A", "N/A"
    for row in rows:
        cells = row.find_all("td")
        if len(cells) > 12 and cells[12].get_text(strip=True).lower() not in ["n/a", "", "--"]:
            session_ip = cells[12].get_text(strip=True)
        if len(cells) > 13 and cells[13].get_text(strip=True).lower() not in ["n/a", "", "--"]:
            mac = cells[13].get_text(strip=True)
        if len(cells) > 14:
            nas_link = cells[14].find("a")
            val = nas_link.get_text(strip=True) if nas_link else cells[14].get_text(strip=True)
            if val.lower() not in ["n/a", "", "--"]: nas = val
        if session_ip != "N/A" or mac != "N/A" or nas != "N/A":
            return session_ip, mac, nas, True
    return "N/A", "N/A", "N/A", False


def get_diameter_traffic_data(session, base_url, username, last_logoff=None, expiry_date=None, registered_date=None):
    try:
        start_date = None
        if last_logoff and last_logoff != "N/A":
            try: start_date = datetime.strptime(last_logoff.split()[0], "%Y-%m-%d")
            except Exception: pass
        if not start_date and expiry_date and expiry_date != "N/A":
            try: start_date = datetime.strptime(expiry_date.split()[0], "%Y-%m-%d")
            except Exception: pass
        if not start_date: start_date = datetime.now()

        if start_date.year < 2024:
            return {"session_ip": "N/A", "mac_address": "N/A", "nas_bts": "N/A", "traffic_date": None}

        end_date = datetime.now()
        if registered_date and registered_date != "N/A":
            try: end_date = datetime.strptime(registered_date.split()[0], "%Y-%m-%d")
            except Exception: pass

        max_days = (start_date - end_date).days
        if max_days < 0 or max_days > 365: max_days = 10

        for day_offset in range(max_days + 1):
            search_date = start_date - timedelta(days=day_offset)
            from_date = search_date.strftime("%Y-%m-%d")
            url = f"{base_url}?cont=detailed_traffic_report&username={username}&fromdate={from_date}&framedip=%&stationid=%&nasid=&apid="
            try:
                resp = session.get(url, timeout=60)
                resp.encoding = "utf-8"
                if resp.status_code != 200: continue
                if "Secure login" in resp.text or "txt_Username" in resp.text:
                    return {"session_ip": "N/A", "mac_address": "N/A", "nas_bts": "N/A", "traffic_date": None}
                sip, mac, nas, found = parse_traffic_report(resp.text, username, from_date)
                if found:
                    return {"session_ip": sip, "mac_address": mac, "nas_bts": nas, "traffic_date": from_date}
            except requests.exceptions.ReadTimeout:
                pass
            except Exception:
                pass
        return {"session_ip": "N/A", "mac_address": "N/A", "nas_bts": "N/A", "traffic_date": None}
    except Exception:
        return {"session_ip": "N/A", "mac_address": "N/A", "nas_bts": "N/A", "traffic_date": None}


def get_diameter_user_data(username, session_id):
    if not session_id:
        return None
    diameter_username = username.replace(" ", "_")
    
    for url_index, try_url in enumerate(DIAMETER_URL_LIST):
        label = "PRIMARY" if url_index == 0 else f"BACKUP-{url_index}"
        debug_print(f"[DIAMETER] Trying {label}: {try_url}", "INFO")
        session = create_diameter_session(session_id)
        
        try:
            resp = session.get(f"{try_url}?cont=list_users", timeout=60)
            if resp.status_code != 200: continue

            resp = session.get(f"{try_url}?cont=edit_user&username={diameter_username}", timeout=60, allow_redirects=True)
            if resp.status_code != 200 or "Secure login" in resp.text: continue

            user_data = parse_edit_user_page(resp.text, diameter_username)
            if user_data.get("user_not_found", False): return user_data

            if not user_data.get("is_online", False):
                traffic = get_diameter_traffic_data(session, try_url, diameter_username,
                                                    user_data.get("last_logoff"),
                                                    user_data.get("expiry_date"),
                                                    user_data.get("registered_date"))
                if traffic:
                    user_data["session_ip"] = traffic.get("session_ip", "N/A")
                    if user_data.get("mac_address", "N/A") == "N/A":
                        user_data["mac_address"] = traffic.get("mac_address", "N/A")
                    if user_data.get("nas_bts", "N/A") == "N/A":
                        user_data["nas_bts"] = traffic.get("nas_bts", "N/A")
                    user_data["traffic_date"] = traffic.get("traffic_date")

            ping_ok = False
            if user_data["cpe_ip"] != "N/A":
                ping_ok = ping_ip(user_data["cpe_ip"])
            user_data["ping_reachable"] = ping_ok
            user_data["expired"] = is_account_expired(user_data["expiry_date"])
            
            debug_print(f"[DIAMETER] Success via {label}", "SUCCESS")
            return user_data

        except Exception as e:
            debug_print(f"[DIAMETER] {label} failed: {e}", "WARNING")
            continue
        finally:
            session.close()
    
    debug_print("[DIAMETER] All URLs failed", "ERROR")
    return None


def format_network_analysis(diameter_data):
    if not diameter_data:
        return ""
    if diameter_data.get("user_not_found", False):
        return "\n## ⚠️ User Not Found\n\n**This PPPoE username does not exist in the system. Please confirm the correct PPPoE username with the client.**\n\nThe username you searched for could not be found in the Diameter database.\n"
    if diameter_data.get("login_page", False):
        return "\n## ⚠️ Network Analysis Unavailable\n\n**Session Expired:** The Diameter session is invalid. Please refresh your PHPSESSID.\n"
    if not diameter_data.get("found", False):
        return ""
    
    status_emoji = "🟢" if diameter_data.get("is_online") else "🔴"
    ping_emoji = "🟢" if diameter_data.get("ping_reachable") else "🔴"
    expiry_emoji = "🔴" if diameter_data.get("expired") else "🟢"
    full_name = f"{diameter_data.get('first_name', '')} {diameter_data.get('last_name', '')}".strip()
    if not full_name or full_name == "N/A N/A": full_name = diameter_data.get("username", "N/A")
    
    traffic_info = ""
    if diameter_data.get("traffic_date"):
        traffic_info = f"\n| **Traffic Data From** | - | `{diameter_data.get('traffic_date')}` |"
        
    return f"""
## Network Analysis

| Metric | Status | Details |
|--------|--------|---------|
| **Full Name** | - | `{full_name}` |
| **Email** | - | `{diameter_data.get('email', 'N/A')}` |
| **Phone** | - | `{diameter_data.get('phone', 'N/A')}` |
| **Diameter Status** | {status_emoji} {diameter_data.get('status', 'N/A')} | - |
| **NAS/BTS** | - | `{diameter_data.get('nas_bts', 'N/A')}` |
| **Session IP** | - | `{diameter_data.get('session_ip', 'N/A')}` |
| **CPE IP** | - | `{diameter_data.get('cpe_ip', 'N/A')}` |
| **MAC Address** | - | `{diameter_data.get('mac_address', 'N/A')}` {get_mac_vendor(diameter_data.get('mac_address', ''))} |
| **Ping (CPE IP)** | {ping_emoji} {"Reachable" if diameter_data.get('ping_reachable') else "Unreachable"} | via `{diameter_data.get('ping_ip', 'N/A')}` |
| **Account Status** | {expiry_emoji} {"EXPIRED" if diameter_data.get('expired') else "Active"} | Expires: `{diameter_data.get('expiry_date', 'N/A')}` |
| **Service Plan** | - | `{diameter_data.get('service_plan', 'N/A')}` |
| **Registered Date** | - | `{diameter_data.get('registered_date', 'N/A')}` |
| **Last Logoff** | - | `{diameter_data.get('last_logoff', 'N/A')}` |{traffic_info}
| **Address** | - | `{diameter_data.get('address', 'N/A')}` |
| **City/State** | - | `{diameter_data.get('city', 'N/A')}, {diameter_data.get('state', 'N/A')}` |
"""
