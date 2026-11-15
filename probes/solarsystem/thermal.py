"""Thermal over reflected flux (upper bound, subsolar temperature) for the bodies tested.

    uv run python probes/solarsystem/thermal.py
"""
import numpy as np

from pxs.solarsystem.solar import thermal_fraction

# name, r (au), geometric albedo, Bond albedo (assumed, rounded literature values)
BODIES = [("Haumea", 49.9, 0.7, 0.5), ("Makemake", 52.7, 0.8, 0.6), ("Eris", 95.6, 0.9, 0.7),
          ("Pluto", 35.2, 0.5, 0.4), ("Chiron", 18.5, 0.15, 0.05), ("Chariklo", 17.5, 0.04, 0.01),
          ("(153) Hilda", 4.1, 0.06, 0.02)]
for name, r, p, a in BODIES:
    f = {w: thermal_fraction(w, r, p, a) for w in (3.0, 4.0, 4.5, 5.0)}
    grid = np.linspace(2.0, 5.0, 301)
    cross = next((w for w in grid if thermal_fraction(w, r, p, a) > 0.1), None)
    print(f"{name:12s} r={r:5.1f} au: thermal/reflected at 3/4/4.5/5 um = "
          + ", ".join(f"{v:.1e}" for v in f.values())
          + (f"; exceeds 10% beyond {cross:.2f} um" if cross else "; < 10% everywhere to 5 um"))
