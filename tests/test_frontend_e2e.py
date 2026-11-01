"""Browser regression tests of the UI (since version 0.4.0). Skipped without Playwright or Chromium."""

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
    pg.wait_for_selector("#in-rod-diameter")
    pg.wait_for_function("cfg && document.querySelector('#planeTable table')")
    yield pg
    assert pg.errors == []
    pg.close()


def open_details(pg, inside):
    """Open the folded part that holds the element."""
    pg.evaluate(f"document.querySelector('{inside}').closest('details').open = true")


def change(pg, selector, value):
    pg.fill(selector, value)
    pg.dispatch_event(selector, "change")


def result_file(placements):
    data = {"project": Project().to_dict(), "placements": placements}
    return {"name": "ergebnis.json", "mimeType": "application/json", "buffer": json.dumps(data).encode()}


STEP_RESULTS = "[data-step=results] span[data-i18n]"
GOOD = [{"x": 30, "y": 60, "plane": 1, "angle": 0}, {"x": 90, "y": 60, "plane": 2, "angle": 0}]


def test_plane_table_follows_plane_count(page):
    # The table used to stay at 3 rows and reading it crashed
    change(page, "#in-stack-n_motor_planes", "5")
    open_details(page, "#planeTable")
    page.wait_for_selector("[data-pt='cap'][data-i='5']")
    change(page, "[data-pt='cap'][data-i='5']", "2")
    assert page.evaluate("cfg.stack.max_per_plane[5]") == 2
    # Permitted layers and thicknesses have only one editor now (the table)
    assert page.locator("#in-stack-allowed_planes").count() == 0
    assert page.locator("#in-stack-thicknesses").count() == 0


def test_empty_required_field_is_marked_and_keeps_value(page):
    before = page.evaluate("cfg.rod.diameter")
    change(page, "#in-rod-diameter", "")
    page.wait_for_selector("#in-rod-diameter.err")
    assert page.evaluate("cfg.rod.diameter") == before


def test_goals_move_freely_and_must_add_up_to_100_percent(page):
    page.evaluate("loadCfg({search: {weights: {count: 50, area: 1, uniformity: 1, regularity: 1}}})")  # free mode
    page.wait_for_function("cfg.search.weights.count === 94")  # older relative weights keep their ratio
    page.click("[data-step=run]")
    assert page.inner_text("#weightSum") == "Summe 100 %"
    change(page, "#wn-count", "50")
    change(page, "#wn-area", "1")
    assert page.inner_text("#weightSum") == "Summe 55 %, es fehlen 45 %"
    assert page.locator("#btnStart").is_disabled() and "100 %" in page.inner_text("#startHint")
    # Number field and slider stay in step, nothing is redistributed automatically
    change(page, "#wn-area", "45")
    assert page.input_value("[data-w=area]") == "45" and page.evaluate("cfg.search.weights.count") == 50
    assert page.inner_text("#weightSum") == "Summe 99 %, es fehlen 1 %"
    page.fill("[data-w=uniformity]", "10")
    page.dispatch_event("[data-w=uniformity]", "input")
    assert page.input_value("#wn-uniformity") == "10" and page.inner_text("#weightSum") == "Summe 107 %, 7 % zu viel"
    page.click("#weightNormalize")
    assert page.inner_text("#weightSum") == "Summe 100 %" and page.locator("#btnStart").is_enabled()


def test_zone_add_with_null_zones_does_not_crash(page):
    page.evaluate("cfg.stack.mount_zones = null")
    page.click("[data-step=board]")
    open_details(page, "#zoneTable")
    page.click("#zoneAdd")
    assert page.evaluate("Object.keys(cfg.stack.mount_zones)") == ["1"]


def test_tooltip_returns_after_dropping_the_sketch(page):
    tip = page.get_attribute("#in-motor-width", "title")
    page.evaluate("cfg.motor.sketch = {points: [[-20,-10],[-2,-10]], entities: [{type: 'line', points: [0, 1]}], constraints: []}; drawMotor()")
    assert page.is_disabled("#in-motor-width")
    page.click("[data-step=motor]")
    page.once("dialog", lambda dialog: dialog.accept())  # discarding asks first
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
    # A click without movement only selects and marks nothing as edited
    page.click("#view circle[data-unit='0']")
    page.wait_for_selector("#edX")
    page.wait_for_timeout(300)
    assert page.evaluate("edited") is False
    # Edit in mm, then reset to the loaded state
    assert page.input_value("#edX") == "30"
    change(page, "#edX", "50")
    page.wait_for_function("edited && lastGeo.units[0].x === 50")
    page.click("#edReset")
    page.wait_for_function("!edited && lastGeo.units[0].x === 30")
    # Loading the same file again triggers again
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
    # Late answers after the release used to throw a TypeError
    def slow(route):
        page.wait_for_timeout(150)
        route.continue_()

    page.click("[data-step=motor]")
    page.click("[data-motor-view=sketch]")
    page.wait_for_function("__sk.sk.entities.length && __sk.res && __sk.busy === 0")
    page.route("**/api/sketch/solve", slow)
    handle = page.locator("#skCanvas circle[data-sk-ref='p2']").bounding_box()  # top right corner of the housing
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
    page.click("[data-step=holes]")
    # Only the fields of the chosen pattern are shown
    assert page.locator("#patternCards [data-pattern=centered_square].chosen").count() == 1
    assert page.locator("#in-search-pattern_count").is_visible() and page.locator("#in-search-tile_rods").is_hidden()
    assert page.locator("#in-search-patterns").is_hidden()
    page.click("[data-step=run]")
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
    assert page.inner_text(STEP_RESULTS) == "Result"
    assert page.inner_text(label) != german and "[mm]" in page.inner_text(label)
    assert "2 of" in page.inner_text("#statusBox") and "No collisions" in page.inner_text("#collisions")
    assert page.evaluate("document.documentElement.lang") == "en"
    page.select_option("#langSel", "fr")
    page.wait_for_function("document.querySelector('#collisions').innerText.includes('Aucune collision')")
    assert page.inner_text(STEP_RESULTS) == "Résultat"
    # Errors of the core come in the chosen language too
    page.click("[data-step=basics]")
    change(page, "#in-rod-diameter", "-1")
    page.wait_for_function("document.querySelector('#banner').innerText.includes('Doit être supérieur')")
    page.reload()
    page.wait_for_selector("#in-rod-diameter")
    assert page.inner_text(STEP_RESULTS) == "Résultat"  # the choice is remembered
    page.select_option("#langSel", "de")
    page.wait_for_function(f"document.querySelector('{STEP_RESULTS}').textContent === 'Ergebnis'")


def choose_mode(page, mode):
    page.click("[data-step=mode]")
    page.click(f"[data-mode={mode}]")
    page.click("[data-step=holes]")


def test_hole_generator_builds_a_file_and_runs_fixed_holes(page):
    choose_mode(page, "holes")
    page.click("text=Aus Text einfügen")
    page.fill("#holePaste", "30;30\n60;30\n90;30\n30,5;60\n60 60\n90\t60")
    page.click("#holePasteReplace")
    assert page.locator("#holeTable tr").count() == 7  # header plus six holes
    assert page.inner_text("#holeTable tr:nth-child(5) td:first-child") == "4"
    assert page.input_value("#holeTable [data-hole='3'][data-c='0']") == "30.5"
    # A click into the free preview area places a hole, too close holes are reported by the core
    box = page.locator("#holePreview").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.9, box["y"] + box["height"] * 0.1)
    assert page.locator("#holeTable tr").count() == 8
    page.fill("#holeTable [data-hole='6'][data-c='0']", "31")
    page.dispatch_event("#holeTable [data-hole='6'][data-c='0']", "change")
    page.fill("#holeTable [data-hole='6'][data-c='1']", "30")
    page.dispatch_event("#holeTable [data-hole='6'][data-c='1']", "change")
    page.wait_for_function("document.querySelector('#holeProblems').innerText.includes('zu nah')")
    page.click("#holeTable [data-hole-del='6']")
    page.wait_for_function("document.querySelector('#holeProblems').innerText === ''")
    with page.expect_download() as download:
        page.click("#holeDownload")
    data = json.loads(open(download.value.path(), encoding="utf-8").read())
    assert data["format"] == "blindsight.holes" and len(data["holes"]) == 6 and data["holes"][3]["x"] == 30.5
    page.wait_for_function("cfg.search.optimizer === 'fixed_holes' && cfg.holes.length === 6")  # taken over at once
    page.click("[data-step=run]")
    assert "6 Löcher" in page.inner_text("#runSummary")
    change(page, "#in-search-time_limit_s", "4")
    page.click("#btnStart")
    page.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    assert "6 von 6" in page.inner_text("#statusBox")
    assert "Alle 6 Löcher" in page.inner_text("#messages")


def test_hole_generator_tile_mode_sets_an_own_pattern(page):
    choose_mode(page, "pattern")
    page.click("#patternCards [data-pattern=custom]")
    page.wait_for_selector("#holeTileBox:not([hidden])")
    page.fill("#holeTileW", "40")
    page.dispatch_event("#holeTileW", "change")
    page.fill("#holeTileH", "34")
    page.dispatch_event("#holeTileH", "change")
    page.click("text=Aus Text einfügen")
    page.fill("#holePaste", "0;0\n20;17\n45;3")
    page.click("#holePasteReplace")
    page.wait_for_function("document.querySelector('#holeProblems').innerText.includes('Loch 3')")
    page.click("#holeTable [data-hole-del='2']")
    page.wait_for_function("cfg.search.pattern === 'custom' && cfg.search.custom_tile.holes.length === 2")
    assert cfg_value(page, "search.optimizer") == "periodic_tile"
    assert cfg_value(page, "search.custom_tile.width") == 40


def cfg_value(page, path):
    return page.evaluate(f"getPath(cfg, '{path}')")


def test_help_buttons_explain_fields_and_sections(page):
    page.click("label[data-label-for='rod.stroke'] .helpBtn")
    pop = page.locator("#helpPop")
    assert pop.is_visible() and "G0" in pop.inner_text() and "Hub" in pop.inner_text()
    assert "[mm]" in page.inner_text("label[data-label-for='rod.stroke']")  # the button adds no text to the label
    page.keyboard.press("Escape")
    assert pop.is_hidden()
    # Simple fields get no help button, complex ones do
    assert page.locator("label[data-label-for='rod.diameter'] .helpBtn").count() == 0
    page.click("[data-step=board]")
    page.click("#tab-board summary[data-help='ui.help.obstacles'] .helpBtn")
    assert "Sperrzone" in pop.inner_text()
    page.mouse.click(5, 5)  # a click elsewhere closes it
    assert pop.is_hidden()
    # Help follows a language switch
    page.select_option("#langSel", "en")
    page.wait_for_function(f"document.querySelector('{STEP_RESULTS}').textContent === 'Result'")
    page.click("[data-step=mode]")
    page.click("#tab-mode h2[data-help='ui.help.mode'] .helpBtn")
    assert "Give the holes fits" in pop.inner_text()
    page.click("[data-step=run]")
    page.click("#tab-run h2[data-help='ui.help.goals'] .helpBtn")
    assert "every served hole" in pop.inner_text()


def test_rarely_changed_fields_are_folded(page):
    page.click("[data-step=run]")
    assert page.locator("#in-search-time_limit_s").is_visible() and page.locator("#in-search-seed").is_hidden()
    more = page.locator("#f-search-more").locator("xpath=..")
    assert more.locator("summary").inner_text() == "Weitere Einstellungen"
    more.locator("summary").click()
    change(page, "#in-search-seed", "7")
    assert more.locator("summary").inner_text() == "Weitere Einstellungen · 1 geändert"
    # An error in a folded field opens its part
    page.click("[data-step=basics]")
    assert page.locator("#in-tolerance").is_hidden()
    page.evaluate("showFieldErrors(['tolerance. Muss größer als 0 sein'])")
    assert page.locator("#in-tolerance").is_visible()


def test_only_the_spacing_field_of_the_mode_is_shown(page):
    assert page.locator("#in-stack-uniform_spacing").is_visible() and page.locator("#in-stack-gaps").is_hidden()
    page.select_option("#in-stack-mode", "gaps")
    page.dispatch_event("#in-stack-mode", "change")
    assert page.locator("#in-stack-gaps").is_visible() and page.locator("#in-stack-uniform_spacing").is_hidden()
    assert page.locator("#in-stack-distances").is_hidden()


def test_empty_states_and_tabs(page):
    page.click("[data-step=results]")
    assert page.get_attribute("[data-step=results]", "aria-selected") == "true"
    assert page.get_attribute("[data-step=basics]", "aria-selected") == "false"
    assert page.locator("#noResult label[for=fileResult]").is_visible()
    page.click("#btnGoOptim")
    assert page.locator("#tab-run").is_visible()
    page.click("[data-step=board]")
    open_details(page, "#obsTable")
    assert page.inner_text("#obsTable") == "Noch keine Einträge." and page.locator("#obsTable table").count() == 0
    page.click("#obsAdd")
    assert page.locator("#obsTable table [data-obdel='0']").count() == 1


def test_reset_asks_before_discarding_inputs(page):
    page.click("[data-step=motor]")
    change(page, "#in-motor-width", "33")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("#btnReset")
    assert page.evaluate("cfg.motor.width") == 33
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#btnReset")
    page.wait_for_function("cfg.motor.width === defaults.motor.width")


# --- Guided workflow (phase 8) ---------------------------------------------------------------------------------
def test_steps_lead_from_left_to_right(page):
    assert page.locator("#tab-basics").is_visible()
    page.click("#tab-basics [data-goto=motor]")
    assert page.locator("#tab-motor").is_visible() and page.locator("#in-motor-width").is_visible()
    assert page.inner_text("[data-step=basics] .state") == "✓"
    page.click("[data-motor-view=sketch]")
    page.wait_for_function("document.querySelector('#tab-sketch').classList.contains('active')")
    page.click("#tab-motor [data-goto=basics]")
    assert not page.evaluate("document.querySelector('#tab-sketch').classList.contains('active')")  # keys of the sketch are off
    # A field error marks its step
    change(page, "#in-rod-diameter", "-2")
    page.wait_for_function("document.querySelector('[data-step=basics]').dataset.state === 'problem'")
    assert page.inner_text("[data-step=basics] .state") == "!"


def test_pattern_mode_with_individual_motors(page):
    choose_mode(page, "pattern")
    assert page.inner_text("#stepHolesLabel") == "Muster"
    page.click("#patternCards [data-pattern=hex]")
    page.check("input[name=patternRepeat][value=pattern_holes]")
    page.wait_for_function("cfg.search.optimizer === 'pattern_holes' && cfg.search.pattern === 'hex'")
    assert page.locator("#patternCards [data-pattern=free]").is_disabled()  # 2b needs a lattice
    # Two questions. As large as possible only goes with a fixed number of holes
    assert page.locator("#in-search-pattern_distance option[value=largest]").is_disabled()
    page.select_option("#in-search-pattern_count", "exact")
    page.dispatch_event("#in-search-pattern_count", "change")
    assert page.locator("#in-target_count").is_visible() and page.inner_text("[data-label-for=target_count]") == "Anzahl Löcher"
    assert page.locator("#in-search-pattern_distance option[value=largest]").is_enabled()
    page.select_option("#in-search-pattern_count", "fill")
    page.dispatch_event("#in-search-pattern_count", "change")
    page.select_option("#in-search-pattern_distance", "fixed")
    page.dispatch_event("#in-search-pattern_distance", "change")
    assert page.locator("#in-search-pattern_pitch").is_visible() and page.locator("#in-target_count").is_hidden()
    change(page, "#in-search-pattern_pitch", "24")
    page.click("[data-step=board]")
    page.check("#in-bounds-border")
    page.dispatch_event("#in-bounds-border", "change")
    assert page.locator("#in-bounds-border_width").is_visible()
    page.click("[data-step=run]")
    assert "Hexagonal" in page.inner_text("#runSummary") and "Randbereich 10 mm" in page.inner_text("#runSummary")
    assert page.locator("[data-w=layers]").is_hidden() and page.locator("[data-w=count]").is_hidden()  # layers are fixed
    page.click("#presets [data-preset=border]")
    assert page.input_value("#wn-border") == "78" and page.inner_text("#weightSum") == "Summe 100 %"
    change(page, "#in-search-time_limit_s", "4")
    page.click("#btnStart")
    page.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    assert "jeder Motor einzeln" in page.inner_text("#messages")
    assert "Tiefe im Randbereich" in page.inner_text("#metrics") and "(hat Vorrang)" in page.inner_text("#terms")
    page.wait_for_function("document.querySelector('#collisions').innerText.includes('Keine Kollisionen')")


def test_free_mode_is_folded_and_keeps_its_method(page):
    page.click("[data-step=mode]")
    assert not page.evaluate("document.querySelector('#moreModes').open")
    page.click("#moreModes summary")
    page.click("[data-mode=free]")
    page.click("[data-step=holes]")
    assert page.inner_text("#stepHolesLabel") == "Verteilung"
    assert page.locator("#f-free #in-target_count").is_visible()
    page.select_option("#freeMethod", "anneal_free")
    page.dispatch_event("#freeMethod", "change")
    assert page.evaluate("cfg.search.optimizer") == "anneal_free"
    page.click("[data-step=mode]")
    page.click("[data-mode=pattern]")
    page.click("[data-mode=free]")
    assert page.evaluate("cfg.search.optimizer") == "anneal_free"  # the mode remembers its method
    page.click("[data-step=run]")
    assert page.locator("[data-w=count]").is_visible() and page.locator("[data-w=layers]").is_hidden()
    assert page.locator("[data-w=border]").is_hidden()


def test_edge_goal_moves_freely_and_says_when_it_has_no_effect(page):
    page.click("[data-step=run]")
    assert page.locator("[data-w=border]").is_enabled() and "Randbereich" in page.inner_text("#wnote-border")
    page.click("[data-step=board]")
    page.check("#in-bounds-border")
    page.dispatch_event("#in-bounds-border", "change")
    page.click("[data-step=run]")
    assert page.inner_text("#wnote-border") == ""


def test_layer_goal_appears_when_the_layer_count_is_not_fixed(page):
    page.click("[data-step=run]")
    assert page.locator("[data-w-row=layers]").is_hidden() and page.locator("#presets [data-preset=layers]").count() == 0
    page.click("[data-step=basics]")
    page.uncheck("#in-stack-layers_fixed")
    page.dispatch_event("#in-stack-layers_fixed", "change")
    page.click("[data-step=run]")
    assert page.locator("[data-w-row=layers]").is_visible() and "so wenige wie nötig" in page.inner_text("#runSummary")
    page.click("#presets [data-preset=layers]")
    assert page.input_value("#wn-layers") == "60" and page.inner_text("#weightSum") == "Summe 100 %"


def test_result_shows_dots_edge_strip_and_tiling(page):
    page.click("[data-step=board]")
    page.check("#in-bounds-border")
    page.dispatch_event("#in-bounds-border", "change")
    page.click("[data-step=holes]")
    page.select_option("#in-search-pattern_count", "exact")
    page.dispatch_event("#in-search-pattern_count", "change")
    page.click("[data-step=run]")
    change(page, "#in-search-time_limit_s", "4")
    page.click("#btnStart")
    page.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    assert page.locator("#view .edgeStrip").count() == 1 and page.locator("#view .holeArea").count() == 1
    assert page.locator("#view circle[fill='none'][stroke='#e08a00']").count() == 0  # tight spots are dots, not rings
    # Tile the found block
    page.click("[data-result-view=tile]")
    page.wait_for_function("document.querySelector('#tileStatus').innerText.includes('Keine Kollisionen')")
    change(page, "#tileNx", "2")
    change(page, "#tileNy", "2")
    # The answer for 3 x 3 may still be on its way, only the newest one counts
    page.wait_for_function("tileState.response && tileState.response.placements.length === 4 * currentTile().units.length")
    count = page.evaluate("tileState.response.placements.length")
    assert "Platte" in page.inner_text("#tileStatus")
    with page.expect_download() as download:
        page.click("#tileDownloadTile")
    data = json.loads(open(download.value.path(), encoding="utf-8").read())
    assert data["format"] == "blindsight.holes" and data["tile"]["holes"]
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#tileApply")
    page.wait_for_function(f"lastGeo && lastGeo.units.length === {count}")
    assert page.locator("#resultMain").is_visible() and page.evaluate("cfg.target_count") == count


def test_pattern_with_individual_motors_cannot_be_tiled(page):
    page.set_input_files("#fileResult", result_file(GOOD))
    page.wait_for_selector("#resultBox:not([hidden])")
    page.click("[data-result-view=tile]")
    assert page.locator("#tileUnavailable").is_visible() and page.locator("#tileContent").is_hidden()
