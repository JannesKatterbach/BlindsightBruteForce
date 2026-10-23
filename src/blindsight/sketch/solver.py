"""Constraint Solver der Skizze (CAD Stil).

Ablauf von ``solve``
  1. Struktur pruefen und die Kontur gegen den Uhrzeigersinn ausrichten
  2. alle aktiven Constraints gemeinsam loesen (beim Ziehen mit dem Ziel als weichem Wunsch)
  3. scheitert das, Widersprueche finden. Constraints werden der Reihe nach hinzugenommen, wer
     sich nicht mehr erfuellen laesst, widerspricht den vorherigen
  4. Rang der erfuellten Constraints bestimmen. Daraus folgen Freiheitsgrade und Redundanz
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..geometry import signed_area
from ..units import is_finite_number
from .constraints import SketchGeometry, compile_constraint, constraint_label
from .numeric import Residuals, Vector, constraint_rank, levenberg_marquardt, max_abs
from .polygon import bounding_box, gear_overlap_message, measures, polygon_report
from .structure import normalize_orientation, reversed_point_index, sketch_dict, validate_structure

TIME_LIMIT_S = 3.0  # Obergrenze der Rechenzeit eines Solver Aufrufs
TOL_OK = 1e-6  # ab hier gilt ein Constraint als erfuellt
MIN_AREA = 1e-12  # kleinere Flaeche gilt als entartete Kontur
DRAG_WEIGHT = 0.1  # Gewicht des Ziehziels gegenueber den Constraints
REF_NUDGE = 1e-3  # Startlage weg von einer Referenz schieben (Abstand ist dort nicht differenzierbar)

# Zustaende
STATE_UNDER = "under"  # noch Freiheitsgrade
STATE_FULL = "full"  # voll bestimmt
STATE_OVER = "over"  # mindestens ein Constraint ist redundant
STATE_CONFLICT = "conflict"  # mindestens ein Constraint widerspricht den anderen
STATE_INVALID = "invalid"  # Eingabe ungueltig oder nicht loesbar

MSG_TIMEOUT = "Zeitlimit beim Loesen ueberschritten (zu viele oder zu komplizierte Constraints)"
MSG_DRAG_REJECTED = "Die gezogene Lage verletzt Constraints. Die Skizze bleibt unveraendert"
MSG_UNSOLVED = "Die Constraints lassen sich nicht gleichzeitig erfuellen"
MSG_BAD_DRAG = "drag. Erwartet {point, target:[x, y]} mit gueltigem Punkt"
MSG_BAD_CD = "cd. Achsabstand muss eine Zahl >= 0 sein"
MSG_NO_AREA = "motor.sketch.points. Die Kontur hat keine Flaeche"


@dataclass
class SolveResult:
    ok: bool
    sketch: dict
    state: str  # STATE_*
    dof: int
    constraints: list[dict] = field(default_factory=list)  # je Constraint {index, status, message, residual}
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    convex: bool = False
    measures: dict = field(default_factory=dict)
    bbox: Optional[dict] = None
    reoriented: bool = False  # die Punktreihenfolge wurde umgedreht (Eingabe war im Uhrzeigersinn)

    def as_dict(self) -> dict:
        return asdict(self)


class _Timeout(Exception):
    pass


def _invalid(sk: dict, errors: list[str], reoriented: bool = False) -> SolveResult:
    return SolveResult(False, sk, STATE_INVALID, 0, errors=errors, reoriented=reoriented)


def _parse_drag(drag: Any, n: int) -> Optional[tuple[int, float, float]]:
    """(Punkt, Ziel x, Ziel y) oder None bei ungueltiger Angabe."""
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
    """Alle Residuen der Constraints items als eine Funktion."""
    fns = [compile_constraint(c, geo) for _, c in items]
    return lambda x: [r for fn in fns for r in fn(x)]


def _nudge_off_references(x: Vector, items: list[tuple[int, dict]], geo: SketchGeometry) -> Vector:
    """Punkte mit Abstandsbezug, die genau auf ihrer Referenz liegen, leicht verschieben."""
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
    """Nimmt Constraints der Reihe nach hinzu. Wer sich nicht mehr erfuellen laesst, gilt als Widerspruch.

    Rueckgabe (Loesung der widerspruchsfreien Constraints, Indizes der widerspruechlichen)."""
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
    """Loest die Skizze. Die Punkte aus sketch sind die Startlage (minimale Bewegung).

    drag = {"point": i, "target": [x, y]} zieht einen Punkt so nah wie moeglich an das Ziel, ohne
    Constraints zu verletzen. Laesst sich das Ziel nicht erreichen, bleibt die Skizze unveraendert.
    Bei Widerspruechen enthaelt das Ergebnis die Loesung der widerspruchsfreien Constraints und ok ist
    False. Mit diagnose=False wird die (teure) Suche nach den widerspruechlichen Constraints
    uebersprungen, die Skizze bleibt dann unveraendert.
    gear = (Durchmesser, Breite) prueft zusaetzlich, ob das Zahnrad ins Gehaeuse ragt (Warnung)."""
    sk = sketch_dict(sketch)
    errs = validate_structure(sk)
    if errs:
        return _invalid(sk, errs)
    if not is_finite_number(cd) or cd < 0:
        return _invalid(sk, [MSG_BAD_CD])
    n = len(sk["points"])
    target = None
    if drag is not None:
        target = _parse_drag(drag, n)
        if target is None:
            return _invalid(sk, [MSG_BAD_DRAG])
    sk, reoriented = normalize_orientation(sk)
    if reoriented and target is not None:
        target = (reversed_point_index(n, target[0]), target[1], target[2])
    if signed_area(sk["points"]) <= MIN_AREA:
        return _invalid(sk, [MSG_NO_AREA], reoriented)

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
        x, resid = levenberg_marquardt(hard, None, x, deadline=deadline)  # Politur. Constraints haben Vorrang
    else:
        x, resid = levenberg_marquardt(hard, None, x0, deadline=deadline)
    if resid >= TOL_OK:
        if time.monotonic() > deadline:
            return _invalid(sk, [MSG_TIMEOUT], reoriented)
        if target is not None:
            x = x_start
            errors.append(MSG_DRAG_REJECTED)
        elif diagnose:
            try:
                x, conflicts = _find_conflicts(active, x0, n, cd, deadline)
            except _Timeout:
                return _invalid(sk, [MSG_TIMEOUT], reoriented)
        else:
            x = x_start
            errors.append(MSG_UNSOLVED)

    used = [item for item in active if item[0] not in conflicts]
    geo = SketchGeometry(n, cd, x)
    fns_used = [compile_constraint(c, geo) for _, c in used]
    resid = max((max_abs(fn(x)) for fn in fns_used), default=0.0)  # nach der Diagnose neu bestimmen
    rank, redundant = constraint_rank(fns_used, x)
    dof = 2 * n - rank

    status = {k: "ok" for k, _ in active}
    messages: dict[int, str] = {}
    for k in conflicts:
        status[k] = "conflict"
        messages[k] = f"{constraint_label(cons[k], k)} widerspricht den vorherigen Constraints"
        errors.append(messages[k])
    for (k, _), is_redundant in zip(used, redundant):
        if is_redundant:
            status[k] = "redundant"
            messages[k] = f"{constraint_label(cons[k], k)} ist redundant (bereits durch andere Constraints bestimmt)"
    if not errors and resid >= TOL_OK:
        errors.append(MSG_UNSOLVED)

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
