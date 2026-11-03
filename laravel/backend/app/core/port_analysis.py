"""
Port analysis DB lookup — robust dict matching.
"""
import ast
import json
import pathlib
from typing import Optional, Dict
from backend.app.config import PORT_ANALYSIS_FILE, SCRIPT_DIR


def load_port_analysis_data():
    possible_paths = [
        pathlib.Path("/app") / PORT_ANALYSIS_FILE,
        pathlib.Path("/app") / "testo.json",
        SCRIPT_DIR / PORT_ANALYSIS_FILE,
        pathlib.Path.cwd() / PORT_ANALYSIS_FILE,
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return []


def extract_port_analysis_fields(output_string):
    try:
        # Fallback for the old ast.literal_eval way
        d = ast.literal_eval(output_string)
        return {
            "Explanation": d.get("Explanation"),
            "Action": d.get("Action"),
            "Severity": d.get("Severity"),
        }
    except Exception:
        return None


def find_port_analysis_match(percentages, flags) -> Optional[Dict]:
    data = load_port_analysis_data()
    if not data:
        return None
        
    input_dict = {
        "onl": int(percentages.get("onl", 0)),
        "LOS": int(percentages.get("los", 0)),
        "pf": int(percentages.get("pf", 0)),
        "ofl": int(percentages.get("ofl", 0)),
        "flags": {
            "JCU": int(flags.get("JCU", 0)),
            "JWD": int(flags.get("JWD", 0)),
            "HL": int(flags.get("HL", 0)),
            "MPI": int(flags.get("MPI", 0)),
            "MST": int(flags.get("MST", 0)),
        },
    }
    
    # Iterate and compare as dictionaries, not strings
    for record in data:
        record_input_str = record.get("input", "").strip()
        try:
            record_dict = ast.literal_eval(record_input_str)
            if record_dict == input_dict:
                return extract_port_analysis_fields(record.get("output", ""))
        except Exception:
            # If it fails to parse, fallback to string match
            if record_input_str == repr(input_dict).strip():
                return extract_port_analysis_fields(record.get("output", ""))
                
    return None
