"""
Port analysis DB lookup — fixed search paths.
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
        pathlib.Path("/app/laravel") / PORT_ANALYSIS_FILE,
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
        "onl": percentages.get("onl", 0),
        "LOS": percentages.get("los", 0),
        "pf": percentages.get("pf", 0),
        "ofl": percentages.get("ofl", 0),
        "flags": {
            "JCU": flags.get("JCU", 0),
            "JWD": flags.get("JWD", 0),
            "HL": flags.get("HL", 0),
            "MPI": flags.get("MPI", 0),
            "MST": flags.get("MST", 0),
        },
    }
    input_str = repr(input_dict).strip()
    for record in data:
        if record.get("input", "").strip() == input_str:
            return extract_port_analysis_fields(record.get("output", ""))
    return None
