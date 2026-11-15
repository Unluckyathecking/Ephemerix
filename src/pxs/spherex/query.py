"""Find SPHEREx Level-2 frames with IRSA SIA2, and group them into survey passes."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from astropy.io.votable import parse_single_table

from pxs.astrometry import propagate
from pxs.concurrency import irsa_slot

from . import config, localindex
from .net import check_status, session, with_retries
from .types import Frame, Pass, Target, check_position

log = logging.getLogger(__name__)


def s3_key(access_url: str, cloud_access: str) -> str:
    """Bucket key of a frame: `cloud_access.aws.key` if present, else derived from access_url."""
    if cloud_access.strip():
        key = json.loads(cloud_access).get("aws", {}).get("key")
        if key:
            return str(key)
    if not access_url.startswith(config.IBE_PREFIX):
        raise ValueError(f"cannot derive an S3 key from {access_url!r}")
    return access_url[len(config.IBE_PREFIX):]


def parse_votable(content: bytes, collection: str) -> list[Frame]:
    """Frames from an SIA2 VOTable response. Rows that are not science frames are skipped."""
    tab = parse_single_table(io.BytesIO(content)).to_table(use_names_over_ids=True)
    out = []
    for row in tab:
        if str(row["dataproduct_subtype"]) != "science":
            continue
        out.append(Frame(
            collection=collection,
            obs_id=str(row["obs_id"]),
            detector=int(str(row["energy_bandpassname"])[-1]),
            mjd=0.5 * (float(row["t_min"]) + float(row["t_max"])),
            s3_key=s3_key(str(row["access_url"]), str(row["cloud_access"])),
            em_min_um=float(row["em_min"]) * 1e6,
            em_max_um=float(row["em_max"]) * 1e6,
        ))
    return out


def _sia_bytes(collection: str, ra: float, dec: float, radius_deg: float) -> bytes:
    """SIA2 VOTable for one collection, cached on disk for config.SIA_MAX_AGE_S."""
    params = {"COLLECTION": collection, "POS": f"circle {ra:.7f} {dec:.7f} {radius_deg:.7f}",
              "RESPONSEFORMAT": "VOTABLE"}
    tag = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    path: Path = config.cache_dir() / "sia" / f"{tag}.xml"
    if path.exists() and time.time() - path.stat().st_mtime < config.SIA_MAX_AGE_S:
        return path.read_bytes()

    def go() -> bytes:
        with irsa_slot():
            r = session().get(config.SIA_URL, params=params, timeout=config.SIA_TIMEOUT_S)
        check_status(r, f"SIA {collection}")
        return r.content

    content = with_retries(go, f"SIA {collection}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def find_frames(ra: float, dec: float, radius_deg: float = config.POINT_RADIUS_DEG,
                collections: Sequence[str] = config.COLLECTIONS) -> list[Frame]:
    """All frames whose footprint touches the circle (ra, dec, radius_deg), sorted by MJD.

    With PXS_SPHEREX_INDEX set, frames come from the local index (localindex.py) and SIA is
    the fallback; PXS_SPHEREX_INDEX_SIA_TAIL=1 adds SIA frames newer than the index.

    Collections are queried in parallel. A collection that fails after retries is
    logged and skipped (it then contributes no frames); if every collection fails, this
    raises RuntimeError, so "the archive failed" is never reported as "no frames here".
    """
    check_position(ra, dec)
    if not (math.isfinite(radius_deg) and 0 < radius_deg <= 1.0):
        raise ValueError(f"radius_deg must be in (0, 1], got {radius_deg}")
    local = localindex.try_lookup(ra, dec, radius_deg, collections)  # None: use SIA
    if local is not None and local.sia_after_mjd is None:
        return local.frames

    def one(coll: str) -> list[Frame] | None:
        try:
            return parse_votable(_sia_bytes(coll, ra, dec, radius_deg), coll)
        except Exception as e:  # noqa: BLE001 - one collection failing is not fatal
            log.warning("SIA query of %s failed: %s", coll, e)
            return None

    with ThreadPoolExecutor(max_workers=max(1, len(collections))) as ex:
        results = list(ex.map(one, collections))
    if collections and all(r is None for r in results):
        if local is not None:  # index plus SIA tail: the index alone is still a valid answer
            return local.frames
        raise RuntimeError(f"every SIA query failed ({', '.join(collections)})")
    frames = [f for fs in results if fs for f in fs]
    if local is not None:
        have = {f.s3_key for f in local.frames}
        frames = local.frames + [f for f in frames
                                 if f.mjd > local.sia_after_mjd and f.s3_key not in have]
    return sorted(frames, key=lambda f: (f.mjd, f.detector))


def search_circle(target: Target) -> tuple[float, float, float]:
    """(ra, dec, radius_deg) covering the target's path over config.MOVER_SPAN_YEARS."""
    if not target.has_pm:
        return target.ra, target.dec, config.POINT_RADIUS_DEG
    pts = [propagate(target.ra, target.dec, target.epoch, target.pmra_masyr, target.pmdec_masyr, yr)
           for yr in config.MOVER_SPAN_YEARS]
    (ra0, dec0), (ra1, dec1) = pts
    dra = ((ra1 - ra0 + 180.0) % 360.0 - 180.0) * math.cos(math.radians(0.5 * (dec0 + dec1)))
    half_arc = 0.5 * math.hypot(dra, dec1 - dec0)
    mid = propagate(target.ra, target.dec, target.epoch, target.pmra_masyr, target.pmdec_masyr,
                    sum(config.MOVER_SPAN_YEARS) / 2)
    return float(mid[0]), float(mid[1]), half_arc + config.POINT_RADIUS_DEG


def find_frames_for_target(target: Target,
                           collections: Sequence[str] = config.COLLECTIONS) -> list[Frame]:
    """find_frames over a circle that covers a moving target's 2025-2027 positions."""
    ra, dec, radius = search_circle(target)
    return find_frames(ra, dec, radius, collections)


def group_passes(frames: Sequence[Frame], gap_days: float = config.PASS_GAP_DAYS) -> list[Pass]:
    """Split frames (any order) into passes wherever consecutive MJDs differ by > gap_days."""
    ordered = sorted(frames, key=lambda f: (f.mjd, f.detector))
    groups: list[list[Frame]] = []
    for f in ordered:
        if groups and f.mjd - groups[-1][-1].mjd <= gap_days:
            groups[-1].append(f)
        else:
            groups.append([f])
    return [Pass(tuple(g)) for g in groups]
