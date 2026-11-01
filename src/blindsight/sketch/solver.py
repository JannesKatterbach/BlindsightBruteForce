"""Constraint solver of the sketch (CAD style, modelled after Onshape).

Steps of ``solve``
  1. check the structure of points, entities and constraints
  2. solve all active constraints together (when dragging with the target as a soft wish)
  3. if that fails, find conflicts. Constraints are added one by one, one that can no longer be satisfied
     contradicts the previous ones
  4. determine the rank of the satisfied constraints. Degrees of freedom, redundancy and which points and
     entities are fully determined follow from it (Onshape draws them black, the free ones blue)
  5. derive housing hull and gear (profile.py)
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..i18n import tr
from ..units import is_finite_number
from .constraints import compile_constraint, constraint_errors, constraint_label, implicit_residuals
from .entities import Vars, Vector, ref_kind, sketch_dict, validate_structure
from .numeric import Residuals, determined_variables, levenberg_marquardt, max_abs, row_space
from .profile import profile

TIME_LIMIT_S = 3.0  # upper limit of the computing time of one solver call
TOL_OK = 1e-6  # from here on a constraint counts as satisfied
DRAG_WEIGHT = 0.1  # weight of the drag target compared to the constraints

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
    defined_points: list[bool] = field(default_factory=list)  # per point. True if fully determined
    defined_entities: list[bool] = field(default_factory=list)  # per entity
    profile: dict = field(default_factory=dict)  # housing hull, gear, bbox

    def as_dict(self) -> dict:
        return asdict(self)


class _Timeout(Exception):
    pass


def _invalid(sk: Any, errors: list[str]) -> SolveResult:
    return SolveResult(False, sk, STATE_INVALID, 0, errors=errors)


def structure_errors(sk: dict, prefix: str = "motor.sketch") -> list[str]:
    """All problems of points, entities and constraints, with field path."""
    errs = validate_structure(sk, prefix)
    if errs:
        return errs
    for k, c in enumerate(sk["constraints"]):
        errs.extend(constraint_errors(sk, c, f"{prefix}.constraints[{k}]"))
    return errs


def _drag_wish(sk: dict, v: Vars, drag: Any, x0: Vector) -> Optional[Residuals]:
    """Soft residuals that pull the dragged point or entity towards the target, None for invalid input.

    drag = {"ref": "p3" or "e2", "target": [x, y], "grab": [x, y] (where the mouse took hold),
            "mode": "move" or "radius" (circles)}"""
    try:
        ref, (tx, ty) = drag["ref"], drag["target"]
        gx, gy = drag.get("grab") or (tx, ty)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(is_finite_number(c) for c in (tx, ty, gx, gy)) or ref == "o" or ref_kind(sk, ref) is None:
        return None
    if ref[0] == "p" or sk["entities"][int(ref[1:])]["type"] == "point":
        i = v.point_index(ref)
        return lambda x: [DRAG_WEIGHT * (x[2 * i] - tx), DRAG_WEIGHT * (x[2 * i + 1] - ty)]
    k = int(ref[1:])
    entity = sk["entities"][k]
    if entity["type"] == "circle" and drag.get("mode") == "radius":
        slot = v.radius_slot[k]
        c = entity["points"][0]
        r = math.hypot(tx - x0[2 * c], ty - x0[2 * c + 1])
        return lambda x: [DRAG_WEIGHT * (x[slot] - r)]
    dx, dy = tx - gx, ty - gy
    starts = [(i, x0[2 * i] + dx, x0[2 * i + 1] + dy) for i in entity["points"]]
    return lambda x: [DRAG_WEIGHT * d for i, px, py in starts for d in (x[2 * i] - px, x[2 * i + 1] - py)]


def _system(fns: list[Residuals]) -> Residuals:
    return lambda x: [r for fn in fns for r in fn(x)]


def _find_conflicts(sk: dict, v: Vars, items: list[tuple[int, dict]], implicit: list[Residuals], x0: Vector,
                    deadline: float) -> tuple[Vector, list[int]]:
    """Add constraints one by one. One that can no longer be satisfied counts as a conflict.

    Returns (solution of the consistent constraints, indices of the conflicting ones)."""
    accepted: list[Residuals] = list(implicit)
    conflicts: list[int] = []
    x = x0
    for k, c in items:
        fn = compile_constraint(sk, c, v, x0)
        x_trial, resid = levenberg_marquardt(_system(accepted + [fn]), None, x, deadline=deadline)
        if time.monotonic() > deadline:
            raise _Timeout
        if resid < TOL_OK:
            accepted.append(fn)
            x = x_trial
        else:
            conflicts.append(k)
    return x, conflicts


def _state(conflicts: list[int], redundant: list[bool], dof: int) -> str:
    if conflicts:
        return STATE_CONFLICT
    if any(redundant):
        return STATE_OVER
    return STATE_FULL if dof == 0 else STATE_UNDER


def solve(sketch: Any, drag: Optional[dict] = None, diagnose: bool = True, time_limit: float = TIME_LIMIT_S) -> SolveResult:
    """Solve the sketch. The positions of sketch are the start (minimal movement).

    drag pulls a point or an entity as close as possible to the target without violating constraints. If
    the target cannot be reached, the sketch stays unchanged. With conflicts the result holds the solution
    of the consistent constraints and ok is False. With diagnose=False the (expensive) search for the
    conflicting constraints is skipped and the sketch stays unchanged."""
    sk = sketch_dict(sketch)
    errs = structure_errors(sk)
    if errs:
        return _invalid(sk, errs)
    v = Vars(sk)
    x_start = v.vector()
    wish = None
    if drag is not None:
        wish = _drag_wish(sk, v, drag, x_start)
        if wish is None:
            return _invalid(sk, [tr("solver.bad_drag")])
    active = [(k, c) for k, c in enumerate(sk["constraints"]) if c["enabled"]]
    implicit = implicit_residuals(sk, v)
    try:
        x, conflicts, errors = _positions(sk, v, active, implicit, x_start, wish, diagnose, time.monotonic() + time_limit)
    except _Timeout:
        return _invalid(sk, [tr("solver.timeout")])
    return _analyse(sk, v, active, implicit, x_start, x, conflicts, errors)


def _positions(sk: dict, v: Vars, active: list[tuple[int, dict]], implicit: list[Residuals], x_start: Vector,
               wish: Optional[Residuals], diagnose: bool, deadline: float) -> tuple[Vector, list[int], list[Any]]:
    """Steps 2 and 3. Returns (positions, indices of conflicting constraints, errors)."""
    hard = _system(implicit + [compile_constraint(sk, c, v, x_start) for _, c in active])
    x = x_start
    if wish is not None:
        x, _ = levenberg_marquardt(hard, wish, x, deadline=deadline)
    x, resid = levenberg_marquardt(hard, None, x, deadline=deadline)  # after a drag the constraints take precedence
    if resid < TOL_OK:
        return x, [], []
    if time.monotonic() > deadline:
        raise _Timeout
    if wish is not None:
        return x_start, [], [tr("solver.drag_rejected")]
    if not diagnose:
        return x_start, [], [tr("solver.unsolved")]
    x, conflicts = _find_conflicts(sk, v, active, implicit, x_start, deadline)
    return x, conflicts, []


def _analyse(sk: dict, v: Vars, active: list[tuple[int, dict]], implicit: list[Residuals], x_start: Vector, x: Vector,
             conflicts: list[int], errors: list[Any]) -> SolveResult:
    """Steps 4 and 5 at the positions x. Rank, state of every constraint, determined geometry, profile."""
    cons = sk["constraints"]
    used = [(k, c) for k, c in active if k not in conflicts]
    # Orientation dependent constraints (signs, angle ends) always come from the start position
    fns_used = [compile_constraint(sk, c, v, x_start) for _, c in used]
    resid = max((max_abs(fn(x)) for fn in implicit + fns_used), default=0.0)  # determine again after the diagnosis
    basis, redundant_all = row_space(implicit + fns_used, x)
    redundant = redundant_all[len(implicit):]
    dof = v.size - len(basis)

    status = {k: "ok" for k, _ in active}
    messages: dict[int, Any] = {}
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

    solved = v.apply(x)
    known = determined_variables(basis, v.size)
    defined_points = [known[2 * i] and known[2 * i + 1] for i in range(v.n_points)]
    defined_entities = [all(defined_points[p] for p in e["points"]) and (k not in v.radius_slot or known[v.radius_slot[k]])
                        for k, e in enumerate(solved["entities"])]
    entries = []
    for k, c in enumerate(cons):
        entry = {"index": k, "status": status.get(k, "ok") if c["enabled"] else "disabled", "message": messages.get(k, "")}
        if c["enabled"] and entry["status"] != "conflict":
            entry["residual"] = max_abs(compile_constraint(sk, c, v, x_start)(x))
        entries.append(entry)
    prof = profile(solved)
    return SolveResult(
        ok=not errors, sketch=solved, state=_state(conflicts, redundant, dof), dof=dof, constraints=entries,
        errors=errors, warnings=list(prof.errors), defined_points=defined_points, defined_entities=defined_entities,
        profile=prof.as_dict(),
    )
