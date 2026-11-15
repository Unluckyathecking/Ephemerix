"""All-sky survey shortlist: large-amplitude Gaia DR3 LPVs (Miras) at high latitude with 10 < Ks < 12 and W1, W2 > 8.5."""
import json
import numpy as np
from tap import tap, GAIA, CACHE
from candidates import irsa_xmatch, in_chunks

if __name__ == "__main__":
    t = tap(GAIA, "SELECT v.source_id, v.frequency, v.frequency_error, v.amplitude, v.is_cstar, g.ra, g.dec, g.b, g.phot_g_mean_mag AS gmag, g.pmra, g.pmdec FROM gaiadr3.vari_long_period_variable AS v JOIN gaiadr3.gaia_source AS g ON g.source_id = v.source_id WHERE v.amplitude > 1.5 AND v.frequency IS NOT NULL AND ABS(g.b) > 25", timeout=3000)
    print(len(t), "high-latitude LPVs with G amplitude > 1.5 mag")
    rec = {int(r["source_id"]): {c: (None if np.ma.is_masked(r[c]) else r[c].item()) for c in t.colnames if c not in ("is_cstar",)} | {"cstar": str(r["is_cstar"])} for r in t}
    xm = irsa_xmatch([(i, d["ra"], d["dec"]) for i, d in rec.items()])
    for i, d in xm.items():
        rec[i].update(d)
    out = list(rec.values())
    (CACHE / "allsky_lpv.json").write_text(json.dumps(out, default=str))
    ok = [d for d in out if d.get("ks_m") and 10.0 <= d["ks_m"] <= 12.0 and d.get("w1mpro") and d["w1mpro"] > 8.5]
    ok.sort(key=lambda d: -d["amplitude"])
    print(len(ok), "with 10<Ks<12 and W1>8.5")
    for d in ok[:30]:
        print(f"{d['source_id']} {d['ra']:9.4f} {d['dec']:+8.4f} b={d['b']:+5.1f} G={d['gmag']:.2f} Ks={d['ks_m']:.2f} W1={d['w1mpro']:.2f} W2={d['w2mpro']} P={1/d['frequency']:.0f}d ampG={d['amplitude']:.2f} C={d['cstar']}")
