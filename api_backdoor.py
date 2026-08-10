#!/usr/bin/env python3
"""
MINITRON API Backdoor - SECURED + Network Analysis + Port Analysis + ONU endpoints
"""

import sys
import os
import json
import re
import hashlib
import hmac
import secrets
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import threading
import socket

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import importlib.util
spec = importlib.util.spec_from_file_location("radius_auth", os.path.join(SCRIPT_DIR, "Home.py"))
radius_auth = importlib.util.module_from_spec(spec)
sys.modules["radius_auth"] = radius_auth
spec.loader.exec_module(radius_auth)

search_proctor_csv = radius_auth.search_proctor_csv
clean_search_input_for_smartolt = radius_auth.clean_search_input_for_smartolt
clean_search_input_for_selenium = radius_auth.clean_search_input_for_selenium
search_selenium_olt = radius_auth.search_selenium_olt
cdata_search_and_monitor_port = radius_auth.cdata_search_and_monitor_port
get_cdata_olt_name_by_ip = radius_auth.get_cdata_olt_name_by_ip
cdata_generate_diagnostic_report = radius_auth.cdata_generate_diagnostic_report
get_diameter_user_data = radius_auth.get_diameter_user_data
format_network_analysis = radius_auth.format_network_analysis
identify_radio_type = radius_auth.identify_radio_type
format_radio_message = radius_auth.format_radio_message
format_gpon_request_message = radius_auth.format_gpon_request_message
get_device_type = radius_auth.get_device_type
format_llm_response = radius_auth.format_llm_response
OLT_IPS = radius_auth.OLT_IPS
DIAMETER_BASE_URL = radius_auth.DIAMETER_BASE_URL
DIAMETER_SESSION_ID = radius_auth.get_phpsessid_from_env()
POOR_SIGNAL_THRESHOLD = radius_auth.POOR_SIGNAL_THRESHOLD
connect_to_olt = radius_auth.connect_to_olt
check_reachability = radius_auth.check_reachability
run_async = radius_auth.run_async
debug_print = radius_auth.debug_print
print_debug_header = radius_auth.print_debug_header
print_port_statistics = radius_auth.print_port_statistics
print_status_flags = radius_auth.print_status_flags
print_downtime_info = radius_auth.print_downtime_info
find_port_analysis_match = radius_auth.find_port_analysis_match
format_port_analysis = radius_auth.format_port_analysis
DEBUG_DATA = radius_auth.DEBUG_DATA

from unified_router_api import UnifiedRouterAPI

# ========== SECURITY CONFIG ==========
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'config')
API_TOKEN_FILE = os.path.join(CONFIG_DIR, 'api_token.txt')
ALLOWED_IPS_FILE = os.path.join(CONFIG_DIR, 'allowed_ips.txt')

def load_api_token():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(API_TOKEN_FILE):
            with open(API_TOKEN_FILE, 'r') as f:
                token = f.read().strip()
                if token:
                    os.chmod(API_TOKEN_FILE, 0o600)
                    return token
        token = secrets.token_hex(32)
        with open(API_TOKEN_FILE, 'w') as f:
            f.write(token)
        os.chmod(API_TOKEN_FILE, 0o600)
        print(f"New API token generated")
        return token
    except:
        return secrets.token_hex(32)

def load_allowed_ips():
    default_ips = ['127.0.0.1', '::1']
    try:
        if os.path.exists(ALLOWED_IPS_FILE):
            with open(ALLOWED_IPS_FILE, 'r') as f:
                ips = [line.strip() for line in f.readlines() if line.strip() and not line.strip().startswith('#')]
                if ips:
                    os.chmod(ALLOWED_IPS_FILE, 0o600)
                    return ips
    except:
        pass
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(ALLOWED_IPS_FILE, 'w') as f:
            f.write('# Allowed IPs for MINITRON API\n')
            f.write('# One IP per line\n')
            f.write('# Use * to allow all IPs\n')
            for ip in default_ips:
                f.write(f"{ip}\n")
        os.chmod(ALLOWED_IPS_FILE, 0o600)
    except:
        pass
    return default_ips

API_TOKEN = load_api_token()
ALLOWED_IPS = load_allowed_ips()
RATE_LIMIT_REQUESTS = int(os.environ.get('MINITRON_RATE_LIMIT', '30'))
RATE_LIMIT_WINDOW = 60

rate_limit_store = {}
rate_limit_lock = threading.Lock()

def check_rate_limit(client_ip):
    current_time = datetime.now().timestamp()
    with rate_limit_lock:
        expired = [ip for ip, data in rate_limit_store.items() 
                   if current_time - data['window_start'] > RATE_LIMIT_WINDOW]
        for ip in expired:
            del rate_limit_store[ip]
        if client_ip not in rate_limit_store:
            rate_limit_store[client_ip] = {'window_start': current_time, 'count': 1}
            return True
        client_data = rate_limit_store[client_ip]
        if current_time - client_data['window_start'] > RATE_LIMIT_WINDOW:
            client_data['window_start'] = current_time
            client_data['count'] = 1
            return True
        if client_data['count'] >= RATE_LIMIT_REQUESTS:
            return False
        client_data['count'] += 1
        return True

def verify_token(auth_header):
    if not auth_header:
        return False
    if auth_header.startswith('Bearer '):
        return hmac.compare_digest(auth_header[7:], API_TOKEN)
    return hmac.compare_digest(auth_header, API_TOKEN)

def check_ip_allowed(client_ip):
    if client_ip in ['127.0.0.1', '::1', 'localhost']:
        return True
    if '*' in ALLOWED_IPS:
        return True
    return client_ip in ALLOWED_IPS

def run_search_like_streamlit(search_query):
    debug_print(f"[API] Searching: '{search_query}'", "INFO")
    selenium_search_term = clean_search_input_for_selenium(search_query)
    csv_search_term = clean_search_input_for_smartolt(search_query)
    cdata_search_term = search_query.strip()
    print_debug_header()
    
    result = {
        "success": False, "source": None, "report": None, "status": None,
        "network_analysis": None, "port_analysis": None
    }
    
    # CSV/OLT
    csv_results = search_proctor_csv(csv_search_term)
    if csv_results and len(csv_results) > 0:
        if len(csv_results) == 1:
            csv_result = csv_results[0]
            smartolt_name = csv_result["smartolt_name"]
            serial_number = csv_result["serial_number"]
            olt_full = csv_result["olt_full"]
            onu_match = re.search(r'(\S+onu_\d+/\d+/\d+:\d+)', olt_full)
            if onu_match:
                onu_part = onu_match.group(1)
                olt_name_full = olt_full.replace(onu_part, "").strip()
                onu_type = "gpon" if "gpon-onu_" in onu_part else "epon" if "epon-onu_" in onu_part else "gpon"
                port_onu_part = onu_part.split("_")[1] if "_" in onu_part else onu_part
                port_part = port_onu_part.split(":")[0] if ":" in port_onu_part else port_onu_part
                onu_id = int(port_onu_part.split(":")[1]) if ":" in port_onu_part else 0
                port_parts = port_part.split('/')
                board = port_parts[1] if len(port_parts) >= 3 else "N/A"
                port = port_parts[2] if len(port_parts) >= 3 else "N/A"
                olt_port = f"olt_{port_parts[0]}/{port_parts[1]}/{port_parts[2]}" if len(port_parts) >= 3 else f"olt_{port_part}"
                device_name = get_device_type(serial_number)
                olt_ip = OLT_IPS.get(olt_name_full)
                if not olt_ip:
                    olt_name_clean = re.sub(r'\s+OLT$', '', olt_name_full)
                    olt_ip = OLT_IPS.get(olt_name_clean)
                if olt_ip and check_reachability(olt_ip):
                    try:
                        results, client_status, avg_port_power, is_high_loss, rx_power_val, online_duration, downtime_reason, time_ago, optical_issue_message = run_async(
                            connect_to_olt(olt_name_full, olt_ip, onu_type, olt_port, onu_id, smartolt_name))
                        response = format_llm_response(smartolt_name, device_name, onu_type, serial_number,
                            client_status, rx_power_val, online_duration, downtime_reason,
                            avg_port_power, is_high_loss, olt_name_full, board, port, time_ago, optical_issue_message)
                        result.update({"success": True, "source": "csv_olt", "report": response, "status": client_status})
                        if DIAMETER_SESSION_ID:
                            diameter_data = get_diameter_user_data(smartolt_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                            if diameter_data and diameter_data.get('found', False):
                                result["network_analysis"] = {"html": format_network_analysis(diameter_data), "diameter_data": diameter_data}
                        if client_status == "offline":
                            percentages = radius_auth.DEBUG_DATA.get("port_stats", {}).get("percentages", {})
                            flags = radius_auth.DEBUG_DATA.get("status_flags", {})
                            port_analysis_match = find_port_analysis_match(percentages, flags)
                            port_analysis_text = format_port_analysis(port_analysis_match,
                                flags.get("MST", 0) == 1, radius_auth.DEBUG_DATA.get("mst_clients", []),
                                flags.get("JCU", 0) == 1, radius_auth.DEBUG_DATA.get("jcu_clients", []),
                                flags.get("JWD", 0) == 1, radius_auth.DEBUG_DATA.get("jwd_clients", []))
                            result["port_analysis"] = {"html": port_analysis_text, "raw_debug_data": {
                                "onl": percentages.get("onl", 0), "LOS": percentages.get("los", 0),
                                "pf": percentages.get("pf", 0), "ofl": percentages.get("ofl", 0),
                                "flags": {"JCU": flags.get("JCU", 0), "JWD": flags.get("JWD", 0),
                                          "HL": flags.get("HL", 0), "MPI": flags.get("MPI", 0), "MST": flags.get("MST", 0)}}}
                        return result
                    except Exception as e:
                        debug_print(f"Error: {e}", "ERROR")
        else:
            result.update({"success": True, "source": "csv_multiple", "status": "multiple_matches",
                          "report": f"Found {len(csv_results)} matching devices", "matches": csv_results})
            return result
    
    # Selenium
    selenium_result = search_selenium_olt(selenium_search_term)
    if selenium_result and selenium_result.get("report"):
        result.update({"success": True, "source": "selenium", "report": selenium_result["report"],
                      "status": "online" if "ONLINE" in selenium_result["report"] else "offline"})
        if DIAMETER_SESSION_ID and selenium_result.get("target_ont"):
            ont_name = selenium_result["target_ont"].get("ont_name", "")
            if ont_name:
                diameter_data = get_diameter_user_data(ont_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                if diameter_data and diameter_data.get('found', False):
                    result["network_analysis"] = {"html": format_network_analysis(diameter_data), "diameter_data": diameter_data}
        return result
    
    # CDATA
    matched_cdata, port_data, olt_ip, port_str, error_msg = cdata_search_and_monitor_port(cdata_search_term)
    if error_msg:
        result.update({"source": "cdata", "report": error_msg, "status": "error"})
        return result
    elif matched_cdata and port_data and olt_ip and port_str:
        olt_name = get_cdata_olt_name_by_ip(olt_ip)
        report = cdata_generate_diagnostic_report(matched_cdata, port_data, olt_name, int(port_str))
        result.update({"success": True, "source": "cdata", "report": report,
                      "status": "online" if matched_cdata.get("Status") == "🟢" else "offline"})
        if DIAMETER_SESSION_ID:
            onu_name = matched_cdata.get("Name", "")
            if onu_name:
                diameter_data = get_diameter_user_data(onu_name, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
                if diameter_data and diameter_data.get('found', False):
                    result["network_analysis"] = {"html": format_network_analysis(diameter_data), "diameter_data": diameter_data}
        return result
    
    # Diameter
    if DIAMETER_SESSION_ID:
        diameter_data = get_diameter_user_data(csv_search_term, DIAMETER_BASE_URL, DIAMETER_SESSION_ID)
        if diameter_data and diameter_data.get('found', False):
            radio_type = identify_radio_type(diameter_data.get('mac_address', 'N/A'))
            if radio_type:
                radio_message = format_radio_message(radio_type, diameter_data.get('nas_bts', 'N/A'),
                    diameter_data.get('session_ip', 'N/A'), diameter_data.get('ping_reachable', False))
                if radio_message:
                    result.update({"success": True, "source": "diameter_radio", "report": radio_message, "status": "online",
                                  "network_analysis": {"html": format_network_analysis(diameter_data), "diameter_data": diameter_data}})
                    return result
            else:
                result.update({"success": True, "source": "diameter_gpon", "report": format_gpon_request_message(), "status": "unknown",
                              "network_analysis": {"html": format_network_analysis(diameter_data), "diameter_data": diameter_data}})
                return result
        elif diameter_data and diameter_data.get('user_not_found', False):
            result.update({"source": "diameter", "report": "This PPPoE username does not exist in the system.", "status": "not_found"})
            return result
    
    result.update({"source": "none", "report": f"No results found for: {search_query}", "status": "not_found"})
    return result

def execute_onu_action(username, action, extra_params=None):
    result = run_search_like_streamlit(username)
    if not result or not result.get('success'):
        return {"success": False, "error": "Could not find device"}
    network = result.get('network_analysis')
    diam_data = network.get('diameter_data', {}) if network else {}
    cpe_ip = diam_data.get('cpe_ip', 'N/A')
    if cpe_ip == 'N/A':
        return {"success": False, "error": "CPE IP not found"}
    report = result.get('report', '')
    vendor_match = re.search(r'\*{0,2}(ZTE|Huawei)\*{0,2}', report, re.IGNORECASE)
    device_vendor = vendor_match.group(1).upper() if vendor_match else "Unknown"
    type_match = re.search(r'\*{0,2}(GPON|EPON)\*{0,2}', report, re.IGNORECASE)
    device_type = type_match.group(1).upper() if type_match else "Unknown"
    smartolt_name = diam_data.get('username', username)
    if device_vendor not in ['HUAWEI', 'ZTE']:
        return {"success": False, "error": f"Unsupported vendor: {device_vendor}"}
    router_type = "huawei" if device_vendor == "HUAWEI" else "zte"
    onu_username = smartolt_name if router_type == "zte" else None
    try:
        router = UnifiedRouterAPI(router_ip=cpe_ip, router_type=router_type, onu_username=onu_username, verbose=True, headless=True)
        if not router.login():
            router.close()
            return {"success": False, "error": "Failed to login to router"}
        if action == "scan":
            action_result = router.scan_devices()
        elif action == "wifi":
            action_result = router.get_wifi_details()
        elif action == "change_wifi":
            if not extra_params:
                router.close()
                return {"success": False, "error": "SSID or password required"}
            action_result = router.change_wifi(extra_params.get('ssid'), extra_params.get('password'))
        else:
            router.close()
            return {"success": False, "error": f"Unknown action: {action}"}
        router.close()
        action_result['device_context'] = {'smartolt_name': smartolt_name, 'device_vendor': device_vendor,
                                           'device_type': device_type, 'cpe_ip': cpe_ip, 'status': result.get('status', 'N/A')}
        return action_result
    except Exception as e:
        return {"success": False, "error": str(e)}

class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        client_ip = self.client_address[0]
        if not check_ip_allowed(client_ip):
            self._send_json({"error": "Access denied"}, 403); return
        if not check_rate_limit(client_ip):
            self._send_json({"error": "Rate limit exceeded"}, 429); return
        if parsed.path not in ['/health', '/']:
            auth = self.headers.get('Authorization', '')
            qp = urllib.parse.parse_qs(parsed.query)
            qt = qp.get('token', [None])[0]
            if not (verify_token(auth) or verify_token(qt)):
                self._send_json({"error": "Invalid token"}, 401); return
        if parsed.path in ['/health', '/']:
            self._send_json({"status": "healthy", "service": "MINITRON API"})
            return
        if parsed.path.startswith('/search/'):
            username = urllib.parse.unquote(parsed.path[8:])
            if not username:
                self._send_error("Username required"); return
            result = run_search_like_streamlit(username)
            self._send_json(result)
            return
        if parsed.path.startswith('/onu/'):
            qp = urllib.parse.parse_qs(parsed.query)
            username = qp.get('username', [None])[0]
            if not username:
                self._send_json({"error": "username required"}, 400); return
            if parsed.path == '/onu/scan':
                self._send_json(execute_onu_action(username, "scan")); return
            if parsed.path == '/onu/wifi':
                self._send_json(execute_onu_action(username, "wifi")); return
            self._send_json({"error": "Unknown ONU endpoint"}, 404); return
        self._send_error("Not Found", 404)
    
    def do_POST(self):
        client_ip = self.client_address[0]
        if not check_ip_allowed(client_ip):
            self._send_json({"error": "Access denied"}, 403); return
        if not check_rate_limit(client_ip):
            self._send_json({"error": "Rate limit exceeded"}, 429); return
        if not verify_token(self.headers.get('Authorization', '')):
            self._send_json({"error": "Invalid token"}, 401); return
        cl = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(cl).decode('utf-8'))
            if self.path == '/onu/wifi/change':
                username = data.get('username', '')
                if not username:
                    self._send_json({"error": "username required"}, 400); return
                extra = {'ssid': data.get('ssid'), 'password': data.get('password')}
                self._send_json(execute_onu_action(username, "change_wifi", extra)); return
            username = data.get('username', '')
            if not username:
                self._send_error("Username required"); return
            self._send_json(run_search_like_streamlit(username))
        except json.JSONDecodeError:
            self._send_error("Invalid JSON")
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode('utf-8'))
    
    def _send_error(self, msg, status=400):
        self._send_json({"error": msg}, status)
    
    def log_message(self, format, *args):
        pass

def find_free_port():
    for port in range(8000, 8020):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    return None

if __name__ == "__main__":
    port = find_free_port()
    if port:
        server = HTTPServer(('0.0.0.0', port), APIHandler)
        print(f"MINITRON API on port {port}")
        print(f"Token: {API_TOKEN}")
        print(f"Health: curl http://localhost:{port}/health")
        print(f"Search: curl -H 'Authorization: Bearer {API_TOKEN}' http://localhost:{port}/search/USER")
        server.serve_forever()
    else:
        print("No free ports")
