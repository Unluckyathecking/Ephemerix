"""WISE and NEOWISE single exposures, stacked per visit on the common grid. Written with Claude Code.

    visits = find_visits(ra, dec)                 # or path=path_from_motion(...) for a mover
    stack = stack_visit(visits[0], "W2", grid)    # pxs.grid.Stack in DN, or None

Frames are found with IRSA SIA2 plus a TAP quality lookup (one per mission phase, cached),
and read with two HTTP range requests each from the public bucket s3://nasa-irsa-wise.
"""

from pxs.procs import offloaded
from pxs.wise import stack as _stack
from pxs.wise.frames import Frame
from pxs.wise.visits import Visit, find_visits, group_visits, path_from_motion

# Reads frames and resamples them: in an "io" worker process when PXS_PROCESSES is set
# (pxs.procs), else in-process.
stack_visit = offloaded(_stack.stack_visit, pool="io")

__all__ = ["Frame", "Visit", "find_visits", "group_visits", "path_from_motion", "stack_visit"]
