#!/bin/sh
# Run the body mode for each designation given, one after another, logging each.
#   sh probes/solarsystem/run_all.sh <outdir> Haumea Makemake Eris ...
out="$1"; shift
mkdir -p "$out"
for b in "$@"; do
  start=$(date +%s)
  uv run python -m pxs.solarsystem --body "$b" --out "$out" > "$out/$b.log" 2>&1
  echo "$b exit $? in $(( $(date +%s) - start )) s"
done
