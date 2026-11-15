#!/bin/sh
# Stage 2-3 campaign: three TNO fields and blank high-latitude fields, 8 injection runs each.
# Run from the repository root with PXS_CACHE pointing at ./cache.
set -u
run() { uv run python probes/movers/campaign.py "$@" > "cache/movers/campaign_$1.log" 2>&1; }
mkdir -p cache/movers
run Haumea 218.64096674077047 15.037436666666666 0 8 "[127,137]"
run Makemake 200.63287453322357 21.04122 2 8 "[46,119]"
run Eris 27.44204680308583 -0.16590999999981082 0 8 "[136,68]"
for f in "B1 160.0 10.0" "B2 180.0 -5.0" "B3 30.0 20.0" "B4 350.0 5.0" "B5 230.0 -10.0" \
         "B6 140.0 25.0" "B7 10.0 -15.0"; do
  set -- $f
  run "$1" "$2" "$3" 0 4
done
