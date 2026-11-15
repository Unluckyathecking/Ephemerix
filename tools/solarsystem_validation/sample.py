"""Draw the body-recovery sample from the JPL Small-Body Database by fixed rules.

    uv run python tools/solarsystem_validation/sample.py   # writes sample.json next to this file

Rules (decided before any result was seen, so the sample is not picked by outcome):
- TNO: every numbered TNO with H < 4.0 (SBDB class TNO).
- CEN: the first 8 numbered Centaurs (SBDB class CEN) in number order.
- TJN: Jupiter Trojans, the first 2 numbered objects in number order in each 1-mag H bin
  from 8 to 15.
- MBA: main-belt asteroids, the first 2 numbered objects in number order in each 0.5-mag H
  bin from 5.0 to 18.0 (so the bright end tests saturation and the faint end the limit).
Bins are half open, lo <= H < hi. The raw SBDB answers are saved with the sample.

Written with Claude Code.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
FIELDS = "spkid,pdes,full_name,H,class"
HEADROOM = 6  # extra rows asked so the half-open upper edge never leaves a bin short
OUT = Path(__file__).with_name("sample.json")


@dataclass(frozen=True)
class Bin:
    """SBDB class, H range [h_lo, h_hi) (None: open), and how many to take (None: all)."""

    cls: str
    h_lo: float | None
    h_hi: float | None
    n: int | None

    @property
    def label(self) -> str:
        lo = "" if self.h_lo is None else f"{self.h_lo:g}"
        hi = "" if self.h_hi is None else f"{self.h_hi:g}"
        return f"{self.cls} H {lo}..{hi}"


def _steps(lo: float, hi: float, width: float) -> list[tuple[float, float]]:
    n = round((hi - lo) / width)
    return [(round(lo + i * width, 2), round(lo + (i + 1) * width, 2)) for i in range(n)]


def bins() -> list[Bin]:
    return ([Bin("TNO", None, 4.0, None), Bin("CEN", None, None, 8)]
            + [Bin("TJN", a, b, 2) for a, b in _steps(8.0, 15.0, 1.0)]
            + [Bin("MBA", a, b, 2) for a, b in _steps(5.0, 18.0, 0.5)])


def query_params(b: Bin) -> dict[str, str]:
    p = {"fields": FIELDS, "sb-class": b.cls, "sb-ns": "n"}
    if b.h_lo is not None and b.h_hi is not None:
        p["sb-cdata"] = json.dumps({"AND": [f"H|RG|{b.h_lo}|{b.h_hi}"]})
    elif b.h_hi is not None:
        p["sb-cdata"] = json.dumps({"AND": [f"H|LT|{b.h_hi}"]})
    if b.n is not None:
        p["limit"] = str(b.n + HEADROOM)
    return p


def select(resp: dict, b: Bin) -> list[dict]:
    """The bin's bodies from one SBDB answer: half-open in H, number order, first n."""
    ix = {f: i for i, f in enumerate(resp["fields"])}
    out = []
    for row in sorted(resp.get("data", []), key=lambda r: int(r[ix["spkid"]])):
        h = float(row[ix["H"]]) if row[ix["H"]] not in (None, "") else None
        if h is None:
            continue
        if (b.h_lo is not None and h < b.h_lo) or (b.h_hi is not None and h >= b.h_hi):
            continue
        out.append({"pdes": str(row[ix["pdes"]]), "name": " ".join(str(row[ix["full_name"]]).split()),
                    "H": h, "cls": b.cls, "bin": b.label})
    return out if b.n is None else out[:b.n]


def build(fetch: Callable[[dict], dict], bs: list[Bin], drawn_utc: str) -> dict:
    """The sample: rules, every query with its raw answer, and the bodies drawn."""
    done, bodies = [], []
    for b in bs:
        params = query_params(b)
        resp = fetch(params)
        done.append({"bin": b.label, "params": params, "response": resp})
        bodies += select(resp, b)
    return {"drawn_utc": drawn_utc, "source": SBDB_URL, "rules": [b.label for b in bs], "bins": done, "bodies": bodies}


def _fetch(params: dict) -> dict:
    import requests

    r = requests.get(SBDB_URL, params=params, timeout=60,
                     headers={"User-Agent": "pxs-validation"})
    r.raise_for_status()
    return r.json()


def main() -> int:
    out = build(_fetch, bins(), datetime.now(UTC).strftime("%Y-%m-%d"))
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    by = {}
    for b in out["bodies"]:
        by[b["cls"]] = by.get(b["cls"], 0) + 1
    sys.stdout.write(f"{len(out['bodies'])} bodies {by} -> {OUT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
