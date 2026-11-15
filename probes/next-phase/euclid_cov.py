import json, time, requests, io, sys
from concurrent.futures import ThreadPoolExecutor
from astropy.io.votable import parse_single_table
T=json.load(open('data/targets.json'))
def one(t):
    url="https://irsa.ipac.caltech.edu/SIA"
    p={"COLLECTION":"euclid_dr1_wide_DpdMerBksMosaic","POS":f"CIRCLE {t['ra']} {t['dec']} 0.002","RESPONSEFORMAT":"VOTABLE"}
    t0=time.time()
    try:
        r=requests.get(url,params=p,timeout=120)
        tab=parse_single_table(io.BytesIO(r.content)).to_table()
        bands=sorted(set(str(x) for x in tab['energy_bandpassname'])) if len(tab) else []
        urls=[str(u) for u in tab['access_url']][:1] if len(tab) else []
        return t['slug'], len(tab), bands, round(time.time()-t0,1), urls, list(tab.colnames)[:0]
    except Exception as e:
        return t['slug'],'ERR',str(e)[:80],round(time.time()-t0,1),[],[]
with ThreadPoolExecutor(6) as ex:
    for r in ex.map(one,T): print(r)
