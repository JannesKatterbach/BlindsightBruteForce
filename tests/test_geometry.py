import math

from blindsight.geometry import Footprint, Prism, footprint_distance, prism_distance
from blindsight.units import from_mm, to_mm


def test_units_roundtrip():
    assert to_mm(2, "cm") == 20
    assert math.isclose(to_mm(1, "in"), 25.4)
    assert math.isclose(from_mm(25.4, "in"), 1.0)


def test_circle_circle_distance():
    a, b = Footprint.circle(0, 0, 2), Footprint.circle(10, 0, 3)
    assert math.isclose(footprint_distance(a, b), 5.0)


def test_rect_rect_distance_and_overlap():
    a = Footprint.rect(0, 0, 10, 10)
    assert math.isclose(footprint_distance(a, Footprint.rect(15, 0, 10, 10)), 5.0)
    assert footprint_distance(a, Footprint.rect(5, 0, 10, 10)) == 0.0


def test_rotated_rect_distance():
    a = Footprint.rect(0, 0, 10, 2)
    b = Footprint.rect(0, 10, 10, 2, math.pi / 2)  # steht hochkant, Unterkante bei y = 5
    assert math.isclose(footprint_distance(a, b), 4.0)


def test_circle_polygon_corner():
    sq = Footprint.rect(0, 0, 10, 10)
    c = Footprint.circle(8, 8, 1)
    assert math.isclose(footprint_distance(sq, c), math.hypot(3, 3) - 1)


def test_prism_distance_uses_z():
    a = Prism(Footprint.rect(0, 0, 10, 10), 0, 5)
    b = Prism(Footprint.rect(0, 0, 10, 10), 8, 12)
    assert math.isclose(prism_distance(a, b), 3.0)
    c = Prism(Footprint.rect(13, 0, 10, 10), 8, 12)
    assert math.isclose(prism_distance(a, c), math.hypot(3, 3))
