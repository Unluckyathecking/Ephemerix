"""Trim recorded Horizons responses to the table and its header (drops the long footer).

    uv run python tests/solarsystem/trim_fixtures.py
"""
import json
from pathlib import Path

for p in (Path(__file__).parent / "fixtures").glob("horizons_*.json"):
    d = json.loads(p.read_text())
    lines = d["result"].splitlines()
    end = lines.index("$$EOE") + 1
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Target body name"))
    d["result"] = "\n".join(lines[start:end]) + "\n"
    p.write_text(json.dumps(d, indent=1))
    print(p.name, len(d["result"]))
