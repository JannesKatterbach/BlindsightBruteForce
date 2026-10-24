"""Translations. Catalog consistency, LocalText, server language per request, CLI --lang."""

import json
import pathlib
import pickle
import re
import string
import time

import pytest
from blindsight.cli import main as cli_main
from blindsight.config import FIELD_META, ConfigError, Project
from blindsight.export import EXPORTERS
from blindsight.i18n import LANGUAGES, catalog, localize, negotiate, normalize_language, tr, use_language
from blindsight.model import KIND_GEAR, KIND_HOUSING, KIND_OBSTACLE, KIND_ROD
from blindsight.optimizers.base import STATUS_WITH_MESSAGE
from blindsight.sketch import CONSTRAINT_TYPES, REFS
from blindsight.web.server import App

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "blindsight"


def placeholders(template):
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


def test_all_languages_have_the_same_keys_and_placeholders():
    base = catalog("de")
    for language in LANGUAGES:
        texts = catalog(language)
        assert set(texts) == set(base), language
        for key, template in texts.items():
            assert placeholders(template) == placeholders(base[key]), (language, key)
            assert template.strip(), (language, key)


def test_every_key_used_in_the_code_exists():
    used = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        used.update(re.findall(r'\btr\(\s*"([a-z0-9_.]+)"', text))
        for pair in re.findall(r'\btr\(\s*"([a-z0-9_.]+)" if [^"]+ else "([a-z0-9_.]+)"', text):
            used.update(pair)
    assert used and not used - set(catalog("de"))


def test_complex_fields_have_help():
    keys = set(catalog("de"))
    for path in ("clearance", "rod.stroke", "motor.center_distance", "stack.mode", "search.optimizer", "search.pattern",
                 "search.pattern_pitch", "search.max_block_holes", "search.weights.area"):
        assert f"field.{path}.help" in keys, path


def test_dynamic_keys_exist():
    keys = set(catalog("de"))
    for meta in FIELD_META:
        assert {f"field.{meta.path}.label", f"field.{meta.path}.tip"} <= keys, meta.path
        for value in meta.options or ():
            assert f"option.{meta.path}.{value}" in keys
    assert {f"export.{name}" for name in EXPORTERS} <= keys
    assert {f"constraint.{name}" for name in CONSTRAINT_TYPES} <= keys
    assert {f"ref.{name}" for name in REFS} <= keys
    assert {f"part.{kind}" for kind in (KIND_HOUSING, KIND_GEAR, KIND_ROD, KIND_OBSTACLE, "threaded_rod")} <= keys
    assert {f"status.{status}" for status in STATUS_WITH_MESSAGE} <= keys


def test_local_text_renders_again_in_another_language():
    with use_language("de"):
        text = tr("layout.unit_message", unit=3, message=tr("model.outside_zones"))
    assert text == "Einheit 3. Motor liegt außerhalb der Montagebereiche der Ebene"
    assert text.localized("en") == "Unit 3. Motor lies outside the mounting areas of the layer"
    assert text.localized("fr").startswith("Unité 3. Le moteur se trouve")
    copy = pickle.loads(pickle.dumps(text))
    assert copy == text and copy.localized("en") == text.localized("en")


def test_localize_walks_containers_and_joins_lists():
    with use_language("de"):
        data = {"a": [tr("part.gear"), ("x", tr("part.rod"))], "b": tr("sketch.constraint_label", name="L", where=[tr("sketch.side", n=2)], number=1)}
    assert localize(data, "en") == {"a": ["Gear", ["x", "Rod"]], "b": "L (Side 2) [no. 1]"}


def test_language_codes_are_normalised():
    assert normalize_language("en-GB") == "en" and normalize_language("xx") == "de" and normalize_language(None) == "de"
    assert negotiate("es-ES,fr;q=0.8,en;q=0.5") == "fr" and negotiate("") == "de"


def test_validation_errors_follow_the_language():
    for language, needle in (("de", "Muss größer als 0"), ("en", "Must be greater than 0"), ("fr", "Doit être supérieur à 0")):
        with use_language(language), pytest.raises(ConfigError) as exc:
            Project.from_dict({"rod": {"diameter": -1}})
        assert any(needle in error for error in exc.value.errors), language


def call(app, method, path, obj=None, headers=None, query=None):
    body = json.dumps(obj).encode() if obj is not None else b""
    code, _, payload = app.handle(method, path, query or {}, body, headers)
    return code, json.loads(payload)


def test_server_answers_in_the_language_of_the_request():
    app = App()
    bad = {"rod": {"diameter": -1}}
    assert "Must be greater" in call(app, "POST", "/api/start", bad, {"X-Language": "en"})[1]["error"]
    assert "Doit être supérieur" in call(app, "POST", "/api/start", bad, {"Accept-Language": "fr-FR,fr;q=0.9"})[1]["error"]
    assert "Muss größer" in call(app, "POST", "/api/start", bad, {"X-Language": "de", "Accept-Language": "en"})[1]["error"]
    assert "Must be greater" in call(app, "POST", "/api/start", bad, query={"lang": ["en"]})[1]["error"]
    assert call(app, "GET", "/api/nope", headers={"X-Language": "fr"})[1]["error"] == "introuvable"


def test_schema_texts_are_translated():
    app = App()
    schemas = {lang: call(app, "GET", "/api/schema", headers={"X-Language": lang})[1] for lang in LANGUAGES}
    labels = {lang: {f["path"]: f["label"] for f in s["fields"]} for lang, s in schemas.items()}
    assert labels["de"]["search.tile_rods"] != labels["en"]["search.tile_rods"] != labels["fr"]["search.tile_rods"]
    assert schemas["en"]["language"] == "en" and [l["code"] for l in schemas["en"]["languages"]] == list(LANGUAGES)
    exporters = {lang: {e["name"]: e["label"] for e in s["exporters"]} for lang, s in schemas.items()}
    assert exporters["en"]["rods"] == "Rod positions (JSON)" and exporters["fr"]["rods"].startswith("Positions")
    constraints = {c["name"]: c["label"] for c in schemas["en"]["sketch_constraints"]}
    assert constraints["perpendicular"] == "Perpendicular"


def test_results_of_a_run_follow_a_language_switch():
    app = App()
    project = Project()
    project.target_count = 2
    project.search.time_limit_s = 2
    job = call(app, "POST", "/api/start", project.to_dict(), {"X-Language": "de"})[1]["job_id"]
    for _ in range(300):
        if call(app, "GET", f"/api/status/{job}")[1]["state"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    note_de = call(app, "GET", f"/api/result/{job}", headers={"X-Language": "de"})[1]["result"]["optimality_note"]
    note_en = call(app, "GET", f"/api/result/{job}", headers={"X-Language": "en"})[1]["result"]["optimality_note"]
    assert "Zielanzahl 2 erreicht" in note_de and "Target number 2 reached" in note_en


def test_cli_prints_in_the_chosen_language(tmp_path, capsys):
    project = Project()
    project.target_count = 2
    project.search.time_limit_s = 1
    cfg = tmp_path / "cfg.json"
    cfg.write_text(project.to_json(), encoding="utf-8")
    assert cli_main([str(cfg), "--quiet", "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert "Best solution. 2 of 2 rods" in out and "Target number 2 reached" in out
    assert cli_main([str(cfg), "--quiet", "--lang", "fr"]) == 0
    assert "Meilleure solution" in capsys.readouterr().out


# --- UI catalogs (web/static/js/i18n/*.js) ------------------------------------------------------------
STATIC = SRC / "web" / "static"


def ui_catalog(language):
    text = (STATIC / "js" / "i18n" / f"{language}.js").read_text(encoding="utf-8")
    return json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))


def ui_placeholders(template):
    return set(re.findall(r"\{(\w+)\}", template))


def test_ui_catalogs_have_the_same_keys_and_placeholders():
    base = ui_catalog("de")
    for language in LANGUAGES:
        texts = ui_catalog(language)
        assert set(texts) == set(base), language
        for key, template in texts.items():
            assert ui_placeholders(template) == ui_placeholders(base[key]), (language, key)


def test_every_ui_key_exists():
    keys = set(ui_catalog("de"))
    used = set()
    for path in (STATIC / "js").rglob("*.js"):
        if "i18n" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        used.update(re.findall(r'\bt\(\s*"([a-z0-9_.]+)"', text))
        used.update(re.findall(r'data-i18n="([a-z0-9_.]+)"', text))
    used.update(re.findall(r'data-(?:i18n(?:-title|-placeholder)?|help(?:-title)?)="([a-z0-9_.]+)"', (STATIC / "index.html").read_text(encoding="utf-8")))
    assert not {key for key in used if not key.endswith(".")} - keys
    dynamic = {
        "ui.job.": ("queued", "running", "finished", "failed", "cancelled"),
        "ui.status.": ("completed", "time_limit", "candidate_limit", "cancelled", "infeasible", "stagnation", "manual"),
        "ui.kind.": (KIND_HOUSING, KIND_GEAR, KIND_ROD, KIND_OBSTACLE),
        "ui.term.": ("count", "area", "uniformity", "regularity"),
        "ui.sk.state.": ("under", "full", "over", "conflict", "invalid"),
        "ui.sk.status.": ("ok", "conflict", "redundant", "disabled"),
        "ui.sk.ref.": tuple(REFS),
        "ui.progress.": ("status", "phase", "candidates", "elapsed", "best_count", "best_score", "info"),
        "ui.levels.head.": ("layer", "z_top", "rod_total", "below_mount", "thread"),
        "ui.obstacle.": ("shape", "x", "y", "w", "h", "r", "angle", "plane", "name", "rect", "circle"),
    }
    for prefix, names in dynamic.items():
        assert {prefix + name for name in names} <= keys, prefix
