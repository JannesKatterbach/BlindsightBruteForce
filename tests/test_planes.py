import math

import pytest
from blindsight.config import ConfigError
from helpers import make_model


def test_uniform_spacing():
    m = make_model(stack__n_motor_planes=4, stack__uniform_spacing=15)
    assert [p.z_top for p in m.stack.planes] == [0, -15, -30, -45, -60]


def test_individual_gaps():
    m = make_model(stack__n_motor_planes=3, stack__mode="gaps", stack__gaps=[10, 25, 12])
    assert [p.z_top for p in m.stack.planes] == [0, -10, -35, -47]


def test_distances_to_g0():
    m = make_model(stack__n_motor_planes=3, stack__mode="distances", stack__distances=[10, 35, 47])
    assert [p.z_top for p in m.stack.planes] == [0, -10, -35, -47]


def test_no_hardcoded_plane_limit():
    m = make_model(stack__n_motor_planes=25, stack__uniform_spacing=15)
    assert len(m.stack.motor_planes) == 25
    assert math.isclose(m.stack.planes[25].z_top, -375)


def test_overlapping_planes_rejected():
    with pytest.raises(ConfigError):
        make_model(stack__mode="gaps", stack__gaps=[3, 20, 20], stack__g0_thickness=6.0)


def test_invalid_config_collects_errors():
    with pytest.raises(ConfigError) as e:
        make_model(rod__diameter=-1, stack__n_motor_planes=0)
    assert len(e.value.errors) >= 2


def test_tall_motor_flags_plane():
    m = make_model(motor__height=40, motor__axis_height=20, stack__uniform_spacing=20)
    assert not m.usable_planes()
    assert any("passt nicht" in s for s in m.plane_problems(1))


def test_bottom_mount_uses_space_below():
    m = make_model(motor__mount="bottom")
    g = m.rod_geometry(1)
    assert g.z_mount < m.stack[1].z_top  # haengt unter der Ebene (Unterseite)
    assert g.z_axis < g.z_mount
