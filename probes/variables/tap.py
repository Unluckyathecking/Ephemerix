"""Tiny cached TAP helpers for the variables probe (IRSA and ESA Gaia). Results cached under cache/variables/tap."""
import hashlib, io, json, sys, time
from pathlib import Path
import requests
from astropy.io.votable import parse_single_table

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "variables"
CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "planet-x-spherex-variables-probe"}
IRSA = "https://irsa.ipac.caltech.edu/TAP/sync"
GAIA = "https://gea.esac.esa.int/tap-server/tap/sync"


def tap(url, adql, timeout=600):
    tag = hashlib.sha1((url + adql).encode()).hexdigest()[:16]
    p = CACHE / "tap" / f"{tag}.xml"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        t = time.time()
        try:
            r = requests.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": adql},
                              headers=UA, timeout=180)
            if r.status_code != 200:
                raise RuntimeError(f"sync {r.status_code}: {r.text[:300]}")
            content = r.content
        except Exception as e:  # noqa: BLE001 - fall back to async for long queries
            print(f"sync failed ({str(e)[:120]}), trying async", file=sys.stderr)
            content = _async(url.replace("/sync", "/async"), adql, timeout)
        p.write_bytes(content)
        print(f"[tap {time.time()-t:.1f}s] {tag}", file=sys.stderr)
    return parse_single_table(io.BytesIO(p.read_bytes())).to_table(use_names_over_ids=True)


def _async(url, adql, timeout):
    """UWS async job: create, run, poll, fetch results."""
    r = requests.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": adql,
                                 "PHASE": "RUN"}, headers=UA, timeout=60, allow_redirects=False)
    job = r.headers.get("Location")
    if not job:
        raise RuntimeError(f"no job url: {r.status_code} {r.text[:800]}")
    t0 = time.time()
    while time.time() - t0 < timeout:
        ph = requests.get(job + "/phase", headers=UA, timeout=60).text.strip()
        if ph == "COMPLETED":
            res = requests.get(job + "/results/result", headers=UA, timeout=300)
            res.raise_for_status()
            return res.content
        if ph in ("ERROR", "ABORTED"):
            raise RuntimeError(f"{ph}: {requests.get(job + '/error', headers=UA, timeout=60).text[:1500]}")
        time.sleep(3)
    raise TimeoutError(job)


if __name__ == "__main__":
    which = IRSA if sys.argv[1] == "irsa" else GAIA
    print(tap(which, sys.argv[2]))
