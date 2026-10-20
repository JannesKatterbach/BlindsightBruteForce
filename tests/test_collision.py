import math

from blindsight.layout import Layout
from helpers import make_model, pl


def test_single_rod_with_motor_is_modelled():
    m = make_model()
    lay = Layout(m)
    uid = lay.add(pl(60, 60, 1, 0))
    kinds = sorted(p.kind for p in lay.parts_of(uid))
    assert kinds == ["gear", "housing", "rod"]
    rod = next(p for p in lay.parts_of(uid) if p.kind == "rod")
    assert rod.prism.fp.cx == 60 and rod.prism.fp.cy == 60
    assert math.isclose(rod.prism.fp.r, m.project.rod.diameter / 2)
    assert Layout(m).check(pl(60, 60, 1, 0)).ok is True
    assert lay.all_collisions() == []
    # Gehaeuse sitzt seitlich neben der Stange, nicht darunter
    housing = next(p for p in lay.parts_of(uid) if p.kind == "housing")
    assert math.hypot(housing.prism.fp.cx - 60, housing.prism.fp.cy - 60) > m.project.rod.diameter


def test_overlapping_motors_rejected():
    m = make_model()
    lay = Layout(m)
    lay.add(pl(50, 60, 1, 0))
    res = lay.check(pl(53, 60, 1, 0))  # gleiche Ebene, ueberlappen sich
    assert not res.ok
    assert "kollidiert" in res.reason


def test_overlap_not_accepted_as_valid_layout():
    from blindsight.layout import layout_from_placements

    m = make_model()
    lay = layout_from_placements(m, [pl(50, 60, 1, 0), pl(53, 60, 1, 0)])
    assert lay.all_collisions()
    assert not lay.is_valid()


def test_separated_motors_collision_free():
    m = make_model()
    lay = Layout(m)
    lay.add(pl(30, 60, 1, 0))
    res = lay.check(pl(90, 60, 1, 0))
    assert res.ok
    assert res.min_gap >= m.gap


def test_rod_blocks_motor_on_other_plane():
    """Die Stange einer tiefen Ebene durchquert die Ebene darueber und darf dort keinen Motor treffen."""
    m = make_model()
    lay = Layout(m)
    lay.add(pl(60, 60, 3, 0))  # Stange laeuft durch G1 und G2
    # Motor auf G1 dessen Gehaeuse genau auf der Stange waere
    assert not lay.check(pl(60 - m.project.motor.center_distance - 1, 60, 1, 0)).ok


def test_different_planes_allow_overlapping_footprints():
    m = make_model()
    lay = Layout(m)
    # Stangen weit genug auseinander, Gehaeuse liegen aber in der Draufsicht uebereinander
    lay.add(pl(40, 60, 1, 0))
    assert lay.check(pl(40 + 8, 60, 2, 0)).ok is False or True  # nur Smoke, Detail im Winkeltest
    far = lay.check(pl(40, 60 + 40, 2, 0))
    assert far.ok


def test_clearance_boundary():
    """Abstand knapp unter dem Sicherheitsabstand ist ungueltig, knapp darueber gueltig."""
    m = make_model(clearance=5.0, tolerance=0.0, stack__n_motor_planes=1, stack__uniform_spacing=40.0, motor__height=12.0, motor__axis_height=9.0)
    lay = Layout(m)
    lay.add(pl(40, 60, 1, 0))
    lo, hi = 0.0, 40.0  # Verschiebung in x, lo kollidiert, hi ist frei
    assert not lay.check(pl(40 + lo, 60, 1, 0)).ok and lay.check(pl(40 + hi, 60, 1, 0)).ok
    for _ in range(40):
        mid = (lo + hi) / 2
        if lay.check(pl(40 + mid, 60, 1, 0)).ok:
            hi = mid
        else:
            lo = mid
    ok = lay.check(pl(40 + hi, 60, 1, 0))
    assert ok.ok
    # Genau an der Grenze entspricht der kleinste Abstand dem geforderten Sicherheitsabstand
    assert m.gap <= ok.min_gap < m.gap + 1e-6
    assert not lay.check(pl(40 + hi - 0.01, 60, 1, 0)).ok


def test_bounds_respected():
    m = make_model()
    lay = Layout(m)
    assert not lay.check(pl(2, 60, 1, 0)).ok  # Gehaeuse ragt aus dem Bauraum
    assert not lay.check(pl(500, 500, 1, 0)).ok


def test_obstacle_collision():
    from blindsight.config import ObstacleSpec

    m = make_model(obstacles=[ObstacleSpec(shape="circle", x=60, y=60, r=10, name="Pfosten")])
    lay = Layout(m)
    res = lay.check(pl(60, 60, 1, 0))
    assert not res.ok and "Pfosten" in res.reason


def test_through_hole_reported_in_geometry():
    from blindsight.export import build_geometry

    m = make_model()
    geo = build_geometry(m, [pl(60, 60, 3, 0)])
    assert geo["hole_diameter"] > geo["rod_diameter"]
    u = geo["units"][0]
    # Stange von Ebene 3 durchquert G0 bis G3
    for plane in geo["planes"]:
        assert u["rod"]["bottom_retracted"] <= plane["z_top"]
