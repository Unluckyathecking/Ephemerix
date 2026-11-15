"""Solar System body mode: follow a known distant body across SPHEREx exposures.

Positions come from NASA/JPL Horizons with SPHEREx itself (Horizons id -163182) as the
observer, so the spacecraft's parallax is in the ephemeris. The pipeline then reuses
`pxs.spherex` read-only: frame search along the track, forced ePSF photometry at the
ephemeris position in every exposure, and the stack helpers on a grid that follows the
body. Products: a spectrum (mJy), a reflectance spectrum (divided by a solar model),
ice band depths, background controls at the same sky positions in other passes, and
body-centred and sky-fixed image stacks.

    python -m pxs.solarsystem --body <designation> --out <dir>

Units: degrees, arcsec where named, MJD (UTC), micrometres, mJy (F_nu), au.

Written with Claude Code.
"""

from .bodies import Body, load_bodies, resolve
from .horizons import EphemPoint, ephemeris_at, ephemeris_range

__all__ = ["Body", "EphemPoint", "ephemeris_at", "ephemeris_range", "load_bodies", "resolve"]
