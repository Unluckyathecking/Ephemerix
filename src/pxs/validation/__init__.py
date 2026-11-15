"""Public scoreboard: score every gallery view against its published values.

`python -m pxs.validation` reads web/gallery/index.json, each gallery manifest and
data/targets.json, and writes web/data/validation.json for web/validation.html.

Pass rules (printed on the page from the same constants, see `rules.py`):

* Motion. Both proper-motion components must lie within 3 sigma of the catalogue value, where
  sigma is the error the tool states for that component. There is no percentage escape hatch:
  for a fast mover a 2% allowance is tens of sigma wide and would forgive a real error. The
  percentage difference is still printed as a column. The catalogue's own error is not
  included because data/targets.json does not carry one, so sigma is the tool's error alone.
* Type. The tool's spectral-type range must contain the published type. A published range
  ("T1-1.5") must sit wholly inside the tool's range; for an unresolved pair ("T1-1.5 + T6")
  any one published component inside the range counts. An open end of the tool's range
  (e.g. "Y1 or colder") is unbounded on that side.
* Refused. The tool had a spectrum but declined to classify it; the manifest's own reason
  is shown. A refusal is neither a pass nor a fail and is counted on its own.
* Not applicable. The check cannot be made: no usable spectrum at all, no published type that
  parses, or no stated motion error.

Nothing is hidden: failures, refusals, degraded builds and large centroid residuals are all
written out. The residual has no pass mark; it is reported as measured.
"""

from pxs.validation.report import build_report, main, write_report

__all__ = ["build_report", "main", "write_report"]
