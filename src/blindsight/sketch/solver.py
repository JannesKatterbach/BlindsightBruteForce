"""Constraint solver of the sketch (CAD style).

Steps of ``solve``
  1. check the structure and orient the outline counter clockwise
  2. solve all active constraints together (when dragging with the target as a soft wish)
  3. if that fails, find conflicts. Constraints are added one by one, one that can no longer be
     satisfied contradicts the previous ones
  4. determine the rank of the satisfied constraints. Degrees of freedom and redundancy follow from it
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..geometry import signed_area
from ..i18n import tr
from ..units import is_finite_number
from .constraints import SketchGeometry, compile_constraint, constraint_label
from .numeric import Residuals, Vector, constraint_rank, levenberg_marquardt, max_abs
from .polygon import bounding_box, gear_overlap_message, measures, polygon_report
from .structure import normalize_orientation, reversed_point_index, sketch_dict, validate_structure

TIME_LIMIT_S = 3.0  # upper limit of the computing time of one solver call
TOL_OK = 1e-6  # from here on a constraint counts as satisfied
MIN_AREA = 1e-12  # a smaller area counts as a degenerate outline
DRAG_WEIGHT = 0.1  # weight of the drag target compared to the constraints
REF_NUDGE = 1e-3  # move the start position away from a reference (the distance is not differentiable there)

# States
STATE_UNDER = "under"  # degrees of freedom left
STATE_FULL = "full"  # fully determined
STATE_OVER = "over"  # at least one constraint is redundant
STATE_CONFLICT = "conflict"  # at least one constraint contradicts the others
STATE_INVALID = "invalid"  # input invalid or not solvable


@dataclass
class SolveResult:
    ok: bool
    sketch: dict
    state: str  # STATE_*
    dof: int
    constraints: list[dict] = field(default_factory=list)  # per constraint {index, status, message, residual}
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    convex: bool = False
    measures: dict = field(default_factory=dict)
    bbox: Optional[dict] = None
    reoriented: bool = False  # the point order was reversed (the input was clockwise)

    def as_dict(self) -> dict:
        return asdict(self)


class _Timeout(Exception):
    pass


def _invalid(sk: dict, errors: list[str], reoriented: bool = False) -> SolveResult:
    return SolveResult(False, sk, STATE_INVALID, 0, errors=errors, reoriented=reoriented)


def _parse_drag(drag: Any, n: int) -> Optional[tuple[int, float, float]]:
    """(point, target x, target y) or None for invalid input."""
    try:
        point, (tx, ty) = drag["point"], drag["target"]
    except (KeyError, TypeError, ValueError):
        return None
    if isinstance(point, bool) or not isinstance(point, int) or not 0 <= point < n:
        return None
    if not is_finite_number(tx) or not is_finite_number(ty):
        return None
    return point, float(tx), float(ty)


def _system(items: list[tuple[int, dict]], geo: SketchGeometry) -> Residuals:
    """All residuals of the constraints items as one function."""
    fns = [compile_constraint(c, geo) for _, c in items]
    return lambda x: [r for fn in fns for r in fn(x)]


def _nudge_off_references(x: Vector, items: list[tuple[int, dict]], geo: SketchGeometry) -> Vector:
    """Move points with a distance reference that lie exactly on their reference slightly."""
    x = x[:]
    for _, c in items:
        if c["type"] == "dist_point":
            rx, ry = geo.ref(c["ref"])
            i = c["a"]
            if math.hypot(x[2 * i] - rx, x[2 * i + 1] - ry) < 1e-6:
                x[2 * i] += REF_NUDGE
    return x


def _find_conflicts(items: list[tuple[int, dict]], x0: Vector, n: int, cd: float,
                    deadline: float) -> tuple[Vector, list[int]]:
    """Add constraints one by one. One that can no longer be satisfied counts as a conflict.

    Returns (solution of the consistent constraints, indices of the conflicting ones)."""
    accepted: list[tuple[int, dict]] = []
    conflicts: list[int] = []
    x = x0
    for item in items:
        trial = accepted + [item]
        x_trial, resid = levenberg_marquardt(_system(trial, SketchGeometry(n, cd, x)), None, x, deadline=deadline)
        if time.monotonic() > deadline:
            raise _Timeout
        if resid < TOL_OK:
            accepted, x = trial, x_trial
        else:
            conflicts.append(item[0])
    return x, conflicts


def _state(conflicts: list[int], redundant: list[bool], dof: int) -> str:
    if conflicts:
        return STATE_CONFLICT
    if any(redundant):
        return STATE_OVER
    return STATE_FULL if dof == 0 else STATE_UNDER


def solve(sketch: Any, cd: float = 5.0, drag: Optional[dict] = None, diagnose: bool = True,
          gear: Optional[tuple[float, float]] = None, time_limit: float = TIME_LIMIT_S) -> SolveResult:
    """Solve the sketch. The points of sketch are the start position (minimal movement).

    drag = {"point": i, "target": [x, y]} pulls a point as close as possible to the target without
    violating constraints. If the target cannot be reached, the sketch stays unchanged. With conflicts
    the result holds the solution of the consistent constraints and ok is False. With diagnose=False
    the (expensive) search for the conflicting constraints is skipped and the sketch stays unchanged.
    gear = (diameter, width) additionally checks whether the gear reaches into the housing (warning)."""
    sk = sketch_dict(sketch)
    errs = validate_structure(sk)
    if errs:
        return _invalid(sk, errs)
    if not is_finite_number(cd) or cd < 0:
        return _invalid(sk, [tr("solver.bad_cd")])
    n = len(sk["points"])
    target = None
    if drag is not None:
        target = _parse_drag(drag, n)
        if target is None:
            return _invalid(sk, [tr("solver.bad_drag")])
    sk, reoriented = normalize_orientation(sk)
    if reoriented and target is not None:
        target = (reversed_point_index(n, target[0]), target[1], target[2])
    if signed_area(sk["points"]) <= MIN_AREA:
        return _invalid(sk, [tr("solver.no_area")], reoriented)

    cons = sk["constraints"]
    active = [(k, c) for k, c in enumerate(cons) if c["enabled"]]
    x_start = [v for p in sk["points"] for v in p]
    x0 = _nudge_off_references(x_start, active, SketchGeometry(n, cd, x_start))
    hard = _system(active, SketchGeometry(n, cd, x0))
    deadline = time.monotonic() + time_limit

    errors: list[str] = []
    conflicts: list[int] = []
    if target is not None:
        point, tx, ty = target

        def pull(x: Vector) -> list[float]:
            return [DRAG_WEIGHT * (x[2 * point] - tx), DRAG_WEIGHT * (x[2 * point + 1] - ty)]

        x, _ = levenberg_marquardt(hard, pull, x0, deadline=deadline)
        x, resid = levenberg_marquardt(hard, None, x, deadline=deadline)  # polish. Constraints take precedence
    else:
        x, resid = levenberg_marquardt(hard, None, x0, deadline=deadline)
    if resid >= TOL_OK:
        if time.monotonic() > deadline:
            return _invalid(sk, [tr("solver.timeout")], reoriented)
        if target is not None:
            x = x_start
            errors.append(tr("solver.drag_rejected"))
        elif diagnose:
            try:
                x, conflicts = _find_conflicts(active, x0, n, cd, deadline)
            except _Timeout:
                return _invalid(sk, [tr("solver.timeout")], reoriented)
        else:
            x = x_start
            errors.append(tr("solver.unsolved"))

    used = [item for item in active if item[0] not in conflicts]
    geo = SketchGeometry(n, cd, x)
    fns_used = [compile_constraint(c, geo) for _, c in used]
    resid = max((max_abs(fn(x)) for fn in fns_used), default=0.0)  # determine again after the diagnosis
    rank, redundant = constraint_rank(fns_used, x)
    dof = 2 * n - rank

    status = {k: "ok" for k, _ in active}
    messages: dict[int, str] = {}
    for k in conflicts:
        status[k] = "conflict"
        messages[k] = tr("solver.conflict", label=constraint_label(cons[k], k))
        errors.append(messages[k])
    for (k, _), is_redundant in zip(used, redundant):
        if is_redundant:
            status[k] = "redundant"
            messages[k] = tr("solver.redundant", label=constraint_label(cons[k], k))
    if not errors and resid >= TOL_OK:
        errors.append(tr("solver.unsolved"))

    pts = [[x[2 * i], x[2 * i + 1]] for i in range(n)]
    report = polygon_report(pts)
    warnings: list[str] = [] if report["convex"] else list(report["problems"])
    if gear is not None and report["convex"]:
        message = gear_overlap_message(pts, cd, cd, gear[0], gear[1])
        if message:
            warnings.append(message)

    entries = []
    for k, c in enumerate(cons):
        st = status.get(k, "ok") if c["enabled"] else "disabled"
        entry = {"index": k, "status": st, "message": messages.get(k, "")}
        if c["enabled"] and st != "conflict":
            entry["residual"] = max_abs(compile_constraint(c, geo)(x))
        entries.append(entry)
    return SolveResult(
        ok=not errors, sketch={"points": pts, "constraints": cons}, state=_state(conflicts, redundant, dof),
        dof=dof, constraints=entries, errors=errors, warnings=warnings, convex=report["convex"],
        measures=measures(pts), bbox=bounding_box(pts), reoriented=reoriented,
    )
