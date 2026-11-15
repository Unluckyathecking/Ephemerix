"""Probe: time to read 8 field-sized stamps with 8 threads, via the stamp cache."""
import logging
import sys
import time

sys.path.insert(0, "src")
from pxs.movers.frames import field_passes
from pxs.spherex.stamps import read_many

logging.basicConfig(level=logging.WARNING)
ra, dec, half = 218.4397, 14.7495, int(sys.argv[1])
fp = field_passes(ra, dec)
fr = fp.passes[0].frames[:8]
t = time.time()
b = read_many([(f, ra, dec) for f in fr], half=half, with_psf=True)
print(f"half={half}: {len(b.stamps)} stamps in {time.time()-t:.1f}s, failed {b.n_failed}")
