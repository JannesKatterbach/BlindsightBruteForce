"""Regressionstests fuer Fehler, die bei der Ueberarbeitung (Version 0.4.0) gefunden wurden."""

import math

import pytest

from blindsight.config import ConfigError, Project
from blindsight.diagnose import single_unit_report
from blindsight.layout import Placement, layout_signature
from blindsight.model import Model, PlaneStack
from blindsight.patterns import estimated_point_count, pattern_points


def _nearest_neighbor_distances(points):
    out = []
    for i, (x, y) in enumerate(points):
        out.append(min(math.hypot(x - u, y - v) for j, (u, v) in enumerate(points) if j != i))
    return out


@pytest.mark.parametrize("kind", ["hex_x", "hex_y"])
def test_hex_lattice_neighbors_have_pitch_distance(kind):
    # Frueher wurde jede Reihe einzeln zentriert. Nachbarn lagen dann nur 0.9 x Teilung auseinander
    pts = pattern_points(kind, 10.0, (0.0, 0.0, 95.0, 87.0))
    assert len(pts) > 20
    for dist in _nearest_neighbor_distances(pts):
        assert dist == pytest.approx(10.0, abs=1e-9)


def test_estimated_point_count_is_close():
    region = (0.0, 0.0, 200.0, 150.0)
    for kind in ("square", "hex_x", "hex_y"):
        real = len(pattern_points(kind, 7.0, region))
        assert 0.8 * real <= estimated_point_count(kind, 7.0, region) <= 1.25 * real


def test_unknown_pattern_is_rejected():
    with pytest.raises(ValueError):
        pattern_points("triangle", 5.0, (0.0, 0.0, 10.0, 10.0))


@pytest.mark.parametrize("value", ["no", 0, 1, None])
def test_bool_fields_are_type_checked(value):
    # Frueher galt "enabled": "no" als aktiv
    data = Project().to_dict()
    data["motor"]["sketch"] = {
        "points": [[-20, -10], [-2, -10], [-2, 10], [-20, 10]],
        "constraints": [{"type": "length", "a": 0, "value": 18.0, "enabled": value}],
    }
    with pytest.raises(ConfigError) as exc:
        Project.from_dict(data)
    assert any("true oder false" in e for e in exc.value.errors)


def test_overlapping_planes_fail_validation():
    p = Project()
    p.stack.mode = "distances"
    p.stack.distances = [10.0, 11.0, 30.0]  # G1 und G2 liegen naeher als die Plattendicke
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("ueberlappen" in e for e in exc.value.errors)


def test_unknown_stack_mode_is_reported():
    p = Project()
    p.stack.mode = "spiral"
    with pytest.raises(ConfigError):
        p.validate()
    with pytest.raises(ConfigError):
        p.stack.plane_tops()


def test_free_height_above_g0_is_infinite():
    stack = PlaneStack(Project())
    assert stack.free_height_above(0) == math.inf
    assert stack.free_height_above(1) > 0


def test_center_distance_min_without_max_is_an_error():
    p = Project()
    p.motor.center_distance_min = 4.0
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("zusammen" in e for e in exc.value.errors)


def test_nominal_center_distance_outside_range_is_an_error():
    p = Project()
    p.motor.center_distance = 5.0
    p.motor.center_distance_min = 6.0
    p.motor.center_distance_max = 8.0
    p.motor.center_distance_steps = 3
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("ausserhalb des Bereichs" in e for e in exc.value.errors)


def test_angle_list_has_no_duplicate_zero_and_360():
    p = Project()
    p.search.allowed_angles = [0.0, 90.0, 360.0, -90.0, 270.0]
    assert p.allowed_angle_list() == [0.0, 90.0, 270.0]
    p.search.allowed_angles = None
    p.search.angle_min, p.search.angle_max, p.search.angle_step = 0.0, 360.0, 90.0
    assert p.allowed_angle_list() == [0.0, 90.0, 180.0, 270.0]


def test_diagnose_probes_the_whole_center_distance_range():
    # Nur der nominale Achsabstand scheitert. Frueher meldete die Diagnose "keine Einzeleinheit moeglich"
    p = Project()
    p.motor.own_clearance = 6.0
    p.motor.center_distance = 5.0
    p.motor.center_distance_min = 5.0
    p.motor.center_distance_max = 15.0
    p.motor.center_distance_steps = 3
    model = Model(p)
    assert model.cd_problem(5.0)
    assert not model.cd_problem(15.0)
    assert single_unit_report(model) == []


def test_placement_rejects_negative_center_distance():
    with pytest.raises(ValueError):
        Placement.from_dict({"x": 1, "y": 2, "plane": 1, "angle": 0, "cd": -1}, 3)
    assert Placement.from_dict({"x": 1, "y": 2, "plane": 1, "angle": 0, "cd": None}, 3).cd is None


def test_layout_signature_distinguishes_center_distance():
    a = [Placement(1.0, 2.0, 1, 0.0, 5.0)]
    b = [Placement(1.0, 2.0, 1, 0.0, 6.0)]
    assert layout_signature(a) != layout_signature(b)
    assert layout_signature(a + b) == layout_signature(b + a)


def test_model_unit_bbox_matches_parts():
    model = Model(Project())
    parts = model.unit_parts(0, 50.0, 40.0, 1, 30.0)
    xs = [x for p in parts for x, _ in p.prism.fp.outline()]
    box = model.unit_bbox(50.0, 40.0, 1, 30.0)
    assert box[0] == pytest.approx(min(xs), abs=0.05)
    assert box[2] == pytest.approx(max(xs), abs=0.05)
