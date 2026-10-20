"""Eigenschaftstests mit Zufallskonfigurationen. Jede Ausgabe muss geometrisch gueltig sein."""

import math
import random

import pytest
from blindsight.config import ConfigError, Project
from blindsight.layout import Layout, Placement, layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import run_optimizer


def random_project(rng: random.Random) -> Project:
    p = Project()
    p.target_count = rng.randint(1, 14)
    p.clearance = rng.choice([0.2, 1.0, 2.5])
    p.rod.diameter = rng.choice([3.0, 4.0, 6.0])
    p.rod.stroke = rng.choice([20.0, 50.0])
    p.motor.width = rng.uniform(6, 16)
    p.motor.depth = rng.uniform(10, 26)
    p.motor.height = rng.uniform(6, 12)
    p.motor.axis_height = rng.uniform(2, p.motor.height - 1)
    p.motor.gear_diameter = rng.uniform(3, 8)
    p.motor.gear_width = rng.uniform(2, 6)
    p.motor.center_distance = rng.uniform(3, 8)
    p.motor.mount = rng.choice(["top", "bottom"])
    p.stack.n_motor_planes = rng.randint(1, 5)
    if rng.random() < 0.5:
        p.stack.mode = "gaps"
        p.stack.gaps = [rng.uniform(14, 35) for _ in range(p.stack.n_motor_planes)]
    else:
        p.stack.uniform_spacing = rng.uniform(14, 35)
    s = rng.choice([70, 100, 140])
    p.bounds.xmax = p.bounds.ymax = float(s)
    p.search.time_limit_s = 0.6
    p.search.angle_step = rng.choice([15.0, 30.0, 45.0])
    p.search.seed = rng.randint(0, 1000)
    p.search.optimizer = rng.choice(["pattern_greedy", "anneal_free"])
    p.search.layout_goal = rng.choice(["compact", "spread"])
    p.search.stagnation_s = None
    return p


def test_random_projects_always_yield_valid_layouts():
    rng = random.Random(2024)
    for i in range(14):
        p = random_project(rng)
        try:
            model = Model(p)
        except ConfigError:
            continue
        res = run_optimizer(model)
        for sol in res.solutions:
            lay = layout_from_placements(model, sol.placements)
            assert lay.all_collisions() == [], (i, p.to_json())
            assert len(sol.placements) <= p.target_count
        if not res.solutions:
            assert res.messages, "ohne Loesung muss es eine Erklaerung geben"


def test_incremental_check_matches_full_check():
    """Jede per check akzeptierte Platzierung muss auch die vollstaendige Pruefung bestehen."""
    rng = random.Random(11)
    for _ in range(8):
        p = random_project(rng)
        try:
            model = Model(p)
        except ConfigError:
            continue
        usable = model.usable_planes()
        if not usable:
            continue
        lay = Layout(model)
        b = p.bounds
        for _ in range(400):
            plane = rng.choice(usable)
            pl = Placement(rng.uniform(b.xmin, b.xmax), rng.uniform(b.ymin, b.ymax), plane, rng.choice(model.angles_for(plane)))
            lay.try_add(pl)
        assert lay.all_collisions() == []
        # Umgekehrt. Eine abgelehnte Platzierung erzeugt in der Vollpruefung mindestens eine Kollision
        for _ in range(60):
            plane = rng.choice(usable)
            pl = Placement(rng.uniform(b.xmin, b.xmax), rng.uniform(b.ymin, b.ymax), plane, rng.choice(model.angles_for(plane)))
            ok = lay.check(pl).ok
            test = lay.copy()
            test.add(pl)
            assert ok == (test.all_collisions() == [])


def test_remove_and_readd_restores_state():
    model = Model(Project())
    lay = Layout(model)
    ids = [lay.add(Placement(30 + 30 * i, 60, 1 + i % 3, 0.0)) for i in range(3)]
    before = lay.all_collisions()
    pl = lay.remove(ids[1])
    assert len(lay) == 2
    lay.add(pl)
    assert lay.all_collisions() == before


def test_order_independence_of_validity():
    model = Model(Project())
    pls = [Placement(30, 60, 1, 0), Placement(90, 60, 2, 90), Placement(60, 100, 3, 180)]
    a = layout_from_placements(model, pls).all_collisions()
    b = layout_from_placements(model, list(reversed(pls))).all_collisions()
    assert (a == []) == (b == [])


def _surface_samples(prism):
    from test_reference_distance import sample_boundary

    pts = sample_boundary(prism.fp, 25)
    zs = [prism.z0, (prism.z0 + prism.z1) / 2, prism.z1]
    n = 4 if prism.z1 - prism.z0 > 20 else 1  # lange Stangen dichter in z abtasten
    zs = [prism.z0 + (prism.z1 - prism.z0) * i / (2 * n) for i in range(2 * n + 1)]
    return [(x, y, z) for x, y in pts for z in zs]


def test_valid_layouts_pass_independent_sampling_check():
    """Unabhaengige Gegenprobe. Die abgetasteten Oberflaechenpunkte verschiedener Einheiten
    duerfen nie naeher als der Sicherheitsabstand liegen (sonst waere die Pruefung zu lax)."""
    rng = random.Random(99)
    checked = 0
    for _ in range(4):
        p = random_project(rng)
        p.search.optimizer = "pattern_greedy"
        p.search.time_limit_s = 0.5
        try:
            model = Model(p)
        except ConfigError:
            continue
        res = run_optimizer(model)
        if not res.best or len(res.best.placements) < 2:
            continue
        lay = layout_from_placements(model, res.best.placements)
        ids = sorted(lay.units)
        samples = {u: [s for part in lay.parts_of(u) for s in _surface_samples(part.prism)] for u in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if math.hypot(lay.units[a].x - lay.units[b].x, lay.units[a].y - lay.units[b].y) > 2 * model.unit_radius + model.gap:
                    continue
                d = min(math.dist(s, t) for s in samples[a][::7] for t in samples[b][::7])
                assert d >= model.gap - 1e-6, (a, b, d, model.gap)
                checked += 1
    assert checked > 0
