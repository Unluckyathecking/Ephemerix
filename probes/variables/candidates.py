"""Gaia DR3 variables inside the SPHEREx deep fields, with 2MASS Ks and AllWISE W1/W2 via Gaia best-neighbour tables.

Step 1: gaia_source in a ra/dec box with phot_variable_flag='VARIABLE' (index-friendly).
Step 2: per-class tables by source_id. Step 3: 2MASS/AllWISE by source_id. Step 4: deep-field frame coverage.
"""
import json
import numpy as np
from tap import tap, GAIA, CACHE
from footprint import coverage

BOXES = {"north": "g.dec BETWEEN 61.0 AND 72.5 AND g.ra BETWEEN 252.0 AND 288.0",
         "south": "g.dec BETWEEN -71.0 AND -54.0 AND g.ra BETWEEN 62.0 AND 98.0"}
XM = """LEFT JOIN gaiadr3.tmass_psc_xsc_best_neighbour AS tb ON tb.source_id = g.source_id
LEFT JOIN gaiadr1.tmass_original_valid AS tm ON tm.designation = tb.original_ext_source_id
LEFT JOIN gaiadr3.allwise_best_neighbour AS ab ON ab.source_id = g.source_id
LEFT JOIN gaiadr1.allwise_original_valid AS aw ON aw.designation = ab.original_ext_source_id"""
TABLES = {
    "rrl": ("gaiadr3.vari_rrlyrae", "pf, p1_o, peak_to_peak_g AS amp_g, epoch_g, best_classification AS cls"),
    "cep": ("gaiadr3.vari_cepheid", "pf, p1_o, peak_to_peak_g AS amp_g, epoch_g, type_best_classification AS cls"),
    "lpv": ("gaiadr3.vari_long_period_variable", "frequency, amplitude AS amp_g, is_cstar"),
    "ecl": ("gaiadr3.vari_eclipsing_binary", "frequency, global_ranking, reference_time, derived_primary_ecl_phase AS ecl_phase, derived_primary_ecl_depth AS depth, derived_primary_ecl_duration AS dur, model_type"),
    "cls": ("gaiadr3.vari_classifier_result", "best_class_name, best_class_score"),
}


def in_chunks(ids, fn, n=500):
    rows = []
    for i in range(0, len(ids), n):
        rows.append(fn(",".join(str(x) for x in ids[i:i + n])))
    return rows


DISCS = {"north": (270.0, 66.56, 4.5), "south": (80.0, -61.5, 5.0)}  # dense part of each deep field (footprint.py)


def id_ranges(region):
    """Gaia source_id ranges covering a disc: source_id // 2**35 is the nested HEALPix level-12 index."""
    from astropy_healpix import HEALPix
    import astropy.units as u
    from astropy.coordinates import Longitude, Latitude
    ra, dec, r = DISCS[region]
    pix = sorted(HEALPix(nside=64, order="nested").cone_search_lonlat(Longitude(ra * u.deg), Latitude(dec * u.deg), r * u.deg))
    step = 4 ** 6 * 2 ** 35
    runs = []
    for p in pix:
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return [(a * step, (b + 1) * step - 1) for a, b in runs]


def irsa_xmatch(pos):
    """AllWISE (with its 2MASS J/H/Ks) within 3 arcsec of each Gaia position, via an IRSA TAP upload."""
    import pyvo
    from astropy.table import Table
    tag = CACHE / f"xm_{abs(hash(tuple(p[0] for p in pos))) % 10**12}.json"
    if tag.exists():
        return {int(k): v for k, v in json.loads(tag.read_text()).items()}
    svc = pyvo.dal.TAPService("https://irsa.ipac.caltech.edu/TAP")
    q = ("SELECT u.sid, a.designation AS allwise, a.w1mpro, a.w2mpro, a.ph_qual AS aw_qual, a.cc_flags, "
         "a.j_m_2mass AS j_m, a.h_m_2mass AS h_m, a.k_m_2mass AS ks_m FROM allwise_p3as_psd AS a, TAP_UPLOAD.u AS u "
         "WHERE CONTAINS(POINT('ICRS', a.ra, a.dec), CIRCLE('ICRS', u.ra, u.dec, 0.000833)) = 1")
    import time
    from astropy.table import vstack
    parts = []
    for i in range(0, len(pos), 150):
        up = Table(rows=pos[i:i + 150], names=("sid", "ra", "dec"), dtype=(np.int64, float, float))
        for attempt in range(4):
            try:
                parts.append(svc.run_sync(q, uploads={"u": up}).to_table())
                break
            except Exception as e:  # noqa: BLE001
                print("xmatch retry", attempt, str(e)[:100]); time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError("xmatch failed")
    res = vstack([x for x in parts if len(x)])
    out = {}
    for r in res:
        out[int(r["sid"])] = {c: (None if np.ma.is_masked(r[c]) else (r[c].item() if hasattr(r[c], "item") else str(r[c]))) for c in res.colnames if c != "sid"}
    tag.write_text(json.dumps(out, default=str))
    return out


def build(region, gmax=18.0):
    rng = " OR ".join(f"(source_id BETWEEN {a} AND {b})" for a, b in id_ranges(region))
    ids = set()
    for kind, (table, cols) in TABLES.items():
        if kind == "cls":
            continue
        t = tap(GAIA, f"SELECT source_id FROM {table} WHERE {rng}")
        ids |= {int(x) for x in t["source_id"]}
    ids = sorted(ids)
    rows = in_chunks(ids, lambda c: tap(GAIA, f"SELECT g.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.parallax, g.phot_g_mean_mag AS gmag, g.bp_rp FROM gaiadr3.gaia_source AS g WHERE g.source_id IN ({c}) AND g.phot_g_mean_mag < {gmax}"))
    from astropy.table import vstack
    base = vstack([r for r in rows if len(r)])
    ids = [int(x) for x in base["source_id"]]
    rec = {int(r["source_id"]): {c: (None if np.ma.is_masked(r[c]) else r[c].item() if hasattr(r[c], "item") else r[c]) for c in base.colnames} for r in base}
    for kind, (table, cols) in TABLES.items():
        for t in in_chunks(ids, lambda c: tap(GAIA, f"SELECT source_id, {cols} FROM {table} WHERE source_id IN ({c})")):
            for r in t:
                d = rec[int(r["source_id"])]
                if kind != "cls":
                    d["kind"] = kind
                for c in t.colnames:
                    if c != "source_id":
                        v = r[c]
                        d[f"{kind}_{c}"] = None if np.ma.is_masked(v) else (v.item() if hasattr(v, "item") else str(v))
    try:
        xm = irsa_xmatch([(i, rec[i]["ra"], rec[i]["dec"]) for i in ids])
    except Exception as e:  # noqa: BLE001 - IRSA upload crossmatch failed repeatedly on 14 Nov; rank on Gaia alone
        print("crossmatch unavailable:", e)
        xm = {}
    for i, d in xm.items():
        rec[i].update(d)
    out = list(rec.values())
    cov = coverage(np.array([d["ra"] for d in out]), np.array([d["dec"] for d in out])) if out else []
    for d, c in zip(out, cov):
        d["cov"] = int(c)
        d["region"] = region
    return out


if __name__ == "__main__":
    allrec = []
    for region in ("north", "south"):
        allrec += build(region)
    (CACHE / "gaia_vars_deep.json").write_text(json.dumps(allrec, default=str))
    sel = [d for d in allrec if d.get("ks_m") is not None and 8.5 <= float(d["ks_m"]) <= 14.0 and d["cov"] > 200]
    print(len(allrec), "variables;", len(sel), "with 8.5<Ks<14 and coverage>200")
    from collections import Counter
    print(Counter((d["region"], d.get("kind", d.get("cls_best_class_name"))) for d in sel).most_common(40))
