"""
Colored debug logger — identical format to original debug_print().
"""
from datetime import datetime
from backend.app.config import DEBUG_ENABLED

_LEVEL_COLORS = {
    "INFO": "\033[94m", "SUCCESS": "\033[92m", "WARNING": "\033[93m",
    "ERROR": "\033[91m", "DEBUG": "\033[95m", "PORT": "\033[96m",
    "CLIENT": "\033[97m", "SELENIUM": "\033[93m", "DATABASE": "\033[95m",
    "CDATA": "\033[36m", "CSV": "\033[92m",
}
_RESET = "\033[0m"


def debug_print(message, level="INFO"):
    if not DEBUG_ENABLED:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    color = _LEVEL_COLORS.get(level, "\033[97m")
    print(f"{color}[{ts}] {level}: {message}{_RESET}", flush=True)


def print_debug_header():
    debug_print("=" * 60, "DEBUG")
    debug_print("CLIENT SEARCH DEBUG INFORMATION", "DEBUG")
    debug_print("=" * 60, "DEBUG")


def print_client_info(smartolt_name, serial_number, olt_full, board, port, onu_type, device_name):
    debug_print(f"Smart OLT Name: {smartolt_name.upper()}", "CLIENT")
    debug_print(f"Serial Number: {serial_number.upper()}", "CLIENT")
    debug_print(f"Device Name: {device_name}", "CLIENT")
    debug_print(f"OLT: {olt_full}", "CLIENT")
    debug_print(f"Board: {board}", "CLIENT")
    debug_print(f"Port: {port}", "CLIENT")
    debug_print(f"ONU Type: {onu_type.upper()}", "CLIENT")
    debug_print("-" * 40, "DEBUG")
