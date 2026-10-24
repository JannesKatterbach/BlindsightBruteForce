"""Export of rod positions per layer (JSON)."""

import json

from blindsight.cli import main as cli_main
from blindsight.config import Project
from blindsight.export import EXPORTERS, RodPositionsExporter, build_geometry
from blindsight.export.base import rod_presence
from blindsight.layout import Placement
from blindsight.model import Model
from blindsight.web.server import App


def geometry():
    # Default stack. G1 to G3 every 20 mm, motors on top. A rod of a G1 motor reaches G2 and G3 only when retracted
    model = Model(Project())
    return build_geometry(model, [Placement(30.0, 40.0, 1, 0.0), Placement(80.0, 70.0, 3, 90.0)])


def export():
    return json.loads(RodPositionsExporter().export(geometry()))


def ids(layer, key):
    return [rod["id"] for rod in layer[key]]


def test_layers_come_in_order_from_g0():
    data = export()
    assert [layer["name"] for layer in data["layers"]] == ["G0", "G1", "G2", "G3"]
    assert data["units"] == {"length": "mm", "angle": "deg"}
    assert data["format"] == "blindsight.rod_positions" and data["version"] == 1


def test_presence_distinguishes_always_and_retracted():
    g0, g1, g2, g3 = export()["layers"]
    assert ids(g0, "always_present") == [0, 1] and ids(g1, "always_present") == [0, 1]
    # The G1 rod is only in G2 and G3 when retracted, the G3 rod is always there
    assert ids(g2, "present_when_retracted") == [0] and ids(g2, "always_present") == [1]
    assert ids(g3, "present_when_retracted") == [0] and ids(g3, "always_present") == [1]
    for layer in (g0, g1, g2, g3):
        assert layer["present_when_extended"] == [] and layer["present_during_travel"] == []


def test_coordinates_are_millimetres_from_the_bottom_left_origin():
    data = export()
    rod = data["layers"][0]["always_present"][0]
    assert (rod["x"], rod["y"], rod["motor_layer"]) == (30.0, 40.0, "G1")
    assert data["build_area"] == {"width": 120.0, "height": 120.0}


def test_presence_rules_on_a_single_layer():
    plane = {"z_top": -40.0, "z_bottom": -41.6}
    rod = {"bottom_retracted": -77.0, "tip_retracted": 0.0, "bottom_extended": -27.0, "tip_extended": 50.0}
    assert rod_presence(rod, plane) == "retracted"
    assert rod_presence(rod, {"z_top": 0.0, "z_bottom": -6.0}) == "always"
    assert rod_presence(rod, {"z_top": 60.0, "z_bottom": 55.0}) is None
    assert rod_presence({**rod, "tip_retracted": -10.0}, {"z_top": -2.0, "z_bottom": -4.0}) == "extended"


def test_exporter_is_registered_by_name():
    assert EXPORTERS["rods"] is RodPositionsExporter
    assert EXPORTERS["json"] is not RodPositionsExporter
    app = App()
    body = {"project": Project().to_dict(), "placements": [{"x": 30, "y": 40, "plane": 1, "angle": 0}], "format": "rods"}
    code, ctype, payload = app.handle("POST", "/api/export-layout", {}, json.dumps(body).encode())
    assert code == 200 and ctype.startswith("application/json")
    assert json.loads(payload)["layers"][0]["always_present"][0]["x"] == 30


def test_cli_writes_rod_positions(tmp_path):
    p = Project()
    p.target_count = 2
    p.search.time_limit_s = 1
    cfg = tmp_path / "cfg.json"
    cfg.write_text(p.to_json(), encoding="utf-8")
    out = tmp_path / "rods.json"
    assert cli_main([str(cfg), "--quiet", "--rods", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["layers"][0]["always_present"]) == 2
