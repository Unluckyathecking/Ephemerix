"""Write web/data/names.json: the small offline name index the search box suggests from.

    uv run python tools/build_name_index.py [--out web/data/names.json]

Every position, proper motion and identifier comes from CDS SIMBAD's TAP service (basic, ident
and ids tables); nothing here is typed by hand except which objects to include and a few common
names people search for. Gallery targets are found by a 30 arcsec cone (planets excluded) around the gallery
position moved back to J2000 with the gallery's own proper motion; the two Solar System bodies
have no SIMBAD entry and carry only their gallery slug. Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "web" / "gallery" / "index.json"
# CDS first; its Harvard mirror serves the same SIMBAD database when CDS is unreachable.
TAP_URLS = (
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
    "https://simbad.harvard.edu/simbad/sim-tap/sync",
)
CONE_ARCSEC = 30.0

# Identifier families worth searching by; SIMBAD lists dozens more per bright star.
KEEP = ("NAME ", "* ", "V* ", "GJ ", "HD ", "HIP ", "LHS ", "LP ", "Ross ", "Wolf ", "BD", "CD",
        "2MASS J", "2MASSI J", "2MASSW J", "WISE J", "WISEA J", "WISEP", "CWISE J", "DENIS",
        "UGPS J", "SCR J", "Luhman ", "TRAPPIST", "VHS ", "LTT ", "Gaia DR3 ")

# Nearby stars and brown dwarfs people look for, by a SIMBAD identifier, with the label we show
# and any everyday names SIMBAD does not list.
CURATED = [
    ("NAME Proxima Centauri", "Proxima Centauri", None, ["Proxima", "Alpha Centauri C"]),
    ("* alf Cen A", "Alpha Centauri A", None, ["Rigil Kentaurus"]),
    ("* alf Cen B", "Alpha Centauri B", None, []),
    ("NAME Luhman 16", "Luhman 16AB", "brown dwarf", ["Luhman 16", "WISE 1049-5319"]),
    ("HD 209100", "Epsilon Indi A", None, ["Eps Indi A"]),
    ("Wolf  359", "Wolf 359", None, []),
    ("HD  95735", "Lalande 21185", None, ["Lalande"]),
    ("HD  33793", "Kapteyn's Star", None, ["Kapteyn"]),
    ("GJ 229 B", "Gliese 229B", "brown dwarf", ["Gl 229B"]),
    ("GJ 570 D", "Gliese 570D", "brown dwarf", ["Gl 570D"]),
    ("HD 201091", "61 Cygni A", None, []),
    ("HD 201092", "61 Cygni B", None, []),
    ("Ross  128", "Ross 128", None, []),
    ("Ross  154", "Ross 154", None, []),
    ("Ross  248", "Ross 248", None, []),
    ("* tau Cet", "Tau Ceti", None, []),
    ("* eps Eri", "Epsilon Eridani", None, []),
    ("GJ 1061", "Gliese 1061", None, []),
    ("NAME Teegarden's Star", "Teegarden's Star", None, ["Teegarden"]),
    ("GJ 273", "Luyten's Star", None, ["Luyten"]),
    ("GJ 35", "Van Maanen's Star", None, ["Van Maanen 2"]),
    ("GJ 15 A", "Groombridge 34 A", None, ["Groombridge 34"]),
    ("GJ 628", "Wolf 1061", None, []),
    ("GJ 581", "Gliese 581", None, []),
    ("2MASS J23062928-0502285", "TRAPPIST-1", None, []),
    ("SCR J1845-6357", "SCR J1845-6357", None, []),
    ("DENIS J081730.0-615520", "DENIS J0817-6155", "brown dwarf", []),
    ("WISE J035000.32-565830.2", "WISE 0350-5658", "brown dwarf", []),
    ("WISE J053516.80-750024.9", "WISE 0535-7500", "brown dwarf", []),
    ("WISE J064723.23-623235.5", "WISE 0647-6232", "brown dwarf", []),
    ("Ross  458C", "Ross 458C", "brown dwarf", []),
    ("VHS J125601.92-125723.9", "VHS 1256-1257", None, []),
    ("2MASS J07271824+1710012", "2MASS J0727+1710", "brown dwarf", []),
    ("2MASS J09393548-2448279", "2MASS J0939-2448", "brown dwarf", []),
]

# Everyday names of gallery targets that SIMBAD does not list.
GALLERY_ALSO = {
    "barnards-star": ["Barnard's Star", "Gliese 699", "Gl 699"],
    "epsilon-indi-b": ["Epsilon Indi B", "Eps Indi B", "Epsilon Indi Ba", "Epsilon Indi Bb"],
    "wise-0855-0714": ["WISE 0855", "WISE 0855-0714"],
    "rw-aurigae": ["RW Aurigae", "RW Aur"],
    "r-draconis": ["R Draconis", "R Dra"],
}


def norm(name: str) -> str:
    """SIMBAD pads identifiers with spaces ('HD  42581B'); one space reads better."""
    return " ".join(name.split())


ANSWERED: set[str] = set()  # which TAP endpoints served this run, recorded in the file


def tap(query: str) -> list[dict]:
    """Run one ADQL query; rows as dicts. Tries each SIMBAD TAP URL in turn."""
    data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                                   "QUERY": query}).encode()
    last = None
    for url in TAP_URLS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": "name-index/1"})
                with urllib.request.urlopen(req, timeout=60) as res:
                    text = res.read().decode("utf-8")
                if text.lstrip().startswith("<"):
                    raise ValueError("HTML instead of CSV")
                ANSWERED.add(url)
                return list(csv.DictReader(io.StringIO(text)))
            except Exception as err:  # noqa: BLE001  network or service page; try the next
                last = err
                time.sleep(1 + attempt)
    raise RuntimeError(f"SIMBAD TAP did not answer: {last}")


def adql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


COLS = "b.oid, b.main_id, b.ra, b.dec, b.pmra, b.pmdec, b.sp_type, b.otype, s.ids"


def by_ident(names: list[str]) -> dict[str, dict]:
    """SIMBAD rows keyed by the identifier asked for (matched without case)."""
    q = (f"SELECT i.id AS q, {COLS} FROM ident AS i JOIN basic AS b ON i.oidref = b.oid "
         f"JOIN ids AS s ON s.oidref = b.oid WHERE i.id IN ({', '.join(map(adql_str, names))})")
    return {r["q"].lower(): r for r in tap(q)}


def by_cone(ra: float, dec: float) -> dict | None:
    """Nearest SIMBAD object within CONE_ARCSEC of a J2000 position, or None."""
    r = CONE_ARCSEC / 3600
    q = (f"SELECT TOP 1 {COLS}, DISTANCE(POINT('ICRS', b.ra, b.dec), POINT('ICRS', {ra}, {dec})) AS d "
         f"FROM basic AS b JOIN ids AS s ON s.oidref = b.oid "
         f"WHERE b.otype != 'Pl' AND CONTAINS(POINT('ICRS', b.ra, b.dec), CIRCLE('ICRS', {ra}, {dec}, {r})) = 1 "
         f"ORDER BY d ASC")
    rows = tap(q)
    return rows[0] if rows else None


def to_j2000(t: dict) -> tuple[float, float]:
    """Move a gallery position at its epoch back to J2000 with its proper motion (linear)."""
    ra, dec, ep = t["ra"], t["dec"], t.get("epoch")
    pmra, pmdec = t.get("pmra_masyr"), t.get("pmdec_masyr")
    if ep is None or pmra is None or pmdec is None:
        return ra, dec
    dt = ep - 2000.0
    return (ra - pmra * dt / 3.6e6 / math.cos(math.radians(dec)), dec - pmdec * dt / 3.6e6)


def aliases(ids: str, extra: list[str]) -> list[str]:
    seen, out = set(), []
    for name in [*extra, *ids.split("|")]:
        name = " ".join(name.split())
        if not name or not (name in extra or name.startswith(KEEP)) or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out


def num(x: str, digits: int) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, digits) if math.isfinite(v) else None


def entry(row: dict, label: str, kind: str | None, slug: str | None, extra: list[str]) -> dict:
    otype = row.get("otype", "")
    return {
        "label": label,
        "kind": kind or ("brown dwarf" if otype.startswith("BD") else "star"),
        "slug": slug,
        "simbad": norm(row["main_id"]),
        "ra": num(row["ra"], 7), "dec": num(row["dec"], 7),
        "pmra": num(row["pmra"], 3), "pmdec": num(row["pmdec"], 3),
        "sp_type": row.get("sp_type") or None,
        "names": aliases(row.get("ids", ""), extra),
    }


def gallery_entries(targets: list[dict]) -> tuple[list[dict], list[str]]:
    out, missing = [], []
    for t in targets:
        if t.get("group") == "solar-system":
            out.append({"label": t["name"], "kind": "Solar System body", "slug": t["slug"],
                        "simbad": None, "ra": None, "dec": None, "pmra": None, "pmdec": None,
                        "sp_type": None, "names": [t["name"]]})
            continue
        m = json.loads((GALLERY.parent / t["manifest"]).read_text())["target"]
        row = by_cone(*to_j2000(m))
        if row is None:
            missing.append(t["slug"])
            continue
        extra = [t["name"], *GALLERY_ALSO.get(t["slug"], [])]
        out.append(entry(row, t["name"], None, t["slug"], extra))
    return out, missing


def build() -> dict:
    targets = json.loads(GALLERY.read_text())["targets"]
    gal, missing = gallery_entries(targets)
    found = by_ident([c[0] for c in CURATED])
    seen = {e["simbad"] for e in gal}
    cur = []
    for q, label, kind, also in CURATED:
        row = found.get(q.lower())
        if row is None:
            missing.append(q)
            continue
        if norm(row["main_id"]) in seen:
            continue
        seen.add(norm(row["main_id"]))
        cur.append(entry(row, label, kind, None, [label, *also]))
    if missing:
        print("not found in SIMBAD:", ", ".join(missing), file=sys.stderr)
    return {
        "schema": 1,
        "source": "CDS SIMBAD TAP (basic, ident and ids tables); ICRS positions at epoch J2000, "
                  "proper motions in mas/yr (pmRA includes cos Dec)",
        "endpoints": sorted(ANSWERED),
        "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "generator": "tools/build_name_index.py",
        "epoch": 2000.0,
        "entries": gal + sorted(cur, key=lambda e: e["label"].lower()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "data" / "names.json")
    args = ap.parse_args()
    data = build()
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(data['entries'])} entries to {args.out}")


if __name__ == "__main__":
    main()
