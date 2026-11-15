"""Apparent motion of distant/solar-system bodies as seen by SPHEREx (observer ~ Earth, 1.01 au),
observed near solar elongation 90 deg. Circular heliocentric orbits, ecliptic frame."""
import numpy as np
PX = 6.15
YR = 365.25
def earth(t):  # t days; Earth at longitude 0 at t=0
    th = 2*np.pi*t/YR
    return 1.01*np.array([np.cos(th), np.sin(th), 0*th])
def body(t, r, lon0, lat):
    # circular orbit in plane inclined so the body sits at latitude `lat` now (moving roughly along longitude)
    n = 2*np.pi/(YR*r**1.5)
    lon = lon0 + n*t
    return r*np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)*np.ones_like(lon)])
def radec(v):
    v = v/np.linalg.norm(v, axis=0)
    return np.arctan2(v[1], v[0]), np.arcsin(v[2])
def sep(a, b):
    l1,b1=a; l2,b2=b
    return np.degrees(np.arccos(np.clip(np.sin(b1)*np.sin(b2)+np.cos(b1)*np.cos(b2)*np.cos(l1-l2),-1,1)))*3600
def elong(t, r, lon0, lat):
    e=earth(t); p=body(t,r,lon0,lat); d=p-e
    return np.degrees(np.arccos(np.dot(-e/np.linalg.norm(e), d/np.linalg.norm(d))))
def find_quad(r, lat, t0, span=YR):
    ts=np.arange(t0, t0+span, 0.05)
    el=np.array([elong(t,r,np.pi/2,lat) for t in ts])
    i=np.argmin(np.abs(el-90)); return ts[i]
print("dist_au lat_deg  6mo_shift_arcmin  6mo_px   in_pass(+-7d)_arcsec  in_pass_px   rate_arcsec_per_hr")
for r in [40, 200, 500, 1000]:
    for lat in [0, 20, 60]:
        la=np.radians(lat)
        t1=find_quad(r,la,0); t2=find_quad(r,la,t1+120,130)
        dt=t2-t1
        p=lambda t: radec(body(t,r,np.pi/2,la)-earth(t))
        s6=sep(p(t1),p(t2))
        sp=sep(p(t1-7),p(t1+7))
        rate=sep(p(t1-0.5),p(t1+0.5))/24
        print(f"dt={dt:5.0f}d {r:6d} {lat:5d} {s6/60:12.2f} {s6/PX:10.0f} {sp:14.1f} {sp/PX:12.2f} {rate:10.3f}")
print("\nMain-belt / NEO-ish circular orbits at elongation 90, lat 0:")
for r in [1.3, 2.2, 2.7, 3.2, 5.2]:
    t1=find_quad(r,0,0); p=lambda t: radec(body(t,r,np.pi/2,0)-earth(t))
    rate=sep(p(t1-0.5),p(t1+0.5))/24
    print(f"r={r} au: {rate:6.1f} arcsec/hr = {rate*24/3600:5.2f} deg/day; crosses 240\" field in {240/rate:5.1f} h")
