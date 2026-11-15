"""One field of the validation campaign: the real search, its mirrored null, and injection runs.

The work splits into units so the Modal campaign can run each in its own container: unit
"base" (real search and null: label 0 and 2 samples) and one unit per injection run (label 1
samples and completeness trials). `merge_units` joins a field's unit files into the
<field>.npz and .json that `train_vet` and probes/movers/figures.py read. Labels: 1 =
recovered injection, 0 = real-sky or null detection (nothing injected), 2 = a catalogued
TNO (a check, never trained on). Heavy (minutes per unit): run it through
deploy/modal_movers.py, not on a laptop.

    python -m pxs.movers.campaign merge cache/movers/campaign/units cache/movers/campaign
"""

from __future__ import annotations

import io
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from .candidates import Detection, track_xy
from .completeness import MATCH_PX, injected_track, run_injections
from .core import THRESHOLD, CoreResult, run_core
from .field import FieldData, load_field
from .matched import reflected_template
from .vetdata import sample

log = logging.getLogger(__name__)

SIZE_ARCMIN = 20.0
PER_RUN = 25
FLUX_RANGE_MJY = (0.02, 0.4)
D_RANGE_AU = (30.0, 1000.0)
KNOWN_MATCH_PX = 3.0
SAMPLE_KEYS = ("X", "F", "Y", "S", "R")
INJ_KEYS = ("inj_flux", "inj_rate", "inj_d", "inj_rec", "inj_pos", "inj_snr", "extras")


class _Samples:
    def __init__(self) -> None:
        self.x: list[np.ndarray] = []
        self.f: list[np.ndarray] = []
        self.y: list[int] = []
        self.s: list[float] = []
        self.r: list[str] = []

    def add(self, core: CoreResult, det: Detection, label: int, src: str,
            mirror: bool = False) -> None:
        st, fe = sample(core, det, mirror)
        self.x.append(st)
        self.f.append(fe)
        self.y.append(label)
        self.s.append(det.snr)
        self.r.append(src)

    def arrays(self) -> dict[str, np.ndarray]:
        return {"X": np.array(self.x), "F": np.array(self.f), "Y": np.array(self.y, int),
                "S": np.array(self.s, float), "R": np.array(self.r, str)}


def _npz(arrays: dict[str, np.ndarray]) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def _plain(obj: Any) -> Any:
    """Plain Python (str/int/float/list/dict) via a JSON round trip: no numpy scalars."""
    return json.loads(json.dumps(obj, default=float))


def field_meta(name: str, ra: float, dec: float, pass_index: int, fd: FieldData,
               core: CoreResult) -> dict[str, Any]:
    return {"name": name, "ra": ra, "dec": dec, "pass_index": pass_index,
            "n_frames": len(core.cube), "n_pass_frames": fd.n_pass_frames,
            "n_ref": len(fd.refs), "n_trials": len(core.trials), "read_s": fd.read_seconds,
            "search_s": core.maps.seconds, "masked": core.cube.masked_fraction,
            "pass_mjd": [float(core.cube.mjd.min()), float(core.cube.mjd.max())]}


def base_unit(name: str, ra: float, dec: float, pass_index: int,
              known_xy: tuple[float, float] | None = None) -> tuple[bytes, dict[str, Any]]:
    """Real search and mirrored null: (npz bytes of label 0/2 samples, plain metadata)."""
    t0, c0 = time.time(), time.process_time()
    fd = load_field(ra, dec, SIZE_ARCMIN, pass_index)
    base = run_core(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec)
    out = _Samples()
    for d in base.detections:
        is_known = known_xy is not None and math.hypot(d.x - known_xy[0],
                                                       d.y - known_xy[1]) <= KNOWN_MATCH_PX
        out.add(base, d, 2 if is_known else 0, "real")
    for d in base.null_detections:
        out.add(base, d, 0, "null", mirror=True)
    meta = field_meta(name, ra, dec, pass_index, fd, base) | {
        "real_ge7": [round(d.snr, 2) for d in base.above(THRESHOLD)],
        "real_ge7_xy": [[d.x, d.y] for d in base.above(THRESHOLD)],
        "null_ge7": [round(d.snr, 2) for d in base.above(THRESHOLD, null=True)],
        "null_max": max((d.snr for d in base.null_detections), default=None),
        "n_real_ge5": len(base.detections), "n_null_ge5": len(base.null_detections),
        "total_s": time.time() - t0, "cpu_s": time.process_time() - c0}
    log.info("%s base: %s", name, meta)
    return _npz(out.arrays()), _plain(meta)


def injection_unit(name: str, ra: float, dec: float, pass_index: int,
                   run: int) -> tuple[bytes, dict[str, Any]]:
    """One injection run of PER_RUN movers: (npz bytes of label 1 samples and trials, meta).
    The uninjected search is redone (no null) for its trial grid and real peak positions."""
    t0, c0 = time.time(), time.process_time()
    fd = load_field(ra, dec, SIZE_ARCMIN, pass_index)
    base = run_core(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec, with_null=False)
    out = _Samples()

    def collect(core: CoreResult, srcs: list) -> None:
        for d in core.detections:
            for s in srcs:
                if math.hypot(d.x - s.x, d.y - s.y) > MATCH_PX:
                    continue
                close = np.hypot(*(track_xy(core.trials, d) - injected_track(s, core))) <= MATCH_PX
                if np.mean(close) >= 0.5:
                    out.add(core, d, 1, "inj")
                    break

    seed = 1000 * sum(map(ord, name)) + run  # distinct per (field, run)
    trials, extras = run_injections(fd, 1, PER_RUN, FLUX_RANGE_MJY, D_RANGE_AU,
                                    reflected_template, seed=seed, base=base, collect=collect)
    arrays = out.arrays() | {
        "inj_flux": np.array([t.source.flux_mjy for t in trials]),
        "inj_rate": np.array([t.rate_px_day for t in trials]),
        "inj_d": np.array([t.source.d_au for t in trials]),
        "inj_rec": np.array([t.recovered for t in trials]),
        "inj_pos": np.array([t.at_position for t in trials]),
        "inj_snr": np.array([t.snr for t in trials]), "extras": np.array(extras)}
    meta = field_meta(name, ra, dec, pass_index, fd, base) | {
        "run": run, "seed": seed, "n_injected": len(trials),
        "n_recovered": int(sum(t.recovered for t in trials)),
        "n_at_position": int(sum(t.at_position for t in trials)), "extras": extras,
        "total_s": time.time() - t0, "cpu_s": time.process_time() - c0}
    log.info("%s run %d: %s", name, run, meta)
    return _npz(arrays), _plain(meta)


def merge_units(units: Path, out: Path) -> list[str]:
    """Join <field>__base and <field>__runNN unit files in `units` into <field>.npz/.json in
    `out` (fields without a base unit are skipped). Returns the fields written."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for bpath in sorted(units.glob("*__base.npz")):
        name = bpath.name.removesuffix("__base.npz")
        meta = json.loads((units / f"{name}__base.json").read_text())
        runs = sorted(units.glob(f"{name}__run*.npz"))
        parts = [np.load(bpath)] + [np.load(p) for p in runs]
        arrays: dict[str, np.ndarray] = {}
        for k in SAMPLE_KEYS:
            nonempty = [z[k] for z in parts if len(z[k])]
            arrays[k] = np.concatenate(nonempty) if nonempty else parts[0][k]
        for k in INJ_KEYS:
            arrays[k] = np.concatenate([z[k] for z in parts[1:]]) if runs else np.array([])
        rmeta = [json.loads(p.with_suffix(".json").read_text()) for p in runs]
        meta |= {"n_runs": len(runs), "n_injected": sum(m["n_injected"] for m in rmeta),
                 "n_recovered": sum(m["n_recovered"] for m in rmeta),
                 "n_at_position": sum(m["n_at_position"] for m in rmeta),
                 "extras_per_run": [e for m in rmeta for e in m["extras"]],
                 "total_s": meta["total_s"] + sum(m["total_s"] for m in rmeta)}
        np.savez_compressed(out / f"{name}.npz", **arrays)
        (out / f"{name}.json").write_text(json.dumps(meta, indent=1))
        written.append(name)
    return written


def run_field(name: str, ra: float, dec: float, pass_index: int, n_runs: int,
              known_xy: tuple[float, float] | None = None) -> tuple[bytes, dict[str, Any]]:
    """Every unit of one field in this process, merged: (npz bytes, metadata)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        units = Path(tmp) / "units"
        units.mkdir()
        jobs = [("base", lambda: base_unit(name, ra, dec, pass_index, known_xy))]
        jobs += [(f"run{r:02d}", lambda r=r: injection_unit(name, ra, dec, pass_index, r))
                 for r in range(n_runs)]
        for tag, job in jobs:
            data, meta = job()
            (units / f"{name}__{tag}.npz").write_bytes(data)
            (units / f"{name}__{tag}.json").write_text(json.dumps(meta))
        merge_units(units, Path(tmp))
        return (Path(tmp) / f"{name}.npz").read_bytes(), \
            json.loads((Path(tmp) / f"{name}.json").read_text())


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "merge":
        raise SystemExit("usage: python -m pxs.movers.campaign merge UNITS_DIR OUT_DIR")
    print("merged:", ", ".join(merge_units(Path(sys.argv[2]), Path(sys.argv[3]))) or "none")
