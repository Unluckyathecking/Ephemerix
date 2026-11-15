"""CLI: python -m pxs.movers (or pxs.search) --ra RA --dec DEC [--fov 1200] [--pass 0] --out DIR

Writes DIR/result.json (format in pxs.movers.result) and DIR/stamps/*.png.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .api import search_field


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pxs.movers",
                                 description="Search one SPHEREx pass of a field for slow "
                                             "movers (experimental).")
    ap.add_argument("--ra", type=float, required=True, help="field centre RA, degrees")
    ap.add_argument("--dec", type=float, required=True, help="field centre Dec, degrees")
    side = ap.add_mutually_exclusive_group()
    side.add_argument("--fov", type=float, help="field side, ARCSEC (default 1200 = 20'; "
                      "unlike the view API's 120-480, a search needs a wide field)")
    side.add_argument("--size", type=float, help="field side, arcmin (default 20)")
    ap.add_argument("--pass", dest="pass_index", type=int, default=0,
                    help="index of the pass among the field's usable passes, oldest first")
    ap.add_argument("--completeness", type=int, default=0,
                    help="injection runs for the limit (25 sources each; 0 = skip)")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    args = ap.parse_args(argv)
    size = args.fov / 60.0 if args.fov is not None else (args.size or 20.0)
    if not (0 <= args.ra < 360 and -90 <= args.dec <= 90 and 2 <= size <= 40):
        ap.error("need 0 <= ra < 360, -90 <= dec <= 90 and a side of 2-40 arcmin "
                 "(fov 120-2400 arcsec)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    res = search_field((args.ra, args.dec), size, args.pass_index, out_dir=args.out,
                       completeness_runs=args.completeness)
    res.write(args.out / "result.json")
    logging.getLogger(__name__).info("%d candidates; wrote %s", len(res.candidates),
                                     args.out / "result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
