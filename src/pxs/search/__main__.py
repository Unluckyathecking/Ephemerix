"""python -m pxs.search --ra RA --dec DEC [--fov ARCSEC] --out DIR (same as pxs.movers)."""

from pxs.movers.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
