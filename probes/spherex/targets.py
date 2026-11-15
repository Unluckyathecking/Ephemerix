"""Test targets and proper-motion propagation.

Astrometry from CDS Sesame/SIMBAD (resolved 14 Nov 2026). SIMBAD positions are
epoch J2000.0, so propagate from 2000.0 with the listed proper motion.
"""
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance
from astropy.time import Time

# name: (ra_deg J2000 epoch 2000, dec_deg, pmra mas/yr (incl cos dec), pmdec mas/yr, plx mas)
TARGETS = {
    "barnard": (269.4520769586187, 4.69336496657667, -801.551, 10362.394, 546.9759),
    "eps_ind_b": (331.04414658852124, -56.78284419511611, 3981.977, -2466.832, 270.658),
    "wise0855": (133.81890825, -7.247048, -8123.7, 673.2, 439.0),
    "rw_aur": (76.95652603458, 30.40143817389, 7.23, -20.33, 15.42),
    "r_dra": (248.16761083295, 66.75497941722, -20.643, 6.149, 1.2509),
}


def coord_at(name: str, epoch: Time | float | None = None) -> SkyCoord:
    """ICRS position of a target at `epoch` (Time, or MJD float). None -> J2000."""
    ra, dec, pmra, pmdec, plx = TARGETS[name]
    c = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, pm_ra_cosdec=pmra * u.mas / u.yr,
                 pm_dec=pmdec * u.mas / u.yr, distance=Distance(parallax=plx * u.mas),
                 obstime=Time("J2000.0"), frame="icrs")
    if epoch is None:
        return c
    t = epoch if isinstance(epoch, Time) else Time(epoch, format="mjd")
    return c.apply_space_motion(new_obstime=t)
