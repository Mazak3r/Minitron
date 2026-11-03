"""
MAC vendor detection + radio type identification.
"""
import time
import urllib.request

from backend.app.config import (
    UBNT_PREFIXES_NORMALIZED,
    CAMBIUM_PREFIXES_NORMALIZED,
)


_VENDOR_CACHE: dict = {}
_CACHE_TTL = 86400

HUAWEI_VENDOR_NAMES = ["huawei", "goodman", "hon hai", "foxconn", "fih"]


def _cache_get(mac):
    entry = _VENDOR_CACHE.get(mac)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _CACHE_TTL:
        _VENDOR_CACHE.pop(mac, None)
        return None
    return value


def _cache_set(mac, value):
    _VENDOR_CACHE[mac] = (time.time(), value)


def is_huawei_vendor(vendor_name):
    if not vendor_name:
        return False
    v = vendor_name.lower()
    return any(name in v for name in HUAWEI_VENDOR_NAMES)


def get_mac_vendor(mac_address):
    if not mac_address or mac_address == "N/A":
        return ""
    clean = mac_address.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(clean) < 6:
        return ""
    cached = _cache_get(clean)
    if cached is not None:
        return cached
    formatted = ":".join(clean[i:i+2] for i in range(0, 12, 2))
    try:
        req = urllib.request.Request(
            f"https://api.macvendors.com/{formatted}",
            headers={"User-Agent": "Python-Mac-Lookup"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode("utf-8").strip()
    except Exception:
        result = ""
    _cache_set(clean, result)
    return result


def identify_radio_type(mac_address):
    if not mac_address or mac_address == "N/A":
        return None
    normalized = mac_address.replace(":", "").replace("-", "").upper()
    if len(normalized) >= 6:
        prefix = normalized[:6]
        if prefix in UBNT_PREFIXES_NORMALIZED:
            return "ubnt"
        elif prefix in CAMBIUM_PREFIXES_NORMALIZED:
            return "cambium"
    return None


def format_radio_message(radio_type, nas_bts, session_ip, ping_reachable):
    if radio_type == "ubnt":
        if ping_reachable:
            return (f"Client is a UBNT radio client connected to {nas_bts}. "
                    f"The client's IP address is reachable via ping. "
                    f"Kindly click on this IP {session_ip} to access the radio and "
                    f"troubleshoot further.")
        return (f"Client is a UBNT radio client whose IP is not reachable. "
                f"Kindly confirm if any UBNT Access Point (AP) is down from {nas_bts}. "
                f"If no access point is down from {nas_bts}, please troubleshoot and "
                f"confirm with the client that both LAN cables connected to the PoE box "
                f"are properly connected. Once confirmed, wait for 5 minutes. "
                f"If the device does not come online, please raise a ticket.")
    elif radio_type == "cambium":
        if ping_reachable:
            return (f"Client is a Cambium radio client connected to {nas_bts}. "
                    f"The client's IP address is reachable via ping. "
                    f"Kindly click on this IP {session_ip} to access the radio and "
                    f"troubleshoot further.")
        return (f"Client is a Cambium radio client whose IP address is not reachable. "
                f"Kindly confirm if any Cambium Access Point (AP) is down from {nas_bts}. "
                f"If no access point is down from {nas_bts}, please troubleshoot and "
                f"confirm with the client that both LAN cables connected to the PoE box "
                f"are properly connected. Once confirmed, wait for 5 minutes. "
                f"If the device does not come online, please raise a ticket.")
    return None
