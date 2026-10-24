import math

import pytest
from helpers import make_model


@pytest.mark.parametrize("mode_kw", [
    dict(),
    dict(stack__mode="gaps", stack__gaps=[10, 30, 17]),
    dict(stack__mode="distances", stack__distances=[12, 40, 95]),
])
def test_every_rod_reaches_full_stroke_above_g0(mode_kw):
    """Independent of the motor layer the tip at full stroke must lie exactly stroke above G0 and the thread
    below the gear axis must still engage."""
    m = make_model(stack__n_motor_planes=3, **mode_kw)
    for plane in m.stack.motor_planes:
        g = m.rod_geometry(plane.index)
        assert math.isclose(g.tip_extended, m.project.rod.stroke)
        assert g.engage_below_actual >= m.project.rod.engage_below + m.project.rod.length_tolerance - 1e-9
        assert g.bottom_extended < g.z_axis
        assert math.isclose(g.length, g.tip_extended - g.bottom_extended)


def test_deeper_plane_needs_longer_rod():
    m = make_model(stack__n_motor_planes=3)
    lengths = [m.rod_geometry(i).length for i in (1, 2, 3)]
    assert lengths[0] < lengths[1] < lengths[2]
    # the difference equals the layer distance exactly
    assert math.isclose(lengths[1] - lengths[0], m.project.stack.uniform_spacing)


def test_rod_length_formula_components():
    m = make_model(stack__n_motor_planes=1)
    g = m.rod_geometry(1)
    r = m.project.rod
    expected = r.stroke + (0 - g.z_axis) + r.engage_below + r.length_tolerance
    assert math.isclose(g.length, expected)
    assert g.length_above_g0 == r.stroke
    assert g.length_below_mount > 0


def test_retracted_tip_not_above_g0():
    m = make_model()
    g = m.rod_geometry(1)
    assert g.tip_retracted <= 0.0
