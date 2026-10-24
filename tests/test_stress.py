"""Belastungs und Grenzfalltests. Keine Abstuerze, alle Ergebnisse gueltig."""

import time

import pytest
from blindsight.config import ConfigError, Project
from blindsight.layout import layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import run_optimizer


def solve(**kw):
    p = Project()
    for k, v in kw.items():
        o = p
        ks = k.split("__")
        for a in ks[:-1]:
            o = getattr(o, a)
        setattr(o, ks[-1], v)
    m = Model(p)
    return m, run_optimizer(m)


def test_many_rods_many_planes():
    m, r = solve(target_count=80, stack__n_motor_planes=8, bounds__width=250.0, bounds__height=250.0, search__time_limit_s=5.0)
    assert len(r.best.placements) == 80
    assert layout_from_placements(m, r.best.placements).is_valid()


def test_25_planes():
    m, r = solve(target_count=30, stack__n_motor_planes=25, bounds__width=160.0, bounds__height=160.0, search__time_limit_s=4.0)
    assert r.best and layout_from_placements(m, r.best.placements).is_valid()


def test_huge_bounds_do_not_explode():
    t = time.time()
    m, r = solve(target_count=5, bounds__width=100000.0, bounds__height=100000.0, search__time_limit_s=4.0)
    assert len(r.best.placements) == 5
    assert time.time() - t < 20


def test_tiny_angle_step_is_bounded():
    with pytest.raises(ConfigError):
        Project.from_dict({"search": {"angle_step": 1e-9}})


def test_single_rod_target():
    m, r = solve(target_count=1, search__time_limit_s=2.0)
    assert len(r.best.placements) == 1


def test_coordinates_start_at_the_bottom_left_origin():
    m, r = solve(target_count=4, bounds__width=100.0, bounds__height=100.0, search__time_limit_s=3.0)
    assert len(r.best.placements) == 4
    assert all(0 <= p.x <= 100 and 0 <= p.y <= 100 for p in r.best.placements)


def test_infeasible_tiny_motor_reports_reason():
    m, r = solve(target_count=3, motor__width=1.0, motor__depth=2.0, motor__height=3.0, motor__axis_height=2.0,
                 motor__gear_diameter=0.5, motor__gear_width=0.5, motor__center_distance=0.5, search__time_limit_s=2.0)
    assert r.status == "infeasible" and any("eigene Stange" in s for s in r.messages)


def test_zero_clearance_still_strictly_valid():
    m, r = solve(target_count=6, clearance=0.0, tolerance=0.0, search__time_limit_s=3.0)
    assert layout_from_placements(m, r.best.placements).is_valid()


def test_target_larger_than_possible_gives_partial_with_message():
    m, r = solve(target_count=500, bounds__width=50.0, bounds__height=50.0, search__time_limit_s=2.0)
    n = len(r.best.placements)
    assert 0 < n < 500 and any("von 500" in s for s in r.messages)
