"""Referenztest. Exakte Abstandsberechnung gegen dichte Stichprobe der Konturen."""

import math
import random

from blindsight.geometry import Footprint, Prism, footprint_distance, point_in_convex, prism_distance


def sample_boundary(fp: Footprint, n_per_edge=60):
    if fp.kind == "c":
        return [(fp.cx + fp.r * math.cos(2 * math.pi * i / 720), fp.cy + fp.r * math.sin(2 * math.pi * i / 720)) for i in range(720)]
    pts = []
    k = len(fp.pts)
    for i in range(k):
        (x1, y1), (x2, y2) = fp.pts[i], fp.pts[(i + 1) % k]
        for t in range(n_per_edge):
            f = t / n_per_edge
            pts.append((x1 + (x2 - x1) * f, y1 + (y2 - y1) * f))
    return pts


def inside(fp: Footprint, x, y):
    if fp.kind == "c":
        return math.hypot(x - fp.cx, y - fp.cy) <= fp.r
    return point_in_convex(x, y, fp.pts)


def random_fp(rng):
    if rng.random() < 0.3:
        return Footprint.circle(rng.uniform(0, 40), rng.uniform(0, 40), rng.uniform(1, 8))
    return Footprint.rect(rng.uniform(0, 40), rng.uniform(0, 40), rng.uniform(2, 15), rng.uniform(2, 15), rng.uniform(0, math.pi))


def test_distance_matches_sampling():
    rng = random.Random(7)
    for _ in range(250):
        a, b = random_fp(rng), random_fp(rng)
        d = footprint_distance(a, b)
        sa, sb = sample_boundary(a), sample_boundary(b)
        overlap = any(inside(b, x, y) for x, y in sa) or any(inside(a, x, y) for x, y in sb)
        if overlap:
            assert d == 0.0
            continue
        ref = min(math.hypot(p[0] - q[0], p[1] - q[1]) for p in sa for q in sb)
        assert d <= ref + 1e-9
        assert ref - d < 0.35, (d, ref)  # Stichprobenfehler


def test_distance_symmetric_and_nonnegative():
    rng = random.Random(3)
    for _ in range(200):
        a, b = random_fp(rng), random_fp(rng)
        assert footprint_distance(a, b) >= 0
        assert math.isclose(footprint_distance(a, b), footprint_distance(b, a), abs_tol=1e-9)


def test_touching_and_contained():
    a = Footprint.rect(0, 0, 10, 10)
    assert footprint_distance(a, Footprint.rect(10, 0, 10, 10)) == 0.0  # beruehren sich
    assert footprint_distance(a, Footprint.rect(0, 0, 2, 2)) == 0.0  # enthalten
    assert footprint_distance(a, Footprint.circle(0, 0, 1)) == 0.0
    assert math.isclose(footprint_distance(a, Footprint.rect(10.0 + 1e-6, 0, 10, 10)), 1e-6, rel_tol=1e-3)


def test_parallel_edges():
    a, b = Footprint.rect(0, 0, 10, 10), Footprint.rect(0, 13, 10, 10)
    assert math.isclose(footprint_distance(a, b), 3.0)


def test_prism_cutoff_is_lower_bound():
    rng = random.Random(5)
    for _ in range(200):
        a = Prism(random_fp(rng), 0, rng.uniform(1, 10))
        b = Prism(random_fp(rng), rng.uniform(-5, 15), rng.uniform(16, 30))
        exact = prism_distance(a, b)
        cut = prism_distance(a, b, cutoff=2.0)
        if exact >= 2.0:
            assert cut >= 2.0 - 1e-9
        else:
            assert math.isclose(cut, exact, abs_tol=1e-9)
