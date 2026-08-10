import asyncio
import telnetlib3
import json
import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "olt_config.json")
CSV_FILE = os.path.join(BASE_DIR, "ZTE OLT.csv")

_config = None
_df = None

def _load_config():
    global _config
    if _config is None:
        with open(CONFIG_FILE, 'r') as f:
            _config = json.load(f)
    return _config

def _load_csv():
    global _df
    if _df is None:
        _df = pd.read_csv(CSV_FILE)
        _df.columns = _df.columns.str.strip()
    return _df

async def _telnet_set_wan(olt_ip, username, password, board, port, onu_id, action):
    """Internal async function - DO NOT call directly"""
    onu_full = f"gpon-onu_1/{board}/{port}:{onu_id}"
    
    try:
        reader, writer = await telnetlib3.open_connection(olt_ip, 23)
        
        writer.write(f"{username}\n")
        await asyncio.sleep(0.5)
        writer.write(f"{password}\n")
        await asyncio.sleep(1)
        await reader.read(4096)
        
        writer.write("terminal length 0\n")
        await asyncio.sleep(0.3)
        await reader.read(1024)
        
        writer.write("conf t\n")
        await asyncio.sleep(0.5)
        await reader.read(1024)
        
        writer.write(f"pon-onu-mng {onu_full}\n")
        await asyncio.sleep(0.5)
        await reader.read(1024)
        
        cmd = f"security-mgmt 1 state {action} mode forward ingress-type wan protocol web\n"
        writer.write(cmd)
        await asyncio.sleep(1)
        result = await reader.read(2048)
        
        writer.write("end\n")
        await asyncio.sleep(0.3)
        writer.close()
        
        return "Error" not in result, result.strip()
    except Exception as e:
        return False, str(e)


def _run_async(coro):
    """Safely run an async function, works on both Windows and Linux"""
    try:
        # Try to get the current event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create a new one
        loop = None
    
    if loop and loop.is_running():
        # We're already in an async context, create a new loop in a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # Simple case - just run the coroutine
        return asyncio.run(coro)


def _search_customer(search_name):
    """Search CSV trying both space and underscore variations."""
    df = _load_csv()
    search_lower = search_name.strip().lower()
    
    # Try exact match first
    matches = df[df['Name'].str.lower().str.strip() == search_lower]
    if not matches.empty:
        return matches
    
    # Try swapping spaces and underscores
    if ' ' in search_lower:
        alt_name = search_lower.replace(' ', '_')
        matches = df[df['Name'].str.lower().str.strip() == alt_name]
        if not matches.empty:
            return matches
    elif '_' in search_lower:
        alt_name = search_lower.replace('_', ' ')
        matches = df[df['Name'].str.lower().str.strip() == alt_name]
        if not matches.empty:
            return matches
    
    # Try partial match on original
    matches = df[df['Name'].str.lower().str.strip().str.contains(search_lower, na=False)]
    if not matches.empty:
        return matches
    
    # Try partial match on swapped version
    if ' ' in search_lower:
        alt_name = search_lower.replace(' ', '_')
        matches = df[df['Name'].str.lower().str.strip().str.contains(alt_name, na=False)]
    elif '_' in search_lower:
        alt_name = search_lower.replace(' ', ' ')
        matches = df[df['Name'].str.lower().str.strip().str.contains(alt_name, na=False)]
    
    return matches


def set_wan_access(customer_name, action):
    """
    Enable or disable WAN access for a customer.
    
    Args:
        customer_name (str): Name to search in CSV
        action (str): 'enable' or 'disable'
    
    Returns:
        str: Success/error message
    """
    action = action.strip().lower()
    if action not in ["enable", "disable"]:
        return f"Error: Invalid action '{action}'. Use 'enable' or 'disable'."
    
    try:
        config = _load_config()
        df = _load_csv()
    except FileNotFoundError as e:
        return f"Error: File not found - {e}"
    
    matches = _search_customer(customer_name)
    
    if matches.empty:
        return f"Error: No customer found matching '{customer_name}'"
    
    selected = matches.iloc[0]
    olt_name = selected['OLT'].strip()
    
    if olt_name not in config["olt_ips"]:
        return f"Error: OLT '{olt_name}' not in config"
    
    olt_ip = config["olt_ips"][olt_name]
    username = config["telnet_credentials"]["username"]
    password = config["telnet_credentials"]["password"]
    board = int(selected['Board'])
    port = int(selected['Port'])
    onu_id = int(selected['Allocated ONU'])
    
    try:
        # Run the async function safely
        success, output = _run_async(
            _telnet_set_wan(olt_ip, username, password, board, port, onu_id, action)
        )
        
        if success:
            return f"OK: WAN access {action.upper()}D for {selected['Name'].strip()}"
        else:
            return f"FAIL: {output}"
    
    except Exception as e:
        return f"Error: Connection failed - {str(e)}"
