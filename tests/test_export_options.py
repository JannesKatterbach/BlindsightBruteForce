"""Export menu. Choice of one layer and of the parts of a drawing, presets (KiCad Edge.Cuts) and the endpoints."""

import json
import time
import xml.etree.ElementTree as ET
from collections import Counter

import pytest
from blindsight.config import Project
from blindsight.export import EXPORT_PRESETS, EXPORTERS, build_geometry, export_filename, export_menu_schema, export_options
from blindsight.export.base import CONTENTS, obstacles_of_layer
from blindsight.i18n import LANGUAGES, tr, use_language
from blindsight.layout import Placement
from blindsight.model import Model
from blindsight.web.server import App
from helpers import make_model, pl

SVG = "{http://www.w3.org/2000/svg}"


def geometry(**overrides):
    # Three motor layers. Unit 0 on G3 (its rod passes G0 to G3), unit 1 on G1
    m = make_model(stack__n_motor_planes=3, **overrides)
    return build_geometry(m, [pl(60, 60, 3, 0), pl(30, 40, 1, 90)])


def dxf_entities(text):
    """(entity type, DXF layer) of the ENTITIES section."""
    lines = text.split("\n")
    start = lines.index("ENTITIES")
    out = []
    for i in range(start, len(lines) - 3):
        if lines[i] == "0" and lines[i + 1] in ("POLYLINE", "CIRCLE", "TEXT") and lines[i + 2] == "8":
            out.append((lines[i + 1], lines[i + 3]))
    return Counter(out)


def dxf(geo, layer=None, contents=None):
    exporter = EXPORTERS["dxf"]
    return exporter().export(geo, export_options(exporter, layer, contents, geo))


# -- Choice of layer and contents ------------------------------------------------------------
def test_kicad_edge_cuts_has_only_board_outline_and_holes_of_g0():
    geo = geometry()
    preset = next(p for p in EXPORT_PRESETS if p["name"] == "kicad_edge")
    text = dxf(geo, preset["layer"], preset["contents"])
    assert dxf_entities(text) == Counter({("POLYLINE", "BOUNDS"): 1, ("CIRCLE", "G0_HOLES"): 2})
    assert "$INSUNITS\n70\n4" in text  # millimetres for the import
    assert "TOP_RODS" not in text and "MOTOR" not in text


def test_dxf_of_one_motor_layer_has_only_its_motors_and_holes():
    ents = dxf_entities(dxf(geometry(), 1, ["holes", "rods", "housings", "gears"]))
    assert ents[("POLYLINE", "G1_MOTOR")] == 1 and ents[("POLYLINE", "G1_GEAR")] == 1
    assert not any("G3" in layer or "G0" in layer for _, layer in ents)
    assert ents[("CIRCLE", "G1_HOLES")] == 2 and ents[("CIRCLE", "G1_RODS")] == 2  # both rods pass G1


def test_dxf_default_is_unchanged_and_margins_on_request():
    geo = geometry(bounds__edge_margin=3.0, bounds__border=True, bounds__border_width=8.0)
    ents = dxf_entities(dxf(geo))
    assert ents[("CIRCLE", "TOP_RODS")] == 2 and ents[("POLYLINE", "G3_MOTOR")] == 1
    assert ents[("CIRCLE", "G2_HOLES")] == 2 and "EDGE_MARGIN" not in str(ents)  # the retracted G1 rod hangs through G2
    ents = dxf_entities(dxf(geo, None, ["outline", "margins"]))
    assert ents == Counter({("POLYLINE", "BOUNDS"): 1, ("POLYLINE", "EDGE_MARGIN"): 1, ("POLYLINE", "HOLE_AREA"): 1})
    assert dxf_entities(dxf(geo, 0, ["holes", "labels"]))[("TEXT", "LABELS")] == 2


def test_svg_of_one_layer_is_a_single_sheet():
    geo = geometry()
    svg = EXPORTERS["svg"]
    root = ET.fromstring(svg().export(geo, export_options(svg, "G0", ["outline", "holes"], geo)))
    assert [g.get("id") for g in root.iter(SVG + "g")] == ["plane-0"]
    assert root.get("width") == "120mm"
    classes = Counter(e.get("class") for e in root.iter() if e.get("class"))
    assert classes == Counter({"bounds": 1, "hole": 2})
    assert not list(root.iter(SVG + "text"))


def test_svg_top_view_shows_g0_holes_without_rods():
    geo = geometry()
    svg = EXPORTERS["svg"]
    root = ET.fromstring(svg().export(geo, export_options(svg, None, ["holes"], geo)))
    top = next(g for g in root.iter(SVG + "g") if g.get("id") == "top")
    assert len([c for c in top.iter(SVG + "circle") if c.get("class") == "hole"]) == 2
    default = ET.fromstring(svg().export(geo))
    top = next(g for g in default.iter(SVG + "g") if g.get("id") == "top")
    assert not [c for c in top.iter(SVG + "circle") if c.get("class") == "hole"]  # the rods cover them


def test_csv_and_rod_positions_of_one_layer():
    geo = geometry()
    rows = EXPORTERS["csv"]().export(geo, export_options(EXPORTERS["csv"], 2, None, geo)).strip().split("\n")[1:]
    assert [r.split(",")[0] for r in rows] == ["G2", "G2"]
    data = json.loads(EXPORTERS["rods"]().export(geo, export_options(EXPORTERS["rods"], 3, None, geo)))
    assert [layer["name"] for layer in data["layers"]] == ["G3"] and len(data["motors"]) == 2


def test_obstacles_follow_the_layer():
    p = Project.from_dict({"stack": {"n_motor_planes": 3}, "obstacles": [
        {"shape": "rect", "x": 20, "y": 20, "w": 10, "h": 10, "plane": 2},
    ]})
    geo = build_geometry(Model(p), [Placement(80, 80, 1, 0)])
    assert len(obstacles_of_layer(geo, None)) == 1 and len(obstacles_of_layer(geo, 2)) == 1
    assert obstacles_of_layer(geo, 0) == []


def test_options_are_checked():
    geo = geometry()
    exporter = EXPORTERS["dxf"]
    assert export_options(exporter, "all", None, geo).layer is None
    assert export_options(exporter, "G2", "outline,holes", geo).contents == {"outline", "holes"}
    assert export_options(exporter, 1, ["outline", "distances"], geo).contents == {"outline"}  # not in DXF
    for layer, contents in ((4, None), ("x", None), (True, None), (None, ["foo"]), (None, ["distances"]), (None, 5)):
        with pytest.raises(ValueError):
            export_options(exporter, layer, contents, geo)
    with pytest.raises(ValueError):
        export_options(EXPORTERS["json"], 0, None, geo)  # always the whole geometry
    assert export_filename(exporter, export_options(exporter, 0, None, geo)) == "blindsight-G0.dxf"
    assert export_filename(EXPORTERS["rods"], export_options(EXPORTERS["rods"], 2, None, geo)) == "blindsight-rods-G2.json"


def test_layer_choice_follows_the_used_layers():
    # Layers not fixed. A result on G1 only knows G0 and G1, G3 is refused
    m = make_model(stack__n_motor_planes=3, stack__layers_fixed=False)
    geo = build_geometry(m, [pl(60, 60, 1, 0)])
    assert len(geo["planes"]) == 2
    with pytest.raises(ValueError):
        export_options(EXPORTERS["dxf"], 3, None, geo)


# -- Presets and schema -----------------------------------------------------------------------
def test_presets_fit_their_formats_and_have_texts():
    for preset in EXPORT_PRESETS:
        if preset["format"]:
            exporter = EXPORTERS[preset["format"]]
            assert set(preset["contents"] or ()) <= set(exporter.contents)
            assert exporter.layer_choice or preset["layer"] == "all"
    for exporter in EXPORTERS.values():
        assert set(exporter.default_contents) <= set(exporter.contents) <= set(CONTENTS)
    for lang in LANGUAGES:
        with use_language(lang):
            menu = export_menu_schema()
            assert all(c["label"] != f"export.content.{c['name']}" for c in menu["contents"])
            assert all(p["hint"] and p["label"] != f"export.preset.{p['name']}" for p in menu["presets"])
    assert tr("export.preset.kicad_edge").endswith("(Edge.Cuts)")


# -- Endpoints -----------------------------------------------------------------------------------
def call(app, method, path, body=None, query=None):
    raw = json.dumps(body).encode() if body is not None else b""
    return app.dispatch(method, path, query or {}, raw)


def test_export_layout_with_layer_and_contents():
    app = App()
    cfg = json.loads(call(app, "GET", "/api/default").body)
    pls = [{"x": 60, "y": 60, "plane": 1, "angle": 0}, {"x": 30, "y": 30, "plane": 2, "angle": 0}]
    body = {"project": cfg, "placements": pls, "format": "dxf", "layer": 0, "contents": ["outline", "holes"]}
    response = call(app, "POST", "/api/export-layout", body)
    assert response.code == 200 and 'filename="blindsight-G0.dxf"' in response.headers["Content-Disposition"]
    assert dxf_entities(response.body.decode()) == Counter({("POLYLINE", "BOUNDS"): 1, ("CIRCLE", "G0_HOLES"): 2})
    for bad in ({"layer": 9}, {"contents": []}, {"contents": ["nope"]}):
        response = call(app, "POST", "/api/export-layout", {**body, **bad})
        assert response.code == 400 and json.loads(response.body)["errors"], bad
    schema = json.loads(call(app, "GET", "/api/schema").body)
    assert {p["name"] for p in schema["export_menu"]["presets"]} == {p["name"] for p in EXPORT_PRESETS}
    assert next(e for e in schema["exporters"] if e["name"] == "json")["layer_choice"] is False


def test_export_of_a_job_with_layer_and_contents():
    app = App()
    cfg = json.loads(call(app, "GET", "/api/default").body)
    cfg["target_count"] = 2
    cfg["search"]["time_limit_s"] = 1
    job = json.loads(call(app, "POST", "/api/start", cfg).body)["job_id"]
    for _ in range(100):
        if json.loads(call(app, "GET", f"/api/status/{job}").body)["state"] not in ("running", "queued"):
            break
        time.sleep(0.1)
    response = call(app, "GET", f"/api/export/{job}.dxf", query={"layer": ["0"], "contents": ["outline,holes"]})
    assert response.code == 200 and 'filename="blindsight-G0.dxf"' in response.headers["Content-Disposition"]
    ents = dxf_entities(response.body.decode())
    assert set(ents) == {("POLYLINE", "BOUNDS"), ("CIRCLE", "G0_HOLES")} and ents[("CIRCLE", "G0_HOLES")] == 2
    assert call(app, "GET", f"/api/export/{job}.dxf", query={"layer": ["7"]}).code == 400
