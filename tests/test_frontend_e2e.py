"""Browser Regressionstests fuer Fehler der Oberflaeche (Version 0.4.0). Uebersprungen ohne Playwright oder Chromium."""

import json
import os
import threading

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from blindsight.config import Project  # noqa: E402
from blindsight.web.server import serve  # noqa: E402

CHROMIUM = os.environ.get("BLINDSIGHT_CHROMIUM", "/opt/pw-browsers/chromium")


@pytest.fixture(scope="module")
def base_url():
    server = serve("127.0.0.1", 0, open_browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=CHROMIUM) if os.path.exists(CHROMIUM) else p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium nicht verfuegbar. {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    pg = browser.new_page(locale="de-DE", viewport={"width": 1500, "height": 950})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(base_url)
    pg.wait_for_selector("#in-motor-width")
    pg.wait_for_function("cfg && document.querySelector('#planeTable table')")
    yield pg
    assert pg.errors == []
    pg.close()


def change(pg, selector, value):
    pg.fill(selector, value)
    pg.dispatch_event(selector, "change")


def result_file(placements):
    data = {"project": Project().to_dict(), "placements": placements}
    return {"name": "ergebnis.json", "mimeType": "application/json", "buffer": json.dumps(data).encode()}


GOOD = [{"x": 30, "y": 60, "plane": 1, "angle": 0}, {"x": 90, "y": 60, "plane": 2, "angle": 0}]


def test_plane_table_follows_plane_count(page):
    # Frueher blieb die Tabelle bei 3 Zeilen und das Lesen stuerzte ab
    page.click("[data-tab=levels]")
    change(page, "#in-stack-n_motor_planes", "5")
    page.wait_for_selector("[data-pt='cap'][data-i='5']")
    change(page, "[data-pt='cap'][data-i='5']", "2")
    assert page.evaluate("cfg.stack.max_per_plane[5]") == 2
    # Erlaubte Ebenen und Dicken haben nur noch einen Editor (die Tabelle)
    assert page.locator("#in-stack-allowed_planes").count() == 0
    assert page.locator("#in-stack-thicknesses").count() == 0


def test_empty_required_field_is_marked_and_keeps_value(page):
    before = page.evaluate("cfg.rod.diameter")
    change(page, "#in-rod-diameter", "")
    page.wait_for_selector("#in-rod-diameter.err")
    assert page.evaluate("cfg.rod.diameter") == before


def test_weights_above_slider_range_are_kept(page):
    page.evaluate("loadCfg({search: {weights: {count: 50, area: 1, uniformity: 1, regularity: 1}}})")
    page.wait_for_function("document.querySelector('#wv-count').textContent === '50'")
    assert page.evaluate("cfg.search.weights.count") == 50
    assert float(page.get_attribute("[data-w='count']", "max")) >= 50


def test_zone_add_with_null_zones_does_not_crash(page):
    page.evaluate("cfg.stack.mount_zones = null")
    page.click("[data-tab=bounds]")
    page.click("#zoneAdd")
    assert page.evaluate("Object.keys(cfg.stack.mount_zones)") == ["1"]


def test_tooltip_returns_after_dropping_the_sketch(page):
    tip = page.get_attribute("#in-motor-width", "title")
    page.evaluate("cfg.motor.sketch = {points: [[-20,-10],[-2,-10],[-2,10],[-20,10]], constraints: []}; drawMotor()")
    assert page.is_disabled("#in-motor-width")
    page.click("#btnDropSketch")
    page.wait_for_function("!document.querySelector('#in-motor-width').disabled")
    assert page.get_attribute("#in-motor-width", "title") == tip and tip


def test_export_formats_come_from_the_schema(page):
    values = page.eval_on_selector_all("#expFmt option", "opts => opts.map(o => o.value)")
    assert sorted(values) == ["csv", "dxf", "json", "rods", "svg"]


def test_loaded_result_click_reset_and_export(page):
    page.set_input_files("#fileResult", result_file(GOOD))
    page.wait_for_selector("#resultBox:not([hidden])")
    page.check("#optEdit")
    # Klick ohne Bewegung waehlt nur aus und markiert nichts als bearbeitet
    page.click("#view circle[data-unit='0']")
    page.wait_for_selector("#edX")
    page.wait_for_timeout(300)
    assert page.evaluate("edited") is False
    # Bearbeiten in mm, dann Zuruecksetzen auf den geladenen Stand
    assert page.input_value("#edX") == "30"
    change(page, "#edX", "50")
    page.wait_for_function("edited && lastGeo.units[0].x === 50")
    page.click("#edReset")
    page.wait_for_function("!edited && lastGeo.units[0].x === 30")
    # Gleiche Datei erneut laden loest wieder aus
    page.evaluate("lastGeo = null")
    page.set_input_files("#fileResult", result_file(GOOD))
    page.wait_for_function("lastGeo && lastGeo.units.length === 2")
    page.select_option("#expFmt", "dxf")
    with page.expect_download() as download:
        page.click("#btnExport")
    assert download.value.suggested_filename == "blindsight.dxf"


def test_empty_result_clears_old_views(page):
    page.set_input_files("#fileResult", result_file(GOOD))
    page.wait_for_function("lastGeo && document.querySelector('#collisions').innerText.length > 0")
    page.evaluate("lastGeo = null; renderResult()")
    assert page.inner_text("#collisions") == "" and page.inner_html("#view") == ""


def test_sketch_drag_with_slow_server_answers(page):
    # Spaete Antworten nach dem Loslassen warfen frueher einen TypeError
    def slow(route):
        page.wait_for_timeout(150)
        route.continue_()

    page.click("[data-tab=sketch]")
    page.wait_for_function("__sk.sk.points.length >= 3 && __sk.res && __sk.busy === 0")
    page.route("**/api/sketch/solve", slow)
    handle = page.locator("#skCanvas circle[data-sk-point='0']").bounding_box()
    x, y = handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 30, y + 20, steps=6)
    page.mouse.up()
    page.wait_for_function("__sk.busy === 0", timeout=15000)
    page.unroute("**/api/sketch/solve")
    assert page.evaluate("__sk.hist.length") >= 1


def test_repeating_tile_run_shows_tile_outlines(page):
    page.select_option("#exampleSel", "repeating_tile")
    page.wait_for_function("cfg.search.optimizer === 'periodic_tile'")
    page.click("[data-tab=optim]")
    # Only the fields of the chosen pattern are shown
    assert page.locator("#in-search-pattern_pitch").is_visible() and page.locator("#in-search-tile_rods").is_hidden()
    assert page.locator("#in-search-patterns").is_hidden()
    change(page, "#in-search-time_limit_s", "4")
    page.click("#btnStart")
    page.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    assert "Muster Würfel Fünf" in page.inner_text("#statusBox")
    assert page.locator("#view rect.tile").count() >= 1


def test_rod_positions_download(page):
    page.set_input_files("#fileResult", result_file(GOOD))
    page.wait_for_selector("#resultBox:not([hidden])")
    page.select_option("#expFmt", "rods")
    with page.expect_download() as download:
        page.click("#btnExport")
    assert download.value.suggested_filename == "blindsight-rods.json"
    data = json.loads(open(download.value.path(), encoding="utf-8").read())
    assert data["layers"][0]["name"] == "G0" and len(data["layers"][0]["always_present"]) == 2


def test_language_switch_translates_the_whole_ui(page):
    page.set_input_files("#fileResult", result_file(GOOD))
    page.wait_for_selector("#resultBox:not([hidden])")
    label = "label[data-label-for='rod.diameter']"
    german = page.inner_text(label)
    page.select_option("#langSel", "en")
    page.wait_for_function("document.querySelector('#collisions').innerText.includes('No collisions')")
    assert page.inner_text("[data-tab=results]") == "Results"
    assert page.inner_text(label) != german and "[mm]" in page.inner_text(label)
    assert "2 of" in page.inner_text("#statusBox") and "No collisions" in page.inner_text("#collisions")
    assert page.evaluate("document.documentElement.lang") == "en"
    page.select_option("#langSel", "fr")
    page.wait_for_function("document.querySelector('#collisions').innerText.includes('Aucune collision')")
    assert page.inner_text("[data-tab=results]") == "Résultats"
    # Errors of the core come in the chosen language too
    page.click("[data-tab=geometry]")
    change(page, "#in-rod-diameter", "-1")
    page.wait_for_function("document.querySelector('#banner').innerText.includes('Doit être supérieur')")
    page.reload()
    page.wait_for_selector("#in-motor-width")
    assert page.inner_text("[data-tab=results]") == "Résultats"  # the choice is remembered
    page.select_option("#langSel", "de")
    page.wait_for_function("document.querySelector('[data-tab=results]').textContent === 'Ergebnisse'")
