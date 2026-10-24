"""Fixed G0 holes. Hole pattern files, the optimizer fixed_holes, API and CLI."""

import json

import pytest

from blindsight import holes as hole_files
from blindsight.cli import main as cli_main
from blindsight.config import ConfigError, Project
from blindsight.export import RodPositionsExporter, build_geometry
from blindsight.layout import layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import get_optimizer
from blindsight.web.server import App

GRID = [[x, y] for y in (30.0, 60.0, 90.0) for x in (30.0, 60.0, 90.0)]


def project(holes, **search):
    p = Project()
    p.search.optimizer = "fixed_holes"
    p.search.time_limit_s = 6
    p.holes = holes
    for key, value in search.items():
        setattr(p.search, key, value)
    p.validate()
    return p


def run(p):
    model = Model(p)
    return model, get_optimizer("fixed_holes").run(model)


def test_all_holes_are_served_at_their_positions():
    model, res = run(project(GRID))
    best = res.best
    assert sorted([q.x, q.y] for q in best.placements) == sorted(GRID)
    assert layout_from_placements(model, best.placements).is_valid()
    assert res.target == 9 and any("Alle 9 Löcher" in m for m in res.messages)


def test_impossible_holes_give_a_partial_result_with_reasons():
    _, res = run(project([[30.0, 30.0], [33.0, 30.0], [80.0, 80.0]]))
    assert len(res.best.placements) == 2
    text = " ".join(res.messages)
    assert "nicht alle 3 Löcher" in text and "2 von 3 Löchern bedient" in text
    assert "Kollidiert in jeder Lage mit den bedienten Löchern" in text


def test_hole_outside_the_build_area_is_reported():
    _, res = run(project([[60.0, 60.0], [500.0, 60.0]]))
    assert len(res.best.placements) == 1
    assert any("Loch 2 (500.00, 60.00)" in m for m in res.messages)


def test_fixed_holes_need_holes():
    p = Project()
    p.search.optimizer = "fixed_holes"
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any(e.startswith("holes.") for e in exc.value.errors)


def test_parse_holes_and_tile_files():
    doc = hole_files.parse({"format": "blindsight.holes", "holes": [{"x": 1, "y": 2}, [3, 4]],
                            "tile": {"width": 20, "height": 10, "scalable": True, "holes": [{"x": 0, "y": 0}, {"x": 10, "y": 5}]}})
    assert doc.holes == [[1.0, 2.0], [3.0, 4.0]]
    assert doc.tile.scalable and doc.tile.holes == [[0.0, 0.0], [10.0, 5.0]]
    again = hole_files.parse(doc.as_dict())
    assert again.holes == doc.holes and again.tile == doc.tile


@pytest.mark.parametrize("data", [[1, 2], {"format": "x"}, {"holes": [{"x": "a", "y": 1}]}, {"holes": []},
                                  {"units": {"length": "inch"}, "holes": [[1, 2]]},
                                  {"tile": {"width": 10, "height": 10, "holes": [[12, 0]]}}])
def test_bad_hole_files_are_rejected(data):
    with pytest.raises(hole_files.HolesError):
        hole_files.parse(data)


def test_rod_positions_export_round_trip():
    model, res = run(project(GRID))
    exported = json.loads(RodPositionsExporter().export(build_geometry(model, res.best.placements)))
    assert sorted(hole_files.parse(exported).holes) == sorted(GRID)
    motor = exported["motors"][0]
    assert {"motor_layer", "angle", "center_distance", "gear_axis"} <= set(motor)
    # The gear axis lies at the centre distance from the rod
    dx, dy = motor["gear_axis"][0] - motor["x"], motor["gear_axis"][1] - motor["y"]
    assert abs((dx * dx + dy * dy) ** 0.5 - motor["center_distance"]) < 1e-6


def test_check_reports_close_and_outside_holes():
    problems = hole_files.check(Project(), [[10.0, 10.0], [12.0, 10.0], [500.0, 10.0]])
    messages = [p["message"] for p in problems]
    assert any("Loch 2 liegt zu nah an Loch 1" in m for m in messages)
    assert any("Loch 3" in m and "außerhalb" in m for m in messages)


def call(app, path, obj):
    code, _, payload = app.handle("POST", path, {}, json.dumps(obj).encode())
    return code, json.loads(payload)


def test_api_parses_and_checks_holes():
    app = App()
    code, data = call(app, "/api/holes/parse", {"format": "blindsight.holes", "holes": [{"x": 5, "y": 6}]})
    assert code == 200 and data["holes"][0] == {"id": 0, "x": 5.0, "y": 6.0}
    code, data = call(app, "/api/holes/parse", {"format": "nope"})
    assert code == 400 and "Unbekanntes Format" in data["error"]
    code, data = call(app, "/api/holes/check", {"project": Project().to_dict(), "holes": [[10, 10], [11, 10]]})
    assert code == 200 and len(data["problems"]) == 1


def test_cli_with_a_hole_file(tmp_path, capsys):
    cfg = tmp_path / "cfg.json"
    p = Project()
    p.search.time_limit_s = 3
    cfg.write_text(p.to_json(), encoding="utf-8")
    holes = tmp_path / "holes.json"
    holes.write_text(json.dumps(hole_files.document(GRID)), encoding="utf-8")
    out = tmp_path / "rods.json"
    assert cli_main([str(cfg), "--quiet", "--holes", str(holes), "--rods", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["motors"]) == 9
    tile = tmp_path / "tile.json"
    tile.write_text(json.dumps({"format": "blindsight.holes", "holes": [],
                                "tile": {"width": 40, "height": 34, "scalable": False, "holes": [[0, 0], [20, 17]]}}), encoding="utf-8")
    assert cli_main([str(cfg), "--quiet", "--holes", str(tile)]) == 0
    assert "Eigene Kachel" in capsys.readouterr().out


def test_example_hole_files_parse():
    import pathlib
    folder = pathlib.Path(__file__).resolve().parents[1] / "examples" / "holes"
    docs = {path.stem: hole_files.parse(json.loads(path.read_text(encoding="utf-8"))) for path in folder.glob("*.json")}
    assert len(docs["grid_3x3"].holes) == 9 and docs["tile_dice_five"].tile.scalable
