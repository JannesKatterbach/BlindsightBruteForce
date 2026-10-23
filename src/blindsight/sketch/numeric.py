"""Numerik des Skizzen Solvers in reinem Python (keine Abhaengigkeit).

  * levenberg_marquardt  minimiert die Residuen mit minimaler Bewegung der Punkte
  * constraint_rank      Rang der Jacobi Matrix, daraus Freiheitsgrade und redundante Constraints
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

Vector = list[float]
Matrix = list[list[float]]
Residuals = Callable[[Vector], list[float]]

TOL_SOLVE = 1e-9  # Abbruch, wenn alle harten Residuen kleiner sind
MAX_ITERATIONS = 120
MAX_DAMPING_TRIES = 30  # Versuche je Iteration, eine Verbesserung durch staerkere Daempfung zu finden
DAMPING_START = 1e-3
DAMPING_MIN = 1e-12
DAMPING_DECREASE = 3.0  # nach erfolgreichem Schritt
DAMPING_INCREASE = 4.0  # nach abgelehntem Schritt
DAMPING_SINGULAR = 10.0  # wenn das Gleichungssystem singulaer ist
REGULARIZATION = 1e-14  # kleiner Zuschlag auf der Diagonalen, haelt das System loesbar
MIN_STEP = 1e-13  # Schritte darunter gelten als Stillstand
COST_ZERO = 1e-26  # Kosten darunter gelten als exakt geloest
PIVOT_MIN = 1e-300  # kleinster Pivot der Gauss Elimination
FD_STEP = 1e-6  # relative Schrittweite der numerischen Ableitung
RANK_ROW_MIN = 1e-9  # Jacobi Zeilen mit kleinerer Norm wirken nicht
RANK_REL_TOL = 1e-6  # relative Restnorm, ab der eine Zeile linear unabhaengig ist


def solve_linear(A: Matrix, b: Vector) -> Optional[Vector]:
    """Loest A x = b mit Gauss Elimination und Spaltenpivotisierung. None bei singulaerem A."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < PIVOT_MIN:
            return None
        M[col], M[pivot] = M[pivot], M[col]
        inv = 1.0 / M[col][col]
        for r in range(col + 1, n):
            factor = M[r][col] * inv
            if factor:
                row, pivot_row = M[r], M[col]
                for k in range(col, n + 1):
                    row[k] -= factor * pivot_row[k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][k] * x[k] for k in range(i + 1, n))) / M[i][i]
    return x


def jacobian(fn: Residuals, x: Vector, m: int) -> Matrix:
    """Jacobi Matrix (m Zeilen) ueber zentrale Differenzen."""
    N = len(x)
    J = [[0.0] * N for _ in range(m)]
    for j in range(N):
        h = FD_STEP * max(1.0, abs(x[j]))
        xp, xm = x[:], x[:]
        xp[j] += h
        xm[j] -= h
        rp, rm = fn(xp), fn(xm)
        for i in range(m):
            J[i][j] = (rp[i] - rm[i]) / (2 * h)
    return J


def max_abs(values: list[float]) -> float:
    return max((abs(v) for v in values), default=0.0)


def levenberg_marquardt(hard: Residuals, soft: Optional[Residuals], x0: Vector, max_iter: int = MAX_ITERATIONS,
                        deadline: Optional[float] = None) -> tuple[Vector, float]:
    """Minimiert |hard|^2 + |soft|^2. hard sind die Constraints, soft optionale Wuensche (Ziehen).

    Jeder Schritt ist die Minimum Norm Loesung dx = -J^T (J J^T + mu I)^-1 r. Sie liegt im Zeilenraum
    von J, nicht eindeutig bestimmte Richtungen bleiben daher unveraendert (minimale Bewegung der
    Punkte) und Rundungsrauschen wird nicht in freie Richtungen verstaerkt.

    Rueckgabe (x, groesster Betrag der harten Residuen)."""
    if soft is None:
        def soft(x: Vector) -> list[float]:
            return []
    has_soft = bool(soft(x0))

    def full(x: Vector) -> list[float]:
        return hard(x) + soft(x)

    N = len(x0)
    n_hard = len(hard(x0))
    x = x0[:]
    r = full(x)
    m = len(r)
    cost = sum(v * v for v in r)
    damping = DAMPING_START
    for _ in range(max_iter):
        if m == 0 or (deadline is not None and time.monotonic() > deadline):
            break
        if not has_soft and max_abs(r[:n_hard]) < TOL_SOLVE:
            break
        J = jacobian(full, x, m)
        JJT = [[sum(J[i][k] * J[j][k] for k in range(N)) for j in range(m)] for i in range(m)]
        scale = max(max(JJT[i][i] for i in range(m)), 1e-12)
        step = _damped_step(J, JJT, r, x, full, cost, damping, scale)
        if step is None:
            break
        x, r, cost, damping, step_length = step
        if step_length < MIN_STEP:
            break
    return x, max_abs(hard(x))


def _damped_step(J: Matrix, JJT: Matrix, r: Vector, x: Vector, full: Residuals, cost: float,
                 damping: float, scale: float):
    """Sucht mit wachsender Daempfung einen Schritt, der die Kosten senkt.

    Rueckgabe (x, r, Kosten, Daempfung, Schrittlaenge) oder None, wenn keiner gefunden wurde."""
    m, N = len(r), len(x)
    for _ in range(MAX_DAMPING_TRIES):
        A = [row[:] for row in JJT]
        for i in range(m):
            A[i][i] += damping * scale + REGULARIZATION
        y = solve_linear(A, r)
        if y is None:
            damping *= DAMPING_SINGULAR
            continue
        dx = [-sum(J[i][k] * y[i] for i in range(m)) for k in range(N)]
        x_new = [x[k] + dx[k] for k in range(N)]
        r_new = full(x_new)
        cost_new = sum(v * v for v in r_new)
        if cost_new < cost or cost_new < COST_ZERO:
            step_length = math.sqrt(sum(d * d for d in dx))
            return x_new, r_new, cost_new, max(damping / DAMPING_DECREASE, DAMPING_MIN), step_length
        damping *= DAMPING_INCREASE
    return None


def constraint_rank(fns: list[Residuals], x: Vector) -> tuple[int, list[bool]]:
    """Rang der gemeinsamen Jacobi Matrix, Constraint fuer Constraint aufgebaut (Gram Schmidt).

    Rueckgabe (Rang, redundant je Constraint). Ein Constraint ist redundant, wenn keine seiner
    Zeilen etwas Neues zur Basis der vorherigen beitraegt."""
    basis: list[Vector] = []
    redundant: list[bool] = []
    for fn in fns:
        J = jacobian(fn, x, len(fn(x)))
        dependent = True
        for row in J:
            row_norm = math.sqrt(sum(v * v for v in row))
            if row_norm < RANK_ROW_MIN:
                continue  # Zeile ist null. Der Constraint wirkt hier nicht, zaehlt als abhaengig
            v = row[:]
            for _ in range(2):  # zweimal orthogonalisieren, numerisch stabiler
                for b in basis:
                    d = sum(v[i] * b[i] for i in range(len(v)))
                    v = [v[i] - d * b[i] for i in range(len(v))]
            rest = math.sqrt(sum(q * q for q in v))
            if rest / row_norm > RANK_REL_TOL:
                basis.append([q / rest for q in v])
                dependent = False
        redundant.append(dependent)
    return len(basis), redundant
