import math
import xml.etree.ElementTree as ET

from blindsight.export import JsonExporter, SvgExporter, build_geometry
from helpers import make_model, pl

SVG = "{http://www.w3.org/2000/svg}"


def test_svg_positions_are_true_to_scale():
    m = make_model(bounds__width=120.0, bounds__height=120.0)
    placements = [pl(40, 50, 1, 0), pl(90, 100, 2, 90)]
    geo = build_geometry(m, placements)
    root = ET.fromstring(SvgExporter().export(geo))
    # size of the drawing in mm
    assert root.get("height") == "120mm"
    assert root.get("viewBox").split()[3] == "120"
    top = next(g for g in root.iter(SVG + "g") if g.get("id") == "top")
    rods = {int(c.get("data-unit")): c for c in top.iter(SVG + "circle") if c.get("class") == "rod"}
    for uid, p in enumerate(placements):
        c = rods[uid]
        assert math.isclose(float(c.get("cx")), p.x, abs_tol=1e-3)
        assert math.isclose(float(c.get("cy")), 120.0 - p.y, abs_tol=1e-3)  # Y mirrored
        assert math.isclose(float(c.get("r")), m.project.rod.diameter / 2, abs_tol=1e-3)


def test_svg_distance_between_rods_matches():
    m = make_model()
    a, b = pl(30, 40, 1, 0), pl(90, 100, 2, 0)
    root = ET.fromstring(SvgExporter().export(build_geometry(m, [a, b])))
    top = next(g for g in root.iter(SVG + "g") if g.get("id") == "top")
    r = [c for c in top.iter(SVG + "circle") if c.get("class") == "rod"]
    d = math.hypot(float(r[0].get("cx")) - float(r[1].get("cx")), float(r[0].get("cy")) - float(r[1].get("cy")))
    assert math.isclose(d, math.hypot(60, 60), abs_tol=1e-3)


def test_svg_housing_polygon_matches_model():
    m = make_model()
    p = pl(60, 60, 1, 30)
    geo = build_geometry(m, [p])
    root = ET.fromstring(SvgExporter().export(geo))
    poly = next(e for e in root.iter(SVG + "polygon") if e.get("class") == "housing")
    pts = [tuple(map(float, s.split(","))) for s in poly.get("points").split()]
    expect = next(x for x in m.unit_parts(0, 60, 60, 1, 30) if x.kind == "housing").prism.fp.pts
    expect = sorted((round(x, 3), round(120 - y, 3)) for x, y in expect)
    assert sorted((round(x, 3), round(y, 3)) for x, y in pts) == expect


def test_svg_has_sheet_per_plane_with_holes():
    m = make_model(stack__n_motor_planes=3)
    geo = build_geometry(m, [pl(60, 60, 3, 0)])
    root = ET.fromstring(SvgExporter().export(geo))
    ids = [g.get("id") for g in root.iter(SVG + "g")]
    assert {"top", "plane-1", "plane-2", "plane-3"} <= set(ids)
    holes = [e for e in root.iter(SVG + "circle") if e.get("class") == "hole"]
    assert len(holes) == 3  # the rod passes through G1, G2 and G3


def test_svg_marks_collisions():
    m = make_model()
    geo = build_geometry(m, [pl(50, 60, 1, 0), pl(53, 60, 1, 0)])
    assert geo["collisions"]
    assert "collision" in SvgExporter().export(geo)


def test_json_export_roundtrip():
    import json

    m = make_model()
    geo = build_geometry(m, [pl(60, 60, 1, 0)])
    assert json.loads(JsonExporter().export(geo))["units"][0]["x"] == 60
