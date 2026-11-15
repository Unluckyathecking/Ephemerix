"""Reuse an earlier view's Gaia and CatWISE lists when the live catalogue query fails.

Gallery builds only (`python -m pxs.build --catalogs-from DIR`); the live lookup service never
does this. DIR holds `<slug>/manifest.json` from an earlier build. A stored list is used only
for the same target, only when the stored field covers the new one, and only when the earlier
build had a real answer for that catalogue (not an empty list left by its own failed query).
The stored lists hold exactly the fields `catalogs.parse_gaia` and `parse_catwise` return, so
a view built from them makes the same decisions as one built with the services up.

The catalogue queries take the brightest MAX_SOURCES in a cone around the field, so a stored
list from a larger field is complete only to its own cut; for the same field it is exact.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pxs import catalogs
from pxs.grid import Grid

log = logging.getLogger(__name__)

_KEYS = {catalogs.GAIA: "gaia", catalogs.CATWISE: "catwise"}
_NOTE = re.compile(r"^The (.+?) lists? (?:was|were) reused from the view built on (\d{1,2} \w{3} "
                   r"\d{4}), because the catalogue services did not answer\.$")
_EDGE_TOL_PX = 1e-3

Overlays = Callable[[Grid], tuple[dict, list[str]]]  # as in pxs.build


def reuse_note(names: list[str], built_on: str) -> str:
    """The manifest warning saying which lists were reused and from when."""
    lists = " and ".join(names)
    verb = "lists were" if len(names) > 1 else "list was"
    return (f"The {lists} {verb} reused from the view built on {built_on}, because the "
            "catalogue services did not answer.")


def _built_on(stored: dict, name: str) -> str:
    """When the stored list was fetched: the date of an earlier reuse it carries, else the
    stored view's own build date."""
    for w in stored.get("warnings", []):
        m = _NOTE.match(w) if isinstance(w, str) else None
        if m and name in m.group(1):
            return m.group(2)
    when = datetime.fromisoformat(stored["generated"])
    return f"{when.day} {when:%b %Y}"


def stored_grid(stored: dict) -> Grid:
    return Grid(stored["center"]["ra"], stored["center"]["dec"], float(stored["fov_arcsec"]),
                int(stored["size_px"]))


def covers(outer: Grid, inner: Grid) -> bool:
    """True when every corner of `inner` lies inside `outer`."""
    n = inner.size_px
    corners = [(0.0, 0.0), (n, 0.0), (0.0, n), (n, n)]
    ras, decs = inner.wcs().all_pix2world([c[0] - 0.5 for c in corners],
                                          [c[1] - 0.5 for c in corners], 0)
    xs, ys = outer.sky_to_px(ras, decs)
    lo, hi = -_EDGE_TOL_PX, outer.size_px + _EDGE_TOL_PX
    return bool(((xs >= lo) & (xs <= hi) & (ys >= lo) & (ys <= hi)).all())


def load_stored(stored_dir: Path, slug: str, grid: Grid) -> dict | None:
    """The earlier manifest for `slug` if it is usable for `grid`, else None (logged)."""
    path = Path(stored_dir) / slug / "manifest.json"
    try:
        stored = json.loads(path.read_text())
        same = stored["target"]["slug"] == slug
        ok = same and covers(stored_grid(stored), grid)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("stored catalogue lists for %s unusable (%s): %s", slug, path, exc)
        return None
    if not ok:
        log.warning("stored catalogue lists for %s not used: %s", slug,
                    "different target" if not same else "stored field does not cover this one")
        return None
    return stored


def _reusable(stored: dict, name: str, grid: Grid) -> list[dict] | None:
    """The stored list for catalogue `name`, cut to `grid`; None when that build lacked it."""
    warnings = stored.get("warnings", [])
    rows = (stored.get("overlays") or {}).get(_KEYS[name])
    if rows is None or catalogs._failed(name) in warnings:
        return None
    return [r for r in rows if catalogs._in_field(grid, r["ra"], r["dec"])]


def merge(ov: dict, warnings: list[str], stored: dict, grid: Grid) -> tuple[dict, list[str]]:
    """Live (`ov`, warnings) with each failed catalogue replaced by its stored list."""
    out, rest, used = dict(ov), list(warnings), []
    for name, key in _KEYS.items():
        failed = catalogs._failed(name)
        rows = _reusable(stored, name, grid) if failed in rest else None
        if rows is None:
            continue
        out, rest = {**out, key: rows}, [w for w in rest if w != failed]
        used.append(name)
    if not used:
        return out, rest
    dates = sorted({_built_on(stored, n) for n in used})
    notes = ([reuse_note(used, dates[0])] if len(dates) == 1
             else [reuse_note([n], _built_on(stored, n)) for n in used])
    return out, [*rest, *notes]


def with_stored(live: Overlays, stored_dir: Path, slug: str) -> Overlays:
    """`live`, falling back per catalogue to the lists stored for `slug` under `stored_dir`."""
    def run(grid: Grid) -> tuple[dict, list[str]]:
        ov, warnings = live(grid)
        if not (catalogs.gaia_failed(warnings) or catalogs.catwise_failed(warnings)):
            return ov, warnings
        stored = load_stored(stored_dir, slug, grid)
        return (ov, warnings) if stored is None else merge(ov, warnings, stored, grid)
    return run
