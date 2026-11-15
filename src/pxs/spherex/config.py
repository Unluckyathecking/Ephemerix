"""Constants for the SPHEREx data path. Values were measured on real frames."""

from __future__ import annotations

import os
from pathlib import Path

# Collections searched by default. DR1 and QR3 are disjoint, so no dedup is needed.
# The deep-field collections are opt-in (only fields near the ecliptic poles have any).
COLLECTIONS: tuple[str, ...] = ("spherex_dr1", "spherex_qr3")
DEEP_COLLECTIONS: tuple[str, ...] = ("spherex_dr1_deep", "spherex_qr3_deep")

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
IBE_PREFIX = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"
BUCKET = "nasa-irsa-spherex"
BUCKET_URL = f"https://{BUCKET}.s3.us-east-1.amazonaws.com/"  # public, anonymous
USER_AGENT = "planet-x-spherex"

# Network behaviour.
MAX_WORKERS = 8  # frames read concurrently by one read_many call
PASS_WORKERS = 32  # frames read concurrently while a whole pass is prefetched
S3_MAX_CONCURRENT = 64  # range reads in flight to the bucket, process-wide
BATCH_WORKERS = 4  # ranged GETs in flight per frame during a prefetch batch
# Worst case for one call: 2 attempts x 15 s + 0.75 s backoff = 31 s; a catalogue (SIA)
# query: 2 x 20 s + 0.75 s = 41 s. Slow-drip bodies are bounded by the build deadline.
TIMEOUT_S = 15.0
SIA_TIMEOUT_S = 60.0  # IRSA searches can take tens of seconds; 20 s timed out in production
RETRIES = 1
BACKOFF_S = 0.5  # first retry delay, doubled each time
BLOCK_BYTES = 64 * 1024  # cache granularity for S3 range reads
SIA_MAX_AGE_S = 24 * 3600  # frame lists grow weekly as QR3 is extended

# Search geometry.
POINT_RADIUS_DEG = 0.0005  # 1.8 arcsec, as validated
MOVER_SPAN_YEARS = (2025.0, 2027.0)  # SPHEREx survey years a fast mover must be covered over
PASS_GAP_DAYS = 20.0

# Detector and photometry.
PIXSCALE_ARCSEC = 6.15
PIX_SR = (PIXSCALE_ARCSEC / 206264.806) ** 2  # nominal pixel solid angle, sr
MJYSR_TO_MJY = PIX_SR * 1e9  # MJy/sr in one pixel -> mJy
STAMP_HALF = 15  # 31x31 px stamp for photometry
R_FIT = 3.0  # px, pixels used in the PSF fit
R_CORE = 1.5  # px, saturation is judged inside this radius
R_ANNULUS = (6.0, 10.0)  # px, background annulus
MIN_PSF_FRACTION = 0.3  # of the PSF inside R_FIT that must be unmasked
EPSF_OVERSAMPLE = 5
EPSF_SIZE = 33

# FLAGS bits (from the MSKN00nn header cards; identical in DR1 and QR3).
FLAG_BITS = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "NONFUNC": 6, "DICHROIC": 7,
    "MISSING_DATA": 9, "HOT": 10, "COLD": 11, "FULLSAMPLE": 12, "PHANMISS": 14,
    "NONLINEAR": 15, "PERSIST": 17, "OUTLIER": 19, "CROSSTALK": 20, "SOURCE": 21,
    "GHOST": 22, "GHOST_FPA": 23, "GHOST_EXT": 24, "STREAK": 25, "BLOOM": 26,
    "SNOWBALL": 27, "HALO": 28,
}
_BAD_NAMES = ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT", "COLD",
              "NONLINEAR", "PERSIST", "OUTLIER")
# SOURCE is set on every real star and must never be in this mask.
BAD_MASK = sum(1 << FLAG_BITS[n] for n in _BAD_NAMES)
# A core with OVERFLOW (or NaN) is saturated. SUR_ERROR alone is not: on Eps Ind B (59 mJy
# peak, far below saturation) it fires on the peak pixels of ~5% of frames with no OVERFLOW,
# so it is masked like any bad pixel and the 30% PSF rule decides ("masked").
SATURATION_MASK = 1 << FLAG_BITS["OVERFLOW"]
MISSING_MASK = 1 << FLAG_BITS["MISSING_DATA"]

# Fallback error scale when a pass has too few empty-position measurements to set its own.
# Measured per detector per pass (robust sigma of flux/err at 8 empty positions 8 px from the
# target) on DR1/QR3: 1.0-1.9 for Eps Ind B (4 passes), 1.0-1.8 for WISE 0855; 1.5 is typical.
ERROR_SCALE = 1.5


def byte_cache_enabled() -> bool:
    """Keep raw byte-range blocks on disk (0.5-0.8 GB per target)? Off unless PXS_BYTE_CACHE=1.

    The small per-frame stamp cache (cache/spherex/stamps/) is always on.
    """
    return os.environ.get("PXS_BYTE_CACHE", "").strip().lower() in ("1", "true", "yes", "on")


def cache_dir() -> Path:
    """Root of the on-disk cache. Override with PXS_CACHE; safe to delete at any time."""
    env = os.environ.get("PXS_CACHE")
    root = Path(env) if env else Path.cwd() / "cache"
    return root / "spherex"
