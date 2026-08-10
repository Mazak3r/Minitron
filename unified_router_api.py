#!/usr/bin/env python3
"""
Unified Router API – Huawei (new simple‑page approach) + ZTE (unchanged)
Fast headless operation on Ubuntu.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
import time
import urllib.parse
import re
import json
import os
import sys
from typing import Dict, Any, Optional, List, Union


# ==================== WAN ACCESS MANAGER ====================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

WAN_MODULE_AVAILABLE = False
set_wan_access = None

try:
    import onu_wan_module
    set_wan_access = onu_wan_module.set_wan_access
    WAN_MODULE_AVAILABLE = True
except Exception as e:
    def set_wan_access(name, action):
        print(f"  [SIMULATED] Would {action} WAN for {name}")
        return f"OK: WAN {action.upper()} (simulated)"


class WANAccessManager:
    """Manages WAN access for ZTE routers"""
    
    def __init__(self, onu_username: str, verbose: bool = False):
        self.onu_username = onu_username
        self.verbose = verbose
        self.wan_enabled = False
        
    def _log(self, message: str):
        if self.verbose:
            print(message)
    
    def enable_wan_access(self) -> bool:
        if not self.onu_username:
            self._log("⚠ No ONU username provided, skipping WAN access enable")
            return True
        self._log(f"  🔓 Enabling WAN access for {self.onu_username}...")
        try:
            result = set_wan_access(self.onu_username, "enable")
            self._log(f"  Result: {result}")
            if "OK" in str(result) or "ENABLED" in str(result).upper():
                self.wan_enabled = True
                self._log("  ✓ WAN access ENABLED successfully")
                time.sleep(2)
                return True
            else:
                self._log("  ⚠ Warning, but continuing anyway")
                self.wan_enabled = True
                return True
        except Exception as e:
            self._log(f"  ⚠ Error: {e}, but continuing anyway")
            self.wan_enabled = True
            return True
    
    def disable_wan_access(self) -> bool:
        if not self.onu_username or not self.wan_enabled:
            return True
        self._log(f"  🔒 Disabling WAN access for {self.onu_username}...")
        try:
            set_wan_access(self.onu_username, "disable")
            return True
        except Exception:
            return True


# ==================== CONFIGURATION FILE HANDLER ====================

class ConfigManager:
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config_data = {}
        self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                self.config_data = self.create_default_config()
        else:
            self.config_data = self.create_default_config()
            self.save_config()
    
    def create_default_config(self) -> Dict:
        return {
            "olt_ips": {"ZTE2": "192.168.3.1", "ZTE1": "192.168.4.2", "ZTE3": "192.168.5.1"},
            "telnet_credentials": {"username": "admin", "password": "admin"},
            "selenium_olt_ips": {"192.168.5.8": {"name": "Surulere OLT", "username": "admin", "password": "admin"}},
            "credentials": {"telnet": {"username": "admin", "password": "admin"}, "selenium_olt": {"username": "admin", "password": "admin"}}
        }
    
    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config_data, f, indent=4)


# ==================== HUAWEI ROUTER CORE (NEW SIMPLE-PAGE APPROACH) ====================

class HuaweiRouterCore:
    """Huawei HG8546M router – uses simplewificfg.asp and wlan_list.asp for speed."""
    
    def __init__(self, router_ip: str = "192.168.100.1", verbose: bool = False, headless: bool = False):
        self.router_ip = router_ip
        self.driver = None
        self.wait = None
        self.timeout = 60
        self.default_ip = "192.168.100.1"
        self.username = "telecomadmin"
        self.password = "admintelecom"
        self.is_logged_in = False
        self.verbose = verbose
        self.headless = headless
        
    def _log(self, message: str):
        if self.verbose:
            print(message)
    
    def _check_login_required(self) -> bool:
        try:
            if not self.driver:
                return True
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()
            if 'login.asp' in current_url:
                self._log("  ⚠ Detected login page, need to re-login")
                return True
            if 'txt_username' in page_source or 'frm_username' in page_source:
                self._log("  ⚠ Detected login form, need to re-login")
                return True
            if 'session expired' in page_source or 'login again' in page_source:
                self._log("  ⚠ Session expired, need to re-login")
                return True
            return False
        except:
            return True
    
    def _ensure_logged_in(self) -> bool:
        if self._check_login_required():
            self._log("  🔄 Re-login required...")
            return self.login()
        return self.is_logged_in
    
    def get_base_url(self):
        if self.router_ip == self.default_ip:
            return f"http://{self.router_ip}"
        else:
            return f"https://{self.router_ip}:80"
        
    def setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument('--ignore-certificate-errors')
        chrome_options.add_argument('--ignore-ssl-errors')
        chrome_options.add_argument('--allow-insecure-localhost')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--allow-running-insecure-content')
        if self.headless:
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
        prefs = {
            'credentials_enable_service': False,
            'profile.password_manager_enabled': False,
            'ssl_error_override': True
        }
        chrome_options.add_experimental_option("prefs", prefs)
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(self.timeout)
        self.wait = WebDriverWait(self.driver, self.timeout)
        self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def handle_certificate_error(self):
        time.sleep(3)
        page_source = self.driver.page_source.lower()
        if 'your connection is not private' in page_source or 'net::err_cert_authority_invalid' in page_source:
            self._log("  ⚠ Certificate error detected! Bypassing...")
            proceed_selectors = [
                "//button[@id='proceed-button']",
                "//a[contains(text(), 'Proceed')]",
                "//button[contains(text(), 'Proceed')]",
                "//*[@id='proceed-link']",
                "//a[contains(@id, 'proceed')]",
                "//button[contains(@id, 'proceed')]",
                "//*[contains(text(), 'proceed to')]",
                "//*[contains(text(), 'unsafe')]"
            ]
            for selector in proceed_selectors:
                try:
                    proceed_button = self.driver.find_element(By.XPATH, selector)
                    if proceed_button.is_displayed():
                        proceed_button.click()
                        self._log("  ✓ Clicked proceed button")
                        time.sleep(3)
                        return True
                except:
                    continue
            js_bypass = """
                var buttons = document.querySelectorAll('button, a');
                for (var i = 0; i < buttons.length; i++) {
                    var text = buttons[i].innerText.toLowerCase();
                    if (text.includes('proceed') || text.includes('unsafe') || text.includes('advanced')) {
                        buttons[i].click(); return true;
                    }
                }
                return false;
            """
            self.driver.execute_script(js_bypass)
            time.sleep(2)
            return True
        return False
    
    def safe_get(self, url, is_login_page=False):
        self._log(f"  ⏳ Navigating to: {url}")
        self.driver.get(url)
        time.sleep(3)
        if is_login_page:
            self.handle_certificate_error()
            time.sleep(2)
        return True
    
    def decode_string(self, text):
        if not text:
            return ""
        result = text
        for esc, char in [('\\x2e', '.'), ('\\x3a', ':'), ('\\x2d', '-'), ('\\x20', ' '),
                          ('\\x5f', '_'), ('\\x5c', '\\'), ('\\x2c', ','), ('\\x28', '('),
                          ('\\x29', ')'), ('\\x3d', '='), ('\\x26', '&')]:
            result = result.replace(esc, char)
        result = re.sub(r'\\x[0-9a-fA-F]{2}', '', result)
        return result.strip()
    
    def login(self) -> bool:
        if self.is_logged_in and not self._check_login_required():
            return True
        self._log(f"\n{'='*60}")
        self._log(f"CONNECTING TO HUAWEI ROUTER")
        self._log(f"{'='*60}")
        base_url = self.get_base_url()
        login_url = f"{base_url}/login.asp"
        if not self.driver:
            self.setup_driver()
        self.safe_get(login_url, is_login_page=True)
        time.sleep(5)
        try:
            username_field = self.wait.until(EC.presence_of_element_located((By.ID, "txt_Username")))
            password_field = self.driver.find_element(By.ID, "txt_Password")
            username_field.clear()
            time.sleep(1)
            username_field.send_keys(self.username)
            password_field.clear()
            time.sleep(1)
            password_field.send_keys(self.password)
            login_button = self.driver.find_element(By.ID, "loginbutton")
            login_button.click()
            time.sleep(5)
            if "login" not in self.driver.current_url.lower():
                self.is_logged_in = True
                self._log(f"\n{'='*60}")
                self._log(f"✓ HUAWEI LOGIN SUCCESSFUL!")
                return True
            else:
                self._log(f"\n✗ HUAWEI LOGIN FAILED!")
                return False
        except Exception as e:
            self._log(f"  ✗ Login error: {e}")
            return False

    # ---------- NEW: SSID from wlan_list.asp ----------
    def get_wlan_ssids_from_list(self):
        """Return list of SSID dicts from wlan_list.asp."""
        if not self._ensure_logged_in():
            return []
        base_url = self.get_base_url()
        list_url = f"{base_url}/html/amp/common/wlan_list.asp"
        self._log(f"  📡 Fetching WLAN list: {list_url}")
        self.safe_get(list_url)
        time.sleep(3)
        page_source = self.driver.page_source
        match = re.search(r'var\s+WlanInfo\s*=\s*new\s+Array\((.*?)\);', page_source, re.DOTALL)
        if not match:
            self._log("  ✗ Could not find WlanInfo array")
            return []
        array_content = match.group(1)
        wlan_pattern = r'new\s+stWlanInfo\("([^"]*)","([^"]*)","([^"]*)","([^"]*)","([^"]*)","([^"]*)"(?:,"([^"]*)")?\)'
        matches = re.findall(wlan_pattern, array_content)
        ssid_list = []
        for m in matches:
            ssid = self.decode_string(m[2])
            band = self.decode_string(m[5])
            service_enabled = (m[3] == '1')
            radio_enabled = (m[4] == '1')
            bindenable = m[6] if len(m) > 6 and m[6] else None
            if ssid:
                ssid_list.append({
                    'ssid': ssid,
                    'band': band,
                    'service_enabled': service_enabled,
                    'radio_enabled': radio_enabled,
                    'bindenable': bindenable,
                    'domain': m[0]
                })
        self._log(f"  ✓ Found {len(ssid_list)} SSID(s)")
        return ssid_list

    # ---------- NEW: simplewificfg.asp operations ----------
    def go_to_simplewificfg(self):
        """Navigate to the simple WiFi configuration page."""
        if not self._ensure_logged_in():
            return False
        base_url = self.get_base_url()
        url = f"{base_url}/html/amp/wlanbasic/simplewificfg.asp"
        self._log(f"  🌐 Opening simple WiFi config page: {url}")
        self.safe_get(url)
        time.sleep(4)
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, "txt_2g_wifiname")))
            self._log("  ✓ Simple WiFi config page loaded")
            return True
        except:
            self._log("  ✗ Could not load simple WiFi config page")
            return False

    def _get_current_ssid_from_simple_page(self):
        try:
            ssid_field = self.driver.find_element(By.ID, "txt_2g_wifiname")
            return ssid_field.get_attribute("value")
        except Exception:
            return None

    def _get_current_password_from_simple_page(self):
        try:
            pwd_field = self.driver.find_element(By.ID, "pwd_2g_wifipwd")
            return pwd_field.get_attribute("value")
        except Exception:
            return None

    def _apply_wifi_simple_page(self, ssid: str, password: str):
        """Fill the simple page fields and click Save. Returns True on success."""
        try:
            ssid_field = self.driver.find_element(By.ID, "txt_2g_wifiname")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", ssid_field)
            time.sleep(1)
            ssid_field.clear()
            ssid_field.send_keys(ssid)
        except Exception as e:
            self._log(f"  ✗ Failed to set SSID: {e}")
            return False

        try:
            pwd_field = self.driver.find_element(By.ID, "pwd_2g_wifipwd")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", pwd_field)
            time.sleep(1)
            pwd_field.clear()
            pwd_field.send_keys(password)
        except Exception as e:
            self._log(f"  ✗ Failed to set password: {e}")
            return False

        try:
            save_btn = self.driver.find_element(By.ID, "btnSave")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
            time.sleep(1)
            save_btn.click()
            self._log("  ✓ Clicked Save button")
            time.sleep(3)
        except Exception as e:
            self._log(f"  ✗ Error clicking Save: {e}")
            return False

        try:
            alert = self.driver.switch_to.alert
            alert.accept()
            self._log("  ✓ Confirmed alert")
            time.sleep(2)
        except:
            pass
        return True

    # ---------- Unified API methods ----------
    def scan_devices(self) -> Dict[str, Any]:
        result = {"success": False, "devices": [], "online_count": 0, "offline_count": 0, "total_count": 0, "error": None}
        if not self._ensure_logged_in():
            result["error"] = "Not logged in"
            return result
        self._log(f"\n{'='*60}")
        self._log("SCANNING FOR CONNECTED DEVICES")
        self._log(f"{'='*60}")
        base_url = self.get_base_url()
        dev_url = f"{base_url}/html/bbsp/common/GetLanUserDevInfo.asp"
        self.safe_get(dev_url)
        self._log("  ⏳ Loading device information...")
        time.sleep(5)
        page_source = self.driver.page_source
        devices = []
        try:
            array_match = re.search(r'var UserDevinfo = new Array\((.+?)\);', page_source, re.DOTALL)
            if array_match:
                array_content = array_match.group(1)
                device_pattern = r'new USERDevice\("([^"]+)","([^"]+)","([^"]+)","([^"]+)","([^"]+)","([^"]*)","([^"]+)","([^"]+)","([^"]+)","([^"]*)","([^"]+)","([^"]+)","([^"]+)"\)'
                matches = re.findall(device_pattern, array_content)
                for match in matches:
                    device = {
                        'hostname': self.decode_string(match[9]),
                        'ip': self.decode_string(match[1]),
                        'mac': self.decode_string(match[2]).upper(),
                        'port': self.decode_string(match[3]),
                        'port_type': self.decode_string(match[7]),
                        'status': self.decode_string(match[6]),
                        'ip_type': self.decode_string(match[4]),
                        'device_type': self.decode_string(match[5]),
                        'time': self.decode_string(match[8])
                    }
                    if device['status'] == 'Online' and device['ip'] and device['ip'] != '--':
                        devices.append(device)
                    elif device['status'] == 'Offline':
                        devices.append(device)
                online = [d for d in devices if d.get('status') == 'Online']
                offline = [d for d in devices if d.get('status') == 'Offline']
                result["success"] = True
                result["devices"] = devices
                result["online_count"] = len(online)
                result["offline_count"] = len(offline)
                result["total_count"] = len(devices)
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_wifi_details(self) -> Dict[str, Any]:
        result = {"success": False, "ssid": None, "password": None, "error": None}
        if not self._ensure_logged_in():
            result["error"] = "Not logged in"
            return result
        # Get SSID from wlan_list.asp
        ssids = self.get_wlan_ssids_from_list()
        if not ssids:
            result["error"] = "No SSIDs found"
            return result
        # Use the first SSID (primary)
        primary_ssid = ssids[0]['ssid']
        # Get password from simple page
        if not self.go_to_simplewificfg():
            result["error"] = "Could not load simple WiFi config page"
            return result
        password = self._get_current_password_from_simple_page()
        result["success"] = True
        result["ssid"] = primary_ssid
        result["password"] = password
        return result

    def change_wifi(self, new_ssid: Optional[str] = None, new_password: Optional[str] = None) -> Dict[str, Any]:
        result = {
            "success": False,
            "ssid_changed": False,
            "password_changed": False,
            "new_ssid": new_ssid,
            "new_password": "********" if new_password else None,
            "error": None
        }
        if not new_ssid and not new_password:
            result["error"] = "No changes provided"
            return result
        if new_password and len(new_password) < 8:
            result["error"] = "Password must be at least 8 characters"
            return result
        if not self._ensure_logged_in():
            result["error"] = "Not logged in"
            return result
        if not self.go_to_simplewificfg():
            result["error"] = "Could not load simple WiFi config page"
            return result

        # Determine current values if not provided
        if new_ssid is None:
            new_ssid = self._get_current_ssid_from_simple_page()
            if not new_ssid:
                result["error"] = "Could not retrieve current SSID"
                return result
        if new_password is None:
            new_password = self._get_current_password_from_simple_page()
            if not new_password:
                result["error"] = "Could not retrieve current password"
                return result

        # Apply changes
        if self._apply_wifi_simple_page(new_ssid, new_password):
            result["success"] = True
            result["ssid_changed"] = True
            result["password_changed"] = True  # We always write both fields
            result["new_ssid"] = new_ssid
            result["new_password"] = "********"  # don't reveal
        else:
            result["error"] = "Failed to apply settings"
        return result

    def close(self):
        if self.driver:
            self.driver.quit()
            self.is_logged_in = False


# ==================== ZTE ROUTER CORE (UNCHANGED) ====================

class ZTERouterCore:
    """ZTE F460 Router Core with WAN access via onu_wan_module"""
    
    def __init__(self, router_ip: str = "172.19.0.145", onu_username: str = None, verbose: bool = False, headless: bool = False):
        if not router_ip:
            router_ip = "172.19.0.145"
        if not router_ip.startswith("http"):
            router_ip = f"http://{router_ip}/"
        self.base_url = router_ip
        self.driver = None
        self.logged_in = False
        self.verbose = verbose
        self.onu_username = onu_username
        self.headless = headless
        self.wan_manager = WANAccessManager(onu_username, verbose) if onu_username else None
        
    def _log(self, message: str):
        if self.verbose:
            print(message)
    
    def _check_login_required(self) -> bool:
        try:
            if not self.driver:
                return True
            current_url = self.driver.current_url.lower()
            if 'login' in current_url and 'start.ghtml' not in current_url and 'index' not in current_url:
                return True
            try:
                username_field = self.driver.find_element(By.ID, "Frm_Username")
                if username_field and username_field.is_displayed():
                    return True
            except:
                pass
            return False
        except:
            return False
    
    def _ensure_logged_in(self) -> bool:
        if self.logged_in:
            if self._check_login_required():
                return self.login()
        return self.logged_in
    
    def _enable_wan_access(self) -> bool:
        if not self.wan_manager:
            return True
        return self.wan_manager.enable_wan_access()
    
    def _disable_wan_access(self) -> bool:
        if not self.wan_manager:
            return True
        return self.wan_manager.disable_wan_access()
        
    def _setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        if self.headless:
            chrome_options.add_argument('--headless=new')
            self._log("  Running in HEADLESS mode")
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            raise Exception(f"Could not initialize ChromeDriver: {e}")
        self.driver.implicitly_wait(10)
    
    def _wait_for_element(self, by, value, timeout=10):
        try:
            return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, value)))
        except TimeoutException:
            return None

    def _try_login(self, username: str, password: str) -> bool:
        try:
            self.driver.get(self.base_url)
            time.sleep(3)
            username_field = self._wait_for_element(By.ID, "Frm_Username", timeout=15)
            if not username_field:
                username_field = self._wait_for_element(By.NAME, "Frm_Username", timeout=5)
            password_field = self._wait_for_element(By.ID, "Frm_Password")
            if not password_field:
                password_field = self._wait_for_element(By.NAME, "Frm_Password", timeout=5)
            login_button = self._wait_for_element(By.ID, "LoginId")
            if not login_button:
                login_button = self._wait_for_element(By.NAME, "LoginId", timeout=5)
            if username_field and password_field and login_button:
                username_field.clear()
                username_field.send_keys(username)
                password_field.clear()
                password_field.send_keys(password)
                login_button.click()
                time.sleep(5)
                current_url = self.driver.current_url
                if "start.ghtml" in current_url or "index" in current_url:
                    self.logged_in = True
                    return True
                try:
                    if self.driver.find_element(By.ID, "Frm_Username"):
                        return False
                except:
                    pass
                self.logged_in = True
                return True
            return False
        except Exception as e:
            return False
    
    def _auto_login(self):
        credentials = [
            ("admin", "admin"), ("user", "green"), ("admin", "Ngcgreen"),
            ("admin", "Ngcgr33n@!"), ("telecomadmin", "admintelecom"),
            ("telecomadmin", "nE7jA%5m"), ("admin", "1234"), ("admin", "password"),
            ("admin", "admin123"), ("support", "support")
        ]
        for username, password in credentials:
            if self._try_login(username, password):
                self._log(f"✓ ZTE Login successful with {username}")
                return True
            time.sleep(1)
        raise Exception("ZTE Login failed")
    
    def _navigate_to_page(self, page_url: str) -> bool:
        try:
            full_url = urllib.parse.urljoin(self.base_url, page_url)
            self.driver.get(full_url)
            time.sleep(2)
            return True
        except Exception:
            return False
    
    def login(self) -> bool:
        if self.logged_in:
            try:
                self.driver.get(self.base_url)
                time.sleep(2)
                try:
                    username_field = self.driver.find_element(By.ID, "Frm_Username")
                    if username_field and username_field.is_displayed():
                        self.logged_in = False
                    else:
                        return True
                except:
                    return True
            except:
                pass
        if not self._enable_wan_access():
            self._log("  ⚠ Failed to enable WAN access, but trying to connect anyway...")
        if not self.driver:
            self._setup_driver()
        try:
            self._auto_login()
            self._log("✓ ZTE LOGIN SUCCESSFUL!")
            return True
        except Exception as e:
            self._log(f"✗ ZTE LOGIN FAILED: {e}")
            return False
    
    def scan_devices(self) -> Dict[str, Any]:
        result = {"success": False, "devices": [], "online_count": 0, "offline_count": 0, "total_count": 0, "error": None}
        if not self.logged_in:
            if not self.login():
                result["error"] = "Not logged in"
                return result
        try:
            devices = self._get_associated_devices_with_hostnames()
            if devices:
                for device in devices:
                    unified_device = {
                        "hostname": device.get("hostname", "Unknown"),
                        "ip": device.get("ip", "N/A"),
                        "mac": device.get("mac", "N/A"),
                        "status": "Online",
                        "port_type": "WIFI",
                        "signal_strength": device.get("signal_strength"),
                        "tx_rate": device.get("tx_rate_mbps"),
                        "rx_rate": device.get("rx_rate_mbps")
                    }
                    result["devices"].append(unified_device)
                result["success"] = True
                result["online_count"] = len(devices)
                result["total_count"] = len(devices)
            else:
                result["error"] = "No devices found"
        except Exception as e:
            result["error"] = str(e)
        return result
    
    def get_wifi_details(self) -> Dict[str, Any]:
        result = {"success": False, "ssid": None, "password": None, "error": None}
        if not self.logged_in:
            if not self.login():
                result["error"] = "Not logged in"
                return result
        try:
            ssid = self._get_current_ssid()
            password = self._get_current_password()
            result["success"] = True
            result["ssid"] = ssid
            result["password"] = password
        except Exception as e:
            result["error"] = str(e)
        return result
    
    def change_wifi(self, new_ssid: Optional[str] = None, new_password: Optional[str] = None) -> Dict[str, Any]:
        result = {"success": False, "ssid_changed": False, "password_changed": False, "new_ssid": new_ssid, "new_password": "********" if new_password else None, "error": None}
        if not new_ssid and not new_password:
            result["error"] = "No changes provided"
            return result
        if new_password and len(new_password) < 8:
            result["error"] = "Password must be at least 8 characters"
            return result
        if not self.logged_in:
            if not self.login():
                result["error"] = "Not logged in"
                return result
        try:
            if new_ssid:
                if self._change_ssid(new_ssid):
                    result["ssid_changed"] = True
                else:
                    result["error"] = "Failed to change SSID"
            if new_password:
                if self._change_wifi_password(new_password):
                    result["password_changed"] = True
                else:
                    result["error"] = "Failed to change password"
            result["success"] = result["ssid_changed"] or result["password_changed"]
        except Exception as e:
            result["error"] = str(e)
        return result
    
    def _get_dhcp_clients(self) -> Optional[List[Dict[str, str]]]:
        if not self.logged_in: return None
        if not self._navigate_to_page("getpage.gch?pid=1002&nextpage=net_dhcp_dynamic_t.gch"): return None
        try:
            dhcp_table = None
            for by, value in [(By.ID, "Dhcp_Table"), (By.CLASS_NAME, "item"), (By.TAG_NAME, "table")]:
                try:
                    tables = self.driver.find_elements(by, value)
                    for table in tables:
                        if table.is_displayed() and "MAC" in table.text:
                            dhcp_table = table; break
                    if dhcp_table: break
                except: continue
            clients = []
            if dhcp_table:
                rows = dhcp_table.find_elements(By.TAG_NAME, "tr")
                for row in rows[1:]:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 4: continue
                    mac = cells[0].text.strip()
                    if not mac or not re.match(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', mac): continue
                    clients.append({'mac': mac, 'ip': cells[1].text.strip() or "N/A", 'lease_time': cells[2].text.strip() or "N/A", 'hostname': cells[3].text.strip() or "N/A"})
            return clients if clients else self._extract_dhcp_from_page_source()
        except: return self._extract_dhcp_from_page_source()
    
    def _extract_dhcp_from_page_source(self) -> List[Dict[str, str]]:
        try:
            page_source = self.driver.page_source
            clients = []
            mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
            rows = re.findall(r'<tr[^>]*>(.*?)</td>', page_source, re.DOTALL | re.IGNORECASE)
            for row in rows:
                if not re.search(mac_pattern, row): continue
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
                if len(cells) < 4: continue
                mac = re.sub(r'<[^>]+>', '', cells[0]).strip()
                if not mac or not re.match(mac_pattern, mac): continue
                clients.append({'mac': mac, 'ip': re.sub(r'<[^>]+>', '', cells[1]).strip() or "N/A", 'lease_time': re.sub(r'<[^>]+>', '', cells[2]).strip() or "N/A", 'hostname': re.sub(r'<[^>]+>', '', cells[3]).strip() or "N/A"})
            return clients
        except: return []

    def _get_associated_devices(self) -> Optional[List[Dict[str, Any]]]:
        if not self.logged_in: return None
        if not self._navigate_to_page("getpage.gch?pid=1002&nextpage=net_wlanm_assoc1_t.gch"): return None
        rssi_table = {i: max(0, min(100, 2 * (i + 100))) for i in range(-100, -29)}
        try:
            devices_table = None
            for by, value in [(By.ID, "Assoc_Table"), (By.CLASS_NAME, "item"), (By.TAG_NAME, "table")]:
                try:
                    tables = self.driver.find_elements(by, value)
                    for table in tables:
                        if table.is_displayed() and "MAC" in table.text:
                            devices_table = table; break
                    if devices_table: break
                except: continue
            devices = []
            if devices_table:
                rows = devices_table.find_elements(By.TAG_NAME, "tr")
                for row in rows[1:]:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 7: continue
                    mac = cells[0].text.strip()
                    if not mac or mac == "N/A": continue
                    device_info = {'mac': mac, 'ip': cells[1].text.strip() or "N/A", 'mcs': cells[2].text.strip() or "N/A", 'sta_mode': cells[6].text.strip() or "N/A"}
                    rssi_text = cells[3].text.strip()
                    if rssi_text and rssi_text != "N/A":
                        try: device_info['rssi'] = int(rssi_text); device_info['signal_strength'] = rssi_table.get(device_info['rssi'], "Out of range")
                        except: device_info['rssi'] = device_info['signal_strength'] = "N/A"
                    else: device_info['rssi'] = device_info['signal_strength'] = "N/A"
                    for col_idx, key in [(4, 'tx_rate_kbps'), (5, 'rx_rate_kbps')]:
                        text = cells[col_idx].text.strip()
                        if text and text != "N/A":
                            try:
                                kbps = int(text)
                                device_info[key] = kbps
                                device_info[key.replace('kbps','mbps')] = round(kbps/1000, 2)
                            except: device_info[key] = device_info[key.replace('kbps','mbps')] = "N/A"
                        else: device_info[key] = device_info[key.replace('kbps','mbps')] = "N/A"
                    devices.append(device_info)
            return devices
        except: return self._extract_devices_from_page_source(rssi_table)

    def _extract_devices_from_page_source(self, rssi_table):
        # same as before, omitted for brevity – unchanged from previous version
        # (kept exactly as in earlier working script)
        try:
            page_source = self.driver.page_source
            devices = []
            mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
            rows = re.findall(r'<tr[^>]*>(.*?)</td>', page_source, re.DOTALL | re.IGNORECASE)
            for row in rows:
                if not re.search(mac_pattern, row): continue
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
                if len(cells) < 7: continue
                mac = re.sub(r'<[^>]+>', '', cells[0]).strip()
                if not mac or mac == "N/A": continue
                device_info = {'mac': mac, 'ip': re.sub(r'<[^>]+>', '', cells[1]).strip() or "N/A", 'mcs': re.sub(r'<[^>]+>', '', cells[2]).strip() or "N/A", 'sta_mode': re.sub(r'<[^>]+>', '', cells[6]).strip() or "N/A"}
                rssi_text = re.sub(r'<[^>]+>', '', cells[3]).strip()
                if rssi_text and rssi_text != "N/A":
                    try: device_info['rssi'] = int(rssi_text); device_info['signal_strength'] = rssi_table.get(device_info['rssi'], "Out of range")
                    except: device_info['rssi'] = device_info['signal_strength'] = "N/A"
                else: device_info['rssi'] = device_info['signal_strength'] = "N/A"
                for col_idx, key in [(4, 'tx_rate_kbps'), (5, 'rx_rate_kbps')]:
                    text = re.sub(r'<[^>]+>', '', cells[col_idx]).strip()
                    if text and text != "N/A":
                        try: kbps = int(text); device_info[key] = kbps; device_info[key.replace('kbps','mbps')] = round(kbps/1000, 2)
                        except: device_info[key] = device_info[key.replace('kbps','mbps')] = "N/A"
                    else: device_info[key] = device_info[key.replace('kbps','mbps')] = "N/A"
                devices.append(device_info)
            return devices
        except: return []

    def _get_associated_devices_with_hostnames(self) -> List[Dict[str, Any]]:
        devices = self._get_associated_devices() or []
        dhcp = self._get_dhcp_clients() or []
        mac_to_host = {c['mac'].lower(): c['hostname'] for c in dhcp if 'mac' in c and 'hostname' in c}
        for d in devices:
            mac_lower = d['mac'].lower()
            d['hostname'] = mac_to_host.get(mac_lower, "Unknown")
        return devices

    def _get_current_ssid(self) -> Optional[str]:
        if not self.logged_in: return None
        if not self._navigate_to_page("getpage.gch?pid=1002&nextpage=net_wlanm_essid1_t.gch"): return None
        try:
            ssid_field = self._wait_for_element(By.ID, "Frm_ESSID")
            return ssid_field.get_attribute("value") if ssid_field else None
        except: return None

    def _get_current_password(self) -> Optional[str]:
        if not self.logged_in: return None
        if not self._navigate_to_page("getpage.gch?pid=1002&nextpage=net_wlanm_secrity1_t.gch"): return None
        for field_id in ["Frm_WPAPassphrase", "Frm_KeyPassphrase", "Frm_Password"]:
            try:
                field = self.driver.find_element(By.ID, field_id)
                if field: return field.get_attribute("value")
            except: continue
        return None

    def _change_ssid(self, new_ssid: str) -> bool:
        if not self.logged_in: return False
        if not self._navigate_to_page("getpage.gch?pid=1002&nextpage=net_wlanm_essid1_t.gch"): return False
        try:
            field = self._wait_for_element(By.ID, "Frm_ESSID")
            if field: field.clear(); field.send_keys(new_ssid); return self._submit_form()
        except: return False

    def _change_wifi_password(self, new_password: str) -> bool:
        if not self.logged_in: return False
        if not self._navigate_to_page("getpage.gch?pid=1002&nextpage=net_wlanm_secrity1_t.gch"): return False
        for field_id in ["Frm_WPAPassphrase", "Frm_KeyPassphrase", "Frm_Password"]:
            try:
                field = self.driver.find_element(By.ID, field_id)
                if field: field.clear(); field.send_keys(new_password); return self._submit_form()
            except: continue
        return False

    def _submit_form(self) -> bool:
        submit_selectors = [(By.ID, "Btn_Submit"), (By.NAME, "Submit"), (By.CSS_SELECTOR, "input[type='submit']"), (By.CSS_SELECTOR, "input[value*='Submit']"), (By.CSS_SELECTOR, "input[value*='Apply']"), (By.CSS_SELECTOR, "button[type='submit']")]
        for by, value in submit_selectors:
            try:
                button = self.driver.find_element(by, value)
                if button and button.is_displayed():
                    button.click()
                    time.sleep(2)
                    return True
            except: continue
        return False

    def close(self):
        if self.driver:
            self.driver.quit()
        self._disable_wan_access()


# ==================== UNIFIED ROUTER API ====================

class UnifiedRouterAPI:
    """Unified API for Huawei and ZTE routers"""
    
    def __init__(self, router_ip: str, router_type: str, onu_username: str = None, verbose: bool = False, headless: bool = False):
        self.router_ip = router_ip
        self.router_type = router_type.lower()
        self.verbose = verbose
        self.headless = headless
        self.core = None
        if self.router_type == "huawei":
            self.core = HuaweiRouterCore(router_ip, verbose=verbose, headless=headless)
        elif self.router_type == "zte":
            self.core = ZTERouterCore(router_ip, onu_username=onu_username, verbose=verbose, headless=headless)
        else:
            raise ValueError(f"Unknown router type: {router_type}")
    
    def login(self) -> bool:
        return self.core.login()
    
    def scan_devices(self) -> Dict[str, Any]:
        return self.core.scan_devices()
    
    def get_wifi_details(self) -> Dict[str, Any]:
        return self.core.get_wifi_details()
    
    def change_wifi(self, new_ssid: Optional[str] = None, new_password: Optional[str] = None) -> Dict[str, Any]:
        return self.core.change_wifi(new_ssid, new_password)
    
    def close(self):
        if self.core:
            self.core.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
