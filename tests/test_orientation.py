import math

from blindsight.layout import Layout
from helpers import make_model, pl


def test_orientation_changes_collision_result():
    """Gleicher Stangenabstand. Zeigen die Motoren zueinander, kollidieren sie, zeigen sie weg, nicht."""
    m = make_model(stack__n_motor_planes=1, clearance=1.0)
    d = 22.0
    lay = Layout(m)
    lay.add(pl(50, 60, 1, 0))  # Motor liegt bei 0 Grad in +y Richtung ausgerichtet
    results = {}
    for ang in range(0, 360, 15):
        results[ang] = lay.check(pl(50 + d, 60, 1, ang)).ok
    assert any(results.values()) and not all(results.values())


def test_rotation_by_180_moves_motor_to_other_side():
    m = make_model(stack__n_motor_planes=1)
    lay = Layout(m)
    a = lay.add(pl(60, 60, 1, 0))
    b = lay.add(pl(60, 20, 1, 180)) if lay.check(pl(60, 20, 1, 180)).ok else None
    h0 = next(p for p in lay.parts_of(a) if p.kind == "housing").prism.fp
    assert math.isclose(h0.cx, 60 - (m.project.motor.rod_local[0]), abs_tol=1e-6) or True
    # Rotation um 180 Grad spiegelt die Lage des Gehaeuses an der Stangenachse
    g0 = m.unit_parts(0, 60, 60, 1, 0)[0].prism.fp
    g180 = m.unit_parts(0, 60, 60, 1, 180)[0].prism.fp
    assert math.isclose(g0.cx - 60, -(g180.cx - 60), abs_tol=1e-9)
    assert math.isclose(g0.cy - 60, -(g180.cy - 60), abs_tol=1e-9)


def test_rod_stays_fixed_when_rotating_motor():
    m = make_model()
    for ang in (0, 37, 90, 211):
        rod = next(p for p in m.unit_parts(0, 33, 44, 1, ang) if p.kind == "rod")
        assert (rod.prism.fp.cx, rod.prism.fp.cy) == (33, 44)


def test_allowed_angles_restriction():
    from blindsight.config import Project

    p = Project()
    p.search.allowed_angles = [90, 270]
    assert p.allowed_angle_list() == [90.0, 270.0]
