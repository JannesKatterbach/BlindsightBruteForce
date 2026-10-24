import math

from blindsight.layout import Layout
from helpers import make_model, pl


def test_orientation_changes_collision_result():
    """Same rod distance. Motors facing each other collide, motors facing away do not."""
    m = make_model(stack__n_motor_planes=1, clearance=1.0)
    d = 22.0
    lay = Layout(m)
    lay.add(pl(50, 60, 1, 0))  # at 0 degrees the motor points in +y
    results = {}
    for ang in range(0, 360, 15):
        results[ang] = lay.check(pl(50 + d, 60, 1, ang)).ok
    assert any(results.values()) and not all(results.values())


def test_rotation_by_180_moves_motor_to_other_side():
    """A rotation by 180 degrees mirrors the housing position at the rod axis."""
    m = make_model(stack__n_motor_planes=1)
    g0 = m.unit_parts(0, 60, 60, 1, 0)[0].prism.fp
    g180 = m.unit_parts(0, 60, 60, 1, 180)[0].prism.fp
    assert math.isclose(g0.cx - 60, -(g180.cx - 60), abs_tol=1e-9)
    assert math.isclose(g0.cy - 60, -(g180.cy - 60), abs_tol=1e-9)
    # the housing centre is offset by (center_distance, gear_center_y) from the rod (at 0 degrees)
    rx, ry = m.project.motor.rod_local()
    assert math.isclose(g0.cx, 60 - rx, abs_tol=1e-9) and math.isclose(g0.cy, 60 - ry, abs_tol=1e-9)


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
