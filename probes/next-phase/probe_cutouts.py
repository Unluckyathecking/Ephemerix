"""Time public cutout routes. Saves each response under cache/next-phase/. Read-only probe."""
import time, sys, requests, urllib.parse as up
from pathlib import Path
OUT = Path("cache/next-phase"); OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "space-apps-2026 scoping probe (python-requests)"}
D = (43.7754, -47.0157)      # DENIS 0255-4700: Euclid DR1, DES/Legacy, VHS, SkyMapper
W = (133.7601, -7.2422)      # WISE 0855 at 2025.85: PS1, UKIDSS-LAS?, 2MASS, DSS
def h2f(hips, ra, dec, fov=0.0667, n=240, fmt="fits", host="alasky.cds.unistra.fr"):
    return (f"https://{host}/hips-image-services/hips2fits?hips={up.quote(hips, safe='')}"
            f"&width={n}&height={n}&fov={fov}&projection=TAN&coordsys=icrs&ra={ra}&dec={dec}&format={fmt}")
URLS = {
 "legacy_dr10_griz.fits": f"https://www.legacysurvey.org/viewer/cutout.fits?ra={D[0]}&dec={D[1]}&layer=ls-dr10&pixscale=0.262&size=240&bands=griz",
 "legacy_dr10.jpg":       f"https://www.legacysurvey.org/viewer/cutout.jpg?ra={D[0]}&dec={D[1]}&layer=ls-dr10&pixscale=0.262&size=240",
 "legacy_unwise_neo11.fits": f"https://www.legacysurvey.org/viewer/cutout.fits?ra={W[0]}&dec={W[1]}&layer=unwise-neo11&pixscale=2.75&size=88",
 "ps1_filenames.txt":     f"https://ps1images.stsci.edu/cgi-bin/ps1filenames.py?ra={W[0]}&dec={W[1]}&filters=grizy",
 "twomass_sia.xml":       f"https://irsa.ipac.caltech.edu/cgi-bin/2MASS/IM/nph-im_sia?POS={W[0]},{W[1]}&SIZE=0.01&FORMAT=image/fits",
 "dss2_red.fits":         f"https://archive.stsci.edu/cgi-bin/dss_search?v=poss2ukstu_red&r={W[0]}&d={W[1]}&e=J2000&h=4&w=4&f=fits",
 "dss1_red.fits":         f"https://archive.stsci.edu/cgi-bin/dss_search?v=poss1_red&r={W[0]}&d={W[1]}&e=J2000&h=4&w=4&f=fits",
 "h2f_2mass_K.fits":      h2f("CDS/P/2MASS/K", *W),
 "h2f_vhs_J.fits":        h2f("wfau.roe.ac.uk/P/VISTA/VHS/J", *D),
 "h2f_ukidss_las_K.fits": h2f("wfau.roe.ac.uk/P/UKIDSS/LAS/K", *W),
 "h2f_dss2_red.fits":     h2f("CDS/P/DSS2/red", *W),
 "h2f_akari_wideS.fits":  h2f("CDS/P/AKARI/FIS/WideS", *W, fov=0.5, n=120),
 "h2f_euclid_q1_J.fits":  h2f("CDS/P/Euclid/Q1/NISP.J", 61.24, -48.42),
 "euclid_dr1_J_cutout.fits": "https://irsacloud.ipac.caltech.edu/ibe/data/euclid/dr1/MER/102022453/NISP/EUC_MER_BGSUB-MOSAIC-NIR-J_TILE102022453-AECB5F_20250804T154603.737222Z_00.00.fits"
                             f"?center={D[0]},{D[1]}&size=60arcsec",
 "skymapper_dr4_siap.xml": f"https://api.skymapper.nci.org.au/public/siap/dr4/query?POS={D[0]},{D[1]}&SIZE=0.01&FORMAT=image/fits&RESPONSEFORMAT=VOTABLE",
 "cadc_sia2.xml":         "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia/v2query?POS=" + up.quote(f"CIRCLE {D[0]} {D[1]} 0.005") + "&MAXREC=200",
 "ztf_ref_search.tbl":    f"https://irsa.ipac.caltech.edu/ibe/search/ztf/products/ref?POS={W[0]},{W[1]}&ct=csv",
}
names = sys.argv[1:] or list(URLS)
for name in names:
    url = URLS[name]; t0 = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=120)
        dt = time.time() - t0
        (OUT / name).write_bytes(r.content)
        sig = r.content[:6]
        print(f"{name:28s} {r.status_code} {dt:6.2f}s {len(r.content)/1024:8.1f} kB  {r.headers.get('content-type','')[:30]:30s} {sig!r}")
    except Exception as e:
        print(f"{name:28s} ERR {time.time()-t0:6.2f}s {type(e).__name__}: {str(e)[:90]}")
    print("   ", url)
