"""Frame lookup from the local Parquet index (tools/spherex_index), with no network.

`FrameIndex.find` returns the same `Frame` records as `query.find_frames` (IRSA SIA2), in
milliseconds. A frame is returned when the search circle touches the image rectangle,
tested exactly with the stored TAN-SIP WCS (indexwcs), after a cheap bounding-circle cut.

Memory: one row costs about 200 bytes (WCS, time, ids), so the full DR1 + QR3 index of
1.63 million frames holds 320 MB of arrays. Keys are rebuilt from their parts, not stored.

Loading: the arrays come from one file, root/cache-v1.npz, when it was built from the
current manifest.json (`python -m pxs.spherex.localindex --build-cache DIR`, done offline;
one sequential read, which is what a network volume is fast at). Otherwise, or if the cache
is damaged, every shard is read once, in parallel. Both give identical lookups.

`try_lookup` is what `query.find_frames` calls. It is configured by PXS_SPHEREX_INDEX (the
directory holding manifest.json and rows/) and never raises: it returns None whenever the
caller should use SIA instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from . import config
from .indexfmt import DETECTOR_BAND_M, SCHEMA_VERSION, rebuild_key
from .indexwcs import WcsTable, distance_to_box, sip_terms, sky_to_pixel
from .types import Frame

log = logging.getLogger(__name__)

ENV_DIR = "PXS_SPHEREX_INDEX"
ENV_TAIL = "PXS_SPHEREX_INDEX_SIA_TAIL"  # "1": also ask SIA for frames newer than the index
_COLUMNS = ["release", "week", "pipeline", "obs_id", "detector", "sps_flags", "mjd", "naxis1",
            "naxis2", "crval1", "crval2", "crpix1", "crpix2", "cd11", "cd12", "cd21", "cd22",
            "sip_order", "sip_ap", "sip_bp", "ra_c", "dec_c", "radius_deg"]
_CUT_SLACK_DEG = 0.05  # float32 unit vectors resolve about 0.02 deg; the exact test decides
CACHE_NAME = "cache-v1.npz"  # at the index root, next to manifest.json
_CACHE_FORMAT = 1  # bump when the arrays FrameIndex is built from change
_CACHE_BUFFER = 64 << 20  # bytes per read of the cache file
_SHARD_THREADS = 32  # shard reads wait on the (network) volume, not on the CPU


class IndexUnavailable(RuntimeError):
    """The index directory is missing, unreadable or from an incompatible version."""


@dataclass(frozen=True)
class LocalResult:
    """Frames from the index; sia_after_mjd is set when SIA should add newer frames."""

    frames: list[Frame]
    sia_after_mjd: float | None = None


class FrameIndex:
    """All indexed frames in memory, with cone and exact-coverage lookups."""

    def __init__(self, root: Path, manifest: dict, cols: dict[str, np.ndarray],
                 wcs: WcsTable, vocab: dict[str, list[str]]) -> None:
        self.root = root
        self.manifest = manifest
        self._c = cols
        self._wcs = wcs
        self._vocab = vocab
        dec = cols["dec_c"]
        band = np.floor(dec).astype(np.int64) + 90  # 0..180
        self._order = np.argsort(band, kind="stable").astype(np.int32)
        self._starts = np.searchsorted(band[self._order], np.arange(183))
        self._rmax = float(cols["radius_deg"].max()) if len(dec) else 0.0
        self.releases = {r for r, v in manifest.get("releases", {}).items() if v["rows"] > 0}
        self.from_cache = False

    def __len__(self) -> int:
        return len(self._c["mjd"])

    def max_mjd(self, releases: Sequence[str]) -> float:
        """Latest observation time in the index over the given releases."""
        return max(float(self.manifest["releases"][r]["mjd_max"]) for r in releases)

    @classmethod
    def load(cls, root: Path | str) -> FrameIndex:
        """Read the index under root: the cache file when it is current, else every shard.

        Raises IndexUnavailable. Never writes (the service mounts the index read-only).
        """
        root = Path(root)
        try:
            raw = (root / "manifest.json").read_bytes()
            manifest = json.loads(raw)
        except (OSError, ValueError) as e:
            raise IndexUnavailable(f"no readable manifest in {root}: {e}") from e
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise IndexUnavailable(f"index schema {manifest.get('schema_version')} != "
                                   f"{SCHEMA_VERSION}")
        arrays = _read_cache(root / CACHE_NAME, _stamp(raw), manifest.get("rows"))
        from_cache = arrays is not None
        idx = cls(root, manifest, *(arrays or _read_shards(root)))
        idx.from_cache = from_cache
        return idx

    def _allowed(self, collections: Sequence[str]) -> np.ndarray:
        """Boolean per row: does its collection (spherex_<release>[_deep]) match?"""
        rel = self._vocab["release"]
        ok = np.zeros(len(rel) * 2, dtype=bool)
        for i, r in enumerate(rel):
            ok[2 * i] = f"spherex_{r}" in collections
            ok[2 * i + 1] = f"spherex_{r}_deep" in collections
        return ok[self._c["release"] * 2 + self._c["deep"]]

    def _candidates(self, ra: float, dec: float, radius_deg: float) -> np.ndarray:
        """Row indices whose bounding circle may reach the search circle."""
        c = self._c
        span = self._rmax + radius_deg + _CUT_SLACK_DEG
        lo = int(np.clip(math.floor(dec - span) + 90, 0, 180))
        hi = int(np.clip(math.floor(dec + span) + 90, 0, 180))
        idx = self._order[self._starts[lo]:self._starts[hi + 1]]
        r, d = math.radians(ra), math.radians(dec)
        x, y, z = math.cos(d) * math.cos(r), math.cos(d) * math.sin(r), math.sin(d)
        dot = c["ux"][idx] * x + c["uy"][idx] * y + c["uz"][idx] * z
        reach = np.radians(c["radius_deg"][idx].astype(float) + radius_deg + _CUT_SLACK_DEG)
        return idx[dot >= np.cos(np.minimum(reach, math.pi))]

    def _covering(self, ra: float, dec: float, radius_deg: float, allowed: np.ndarray,
                  margin_px: float) -> np.ndarray:
        """Rows whose image rectangle, grown by the search radius, contains (ra, dec)."""
        cand = self._candidates(ra, dec, radius_deg)
        cand = cand[allowed[cand]]
        if not len(cand):
            return cand
        t = self._wcs.take(cand)
        x, y, ok = sky_to_pixel(ra, dec, t)
        scale_deg = np.sqrt(np.abs(t.cd11 * t.cd22 - t.cd12 * t.cd21))
        dist = distance_to_box(x, y, self._c["naxis1"][cand], self._c["naxis2"][cand])
        return cand[ok & (dist <= radius_deg / scale_deg + margin_px)]

    def find(self, positions: Sequence[tuple[float, float]], radius_deg: float,
             collections: Sequence[str] = config.COLLECTIONS, margin_px: float = 0.0
             ) -> list[Frame]:
        """Frames covering any (ra, dec) of `positions` (a point, or a moving target's path).

        A frame covers a position when the circle of radius_deg around it touches the image
        rectangle; margin_px grows the rectangle further. Sorted by (mjd, detector).
        """
        allowed = self._allowed(collections)
        rows: set[int] = set()
        for ra, dec in positions:
            rows.update(self._covering(ra, dec, radius_deg, allowed, margin_px).tolist())
        return sorted((self._frame(i) for i in rows), key=lambda f: (f.mjd, f.detector))

    def _frame(self, i: int) -> Frame:
        c, v = self._c, self._vocab
        rel, det = v["release"][c["release"][i]], int(c["detector"][i])
        obs = c["obs_id"][i].decode()
        lo, hi = DETECTOR_BAND_M[det]
        return Frame(
            collection=f"spherex_{rel}" + ("_deep" if c["deep"][i] else ""), obs_id=obs,
            detector=det, mjd=float(c["mjd"][i]),
            s3_key=rebuild_key(rel, v["week"][c["week"][i]], v["pipeline"][c["pipeline"][i]],
                               obs, det),
            em_min_um=lo * 1e6, em_max_um=hi * 1e6)


def _read_shards(root: Path) -> tuple[dict[str, np.ndarray], WcsTable, dict[str, list[str]]]:
    """The arrays FrameIndex needs, from every shard under root/rows (each opened once)."""
    parts = sorted((root / "rows").glob("release=*/week=*/part-*.parquet"))
    if not parts:
        raise IndexUnavailable(f"no shards under {root / 'rows'}")
    with ThreadPoolExecutor(_SHARD_THREADS) as ex:
        t = pa.concat_tables(ex.map(lambda p: pq.read_table(p, columns=_COLUMNS), parts))
    n = t.num_rows
    omax = int(pc.max(t["sip_order"]).as_py())
    terms = sip_terms(omax)
    f32 = np.float32
    cols = {k: t[k].to_numpy() for k in ("mjd", "naxis1", "naxis2", "detector", "ra_c",
                                         "dec_c", "radius_deg")}
    cols["obs_id"] = t["obs_id"].to_numpy().astype("S24")
    vocab: dict[str, list[str]] = {}
    for k in ("release", "week", "pipeline"):
        enc = t[k].combine_chunks().dictionary_encode()
        vocab[k] = enc.dictionary.to_pylist()
        cols[k] = enc.indices.to_numpy().astype(np.int16)
    cols["deep"] = pc.fill_null(pc.starts_with(t["sps_flags"], "deep"), False).to_numpy()
    w = {k: t[k].to_numpy() for k in ("crval1", "crval2", "crpix1", "crpix2", "cd11", "cd12",
                                      "cd21", "cd22")}
    ap = np.zeros((n, len(terms)), f32)
    bp = np.zeros((n, len(terms)), f32)
    _fill_sip(ap, bp, slice(0, n), t, terms)
    wcs = WcsTable(w["crval1"], w["crval2"], w["crpix1"], w["crpix2"], w["cd11"], w["cd12"],
                   w["cd21"], w["cd22"], ap, bp, omax)
    ra, dec = np.radians(cols["ra_c"]), np.radians(cols["dec_c"])
    cols["ux"] = (np.cos(dec) * np.cos(ra)).astype(f32)
    cols["uy"] = (np.cos(dec) * np.sin(ra)).astype(f32)
    cols["uz"] = np.sin(dec).astype(f32)
    return cols, wcs, vocab


def _fill_sip(ap: np.ndarray, bp: np.ndarray, s: slice, t, terms: tuple) -> None:
    """Copy a shard's SIP lists into ap/bp rows, padding lower orders with zeros."""
    orders = t.column("sip_order").to_numpy()
    for name, out in (("sip_ap", ap), ("sip_bp", bp)):
        col = t.column(name).combine_chunks()
        for o in np.unique(orders):
            rows = np.nonzero(orders == o)[0]
            sub = col if len(rows) == len(orders) else col.take(pa.array(rows))
            if len(sip_terms(int(o))) == 0:
                continue
            flat = sub.values.to_numpy().reshape(len(rows), -1)
            at = [terms.index(pq_) for pq_ in sip_terms(int(o))]
            out[s.start + rows[:, None], np.array(at)[None, :]] = flat


# ---- the consolidated cache: one file, one sequential read ---------------------------------


def _stamp(manifest_bytes: bytes) -> str:
    """What a cache is keyed to: the manifest's bytes (rewritten by every index refresh)."""
    return hashlib.sha256(manifest_bytes).hexdigest()


def _read_cache(path: Path, stamp: str, rows: int | None
                ) -> tuple[dict[str, np.ndarray], WcsTable, dict[str, list[str]]] | None:
    """The cached arrays, or None when the cache is absent, stale or unreadable."""
    if not path.exists():
        return None
    try:
        # A large buffer turns numpy's 256 KB chunked reads into a few big ones on the volume.
        with path.open("rb", buffering=_CACHE_BUFFER) as f, np.load(f, allow_pickle=False) as z:
            meta = z["meta"].tolist()
            if meta[:3] != [stamp, str(SCHEMA_VERSION), str(_CACHE_FORMAT)]:
                log.warning("SPHEREx index cache %s is stale; reading the shards", path)
                return None
            got = {k: z[k] for k in z.files}
        cols = {k[2:]: v for k, v in got.items() if k.startswith("c_")}
        wcs = WcsTable(**{k[2:]: v for k, v in got.items() if k.startswith("w_")},
                       order=int(meta[3]))
        vocab = {k[2:]: v.tolist() for k, v in got.items() if k.startswith("v_")}
        sizes = {len(v) for v in (*cols.values(), *_wcs_arrays(wcs).values())}
        if sizes != {rows} or set(vocab) != {"release", "week", "pipeline"}:
            raise ValueError(f"row counts {sorted(sizes)} != manifest {rows}")
        return cols, wcs, vocab
    except Exception as e:  # noqa: BLE001 - a damaged cache only means "read the shards"
        log.warning("SPHEREx index cache %s unreadable (%s); reading the shards", path, e)
        return None


def _wcs_arrays(wcs: WcsTable) -> dict[str, np.ndarray]:
    return {f.name: getattr(wcs, f.name) for f in fields(WcsTable) if f.name != "order"}


def write_cache(root: Path | str) -> Path:
    """Write root/CACHE_NAME from the shards, keyed to the current manifest. Offline only."""
    root = Path(root)
    stamp = _stamp((root / "manifest.json").read_bytes())
    cols, wcs, vocab = _read_shards(root)
    arrays = {f"c_{k}": v for k, v in cols.items()}
    arrays |= {f"w_{k}": v for k, v in _wcs_arrays(wcs).items()}
    arrays |= {f"v_{k}": np.array(v, dtype=str) for k, v in vocab.items()}
    arrays["meta"] = np.array([stamp, str(SCHEMA_VERSION), str(_CACHE_FORMAT), str(wcs.order)])
    path = root / CACHE_NAME
    tmp = root / f".{CACHE_NAME}.tmp"
    with tmp.open("wb") as f:
        np.savez(f, **arrays)
    tmp.replace(path)
    return path


# ---- the cached, never-raising entry point used by query.find_frames ----------------------

_lock = threading.Lock()
_cache: dict[str, tuple[float, FrameIndex | None]] = {}
_RETRY_AFTER_S = 60.0


def _index_for(path: str) -> FrameIndex | None:
    """The loaded index for a directory, or None (a failure is remembered for a minute)."""
    manifest = Path(path) / "manifest.json"
    try:
        stamp = manifest.stat().st_mtime_ns
    except OSError:
        log.warning("%s=%s has no manifest.json; using SIA", ENV_DIR, path)
        return None
    with _lock:
        hit = _cache.get(path)
        if hit and (hit[1] is not None and hit[0] == stamp
                    or hit[1] is None and time.monotonic() - hit[0] < _RETRY_AFTER_S):
            return hit[1]
        try:
            t0 = time.monotonic()
            idx = FrameIndex.load(path)
            log.info("loaded SPHEREx frame index: %d frames in %.1f s", len(idx),
                     time.monotonic() - t0)
            _cache[path] = (stamp, idx)
            return idx
        except Exception as e:  # noqa: BLE001 - any load failure means "use SIA"
            log.warning("SPHEREx frame index at %s unusable (%s); using SIA", path, e)
            _cache[path] = (time.monotonic(), None)
            return None


def clear_cache() -> None:
    """Forget loaded indexes (tests, or after the directory is rebuilt in place)."""
    with _lock:
        _cache.clear()


def current() -> FrameIndex | None:
    """The index named by PXS_SPHEREX_INDEX (loaded once, cached), or None: use SIA."""
    path = os.environ.get(ENV_DIR, "").strip()
    return _index_for(path) if path else None


def try_lookup(ra: float, dec: float, radius_deg: float,
               collections: Sequence[str]) -> LocalResult | None:
    """Frames from the local index, or None when SIA must be used instead.

    None means: PXS_SPHEREX_INDEX unset, the index missing or unreadable, a requested
    release absent from it (stale), or any error during the lookup.
    """
    idx = current()
    if idx is None:
        return None
    wanted = {c.removeprefix("spherex_").removesuffix("_deep") for c in collections}
    if not wanted <= idx.releases:
        log.warning("index lacks release(s) %s; using SIA", sorted(wanted - idx.releases))
        return None
    try:
        t0 = time.perf_counter()
        frames = idx.find([(ra, dec)], radius_deg, collections)
        log.info("frames from local index: %d in %.1f ms", len(frames),
                 1e3 * (time.perf_counter() - t0))
    except Exception:
        log.exception("local index lookup failed; using SIA")
        return None
    tail = os.environ.get(ENV_TAIL, "").strip().lower() in ("1", "true", "yes", "on")
    return LocalResult(frames, idx.max_mjd(sorted(wanted)) if tail else None)


def main(argv: list[str] | None = None) -> None:
    """python -m pxs.spherex.localindex --build-cache DIR: write DIR/cache-v1.npz."""
    ap = argparse.ArgumentParser(description="Build the SPHEREx frame index cache.")
    ap.add_argument("--build-cache", type=Path, required=True, metavar="DIR",
                    help="index directory holding manifest.json and rows/")
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    path = write_cache(a.build_cache)
    print(f"wrote {path} ({path.stat().st_size / 1e6:.0f} MB) in {time.monotonic() - t0:.1f} s")


if __name__ == "__main__":
    main()
