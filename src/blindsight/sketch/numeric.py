"""Numerics of the sketch solver in pure Python (no dependency).

  * levenberg_marquardt  minimises the residuals with minimal movement of the points
  * constraint_rank      rank of the Jacobian, giving degrees of freedom and redundant constraints
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

Vector = list[float]
Matrix = list[list[float]]
Residuals = Callable[[Vector], list[float]]

TOL_SOLVE = 1e-9  # stop when all hard residuals are smaller
MAX_ITERATIONS = 120
MAX_DAMPING_TRIES = 30  # attempts per iteration to find an improvement with stronger damping
DAMPING_START = 1e-3
DAMPING_MIN = 1e-12
DAMPING_DECREASE = 3.0  # after a successful step
DAMPING_INCREASE = 4.0  # after a rejected step
DAMPING_SINGULAR = 10.0  # when the system of equations is singular
REGULARIZATION = 1e-14  # small allowance on the diagonal, keeps the system solvable
MIN_STEP = 1e-13  # smaller steps count as standstill
COST_ZERO = 1e-26  # smaller costs count as exactly solved
PIVOT_MIN = 1e-300  # smallest pivot of the Gaussian elimination
FD_STEP = 1e-6  # relative step size of the numerical derivative
RANK_ROW_MIN = 1e-9  # Jacobian rows with a smaller norm have no effect
RANK_REL_TOL = 1e-6  # relative residual norm from which a row is linearly independent
DETERMINED_TOL = 1e-6  # tolerance of determined_variables


def solve_linear(A: Matrix, b: Vector) -> Optional[Vector]:
    """Solve A x = b with Gaussian elimination and column pivoting. None for a singular A."""
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
    """Jacobian (m rows) by central differences."""
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
    """Minimise |hard|^2 + |soft|^2. hard are the constraints, soft optional wishes (dragging).

    Every step is the minimum norm solution dx = -J^T (J J^T + mu I)^-1 r. It lies in the row space of
    J, so directions that are not uniquely determined stay unchanged (minimal movement of the points)
    and rounding noise is not amplified into free directions.

    Returns (x, largest absolute value of the hard residuals)."""
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
    """Search a step that lowers the cost with growing damping.

    Returns (x, r, cost, damping, step length) or None if none was found."""
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
    """Rank of the joint Jacobian, built constraint by constraint (Gram Schmidt).

    Returns (rank, redundant per constraint). A constraint is redundant if none of its rows adds
    anything new to the basis of the previous ones."""
    basis, redundant = row_space(fns, x)
    return len(basis), redundant


def determined_variables(basis: list[Vector], n: int) -> list[bool]:
    """True for every unknown that the constraints fix completely.

    An unknown j is fixed if the unit vector e_j lies in the row space of the Jacobian, that is if the
    squared components of the orthonormal basis vectors at j add up to 1."""
    return [sum(b[j] * b[j] for b in basis) > 1.0 - DETERMINED_TOL for j in range(n)]


def row_space(fns: list[Residuals], x: Vector) -> tuple[list[Vector], list[bool]]:
    """Orthonormal basis of the row space of the joint Jacobian and redundant per constraint."""
    basis: list[Vector] = []
    redundant: list[bool] = []
    for fn in fns:
        J = jacobian(fn, x, len(fn(x)))
        dependent = True
        for row in J:
            row_norm = math.sqrt(sum(v * v for v in row))
            if row_norm < RANK_ROW_MIN:
                continue  # the row is zero. The constraint has no effect here and counts as dependent
            v = row[:]
            for _ in range(2):  # orthogonalise twice, numerically more stable
                for b in basis:
                    d = sum(v[i] * b[i] for i in range(len(v)))
                    v = [v[i] - d * b[i] for i in range(len(v))]
            rest = math.sqrt(sum(q * q for q in v))
            if rest / row_norm > RANK_REL_TOL:
                basis.append([q / rest for q in v])
                dependent = False
        redundant.append(dependent)
    return basis, redundant
