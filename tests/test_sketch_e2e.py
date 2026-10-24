"""Ende zu Ende Test der Motor Skizze im Browser. Wird uebersprungen, wenn Playwright oder Chromium fehlt.

Die Ergebnisse werden unabhaengig vom Solver in Python nachgemessen (Laengen, Parallelitaet, Winkel)."""

import math
import os
import threading

import pytest

playwright = pytest.importorskip("playwright.sync_api")
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
    pg = browser.new_page(locale="de-DE", viewport={"width": 1600, "height": 1000})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    pg.goto(base_url)
    pg.wait_for_selector("#in-motor-width")
    pg.click("[data-tab=sketch]")
    pg.wait_for_function("__sk.sk.points.length >= 3 && __sk.res")
    yield pg
    pg.close()


def pts(pg):
    return pg.evaluate("__sk.sk.points")


def side(p, i):
    n = len(p)
    return p[(i + 1) % n][0] - p[i][0], p[(i + 1) % n][1] - p[i][1]


def screen(pg, mx, my):
    cx, cy, k, w, h = pg.evaluate("(() => { const S = __sk, c = document.querySelector('#skCanvas'); return [S.view.cx, S.view.cy, S.view.k, c.clientWidth, c.clientHeight]; })()")
    box = pg.locator("#skCanvas").bounding_box()
    return box["x"] + w / 2 + (mx - cx) / k, box["y"] + h / 2 - (my - cy) / k


def draw_trapezoid(pg):
    pg.click("#skDraw")
    for p in [(-14, -30), (6, -30), (2, -8), (-12, -6)]:
        pg.mouse.click(*screen(pg, *p))
    pg.keyboard.press("Enter")
    pg.wait_for_function("__sk.tool === null && __sk.sk.points[2][0] === 2")


def settle(pg):
    pg.wait_for_function("__sk.res && __sk.busy === 0 && !document.querySelector('#skInput:not([hidden])')")
    pg.wait_for_timeout(250)


def test_rod_is_drawn_at_the_origin_and_motor_rotates_about_it(page):
    rod = page.locator("#skRod")
    assert rod.count() == 1
    assert float(rod.get_attribute("r")) == pytest.approx(2.0) and float(rod.get_attribute("cx")) == 0 and float(rod.get_attribute("cy")) == 0
    page.fill("#skRot", "50")
    page.dispatch_event("#skRot", "input")
    assert "rotate(50)" in page.locator("#skCanvas g[opacity]").first.get_attribute("transform")
    # Die Stange bleibt beim Drehen stehen
    assert float(page.locator("#skRod").get_attribute("cx")) == 0
    assert page.locator("#skCanvas").inner_html().count("Stange") >= 1


def test_draw_polygon_set_length_parallel_and_angle(page):
    draw_trapezoid(page)
    p = pts(page)
    assert len(p) == 4
    # Laenge ueber die Tabelle
    page.fill("[data-sk-len='0']", "18")
    page.dispatch_event("[data-sk-len='0']", "change")
    settle(page)
    p = pts(page)
    assert math.hypot(*side(p, 0)) == pytest.approx(18.0, abs=1e-6)
    # Parallelitaet ueber die Tabelle
    page.select_option("[data-sk-par='0']", "2")
    settle(page)
    p = pts(page)
    a, b = side(p, 0), side(p, 2)
    assert abs(a[0] * b[1] - a[1] * b[0]) / (math.hypot(*a) * math.hypot(*b)) < 1e-7
    assert math.hypot(*side(p, 0)) == pytest.approx(18.0, abs=1e-6)
    # Winkel ueber die Werkzeugleiste und das Eingabefeld an der Skizze
    page.evaluate("skSelect([1], [])")
    page.click("[data-sk-add=angle]")
    page.fill("#skInput", "80")
    page.press("#skInput", "Enter")
    settle(page)
    p = pts(page)
    u, v = (p[0][0] - p[1][0], p[0][1] - p[1][1]), (p[2][0] - p[1][0], p[2][1] - p[1][1])
    ang = math.degrees(math.atan2(abs(u[0] * v[1] - u[1] * v[0]), u[0] * v[0] + u[1] * v[1]))
    assert ang == pytest.approx(80.0, abs=1e-5)
    # Alles zusammen steht in der Konfiguration, die an den Server geht
    cfg_cons = page.evaluate("cfg.motor.sketch.constraints.map(c => c.type)")
    assert cfg_cons == ["length", "parallel", "angle"]
    assert page.errors == []


def test_dragging_a_point_keeps_all_constraints(page):
    draw_trapezoid(page)
    page.fill("[data-sk-len='0']", "18")
    page.dispatch_event("[data-sk-len='0']", "change")
    page.select_option("[data-sk-par='0']", "2")
    settle(page)
    p = pts(page)
    x, y = screen(page, *p[2])
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 70, y - 50, steps=8)
    page.mouse.up()
    settle(page)
    p2 = pts(page)
    assert p2[2] != p[2]
    a, b = side(p2, 0), side(p2, 2)
    assert abs(a[0] * b[1] - a[1] * b[0]) / (math.hypot(*a) * math.hypot(*b)) < 1e-6
    assert math.hypot(*a) == pytest.approx(18.0, abs=1e-6)
    assert page.errors == []


def test_undo_redo(page):
    draw_trapezoid(page)
    page.fill("[data-sk-len='0']", "18")
    page.dispatch_event("[data-sk-len='0']", "change")
    settle(page)
    page.click("#skUndo")
    settle(page)
    p = pts(page)
    assert math.hypot(*side(p, 0)) != pytest.approx(18.0, abs=1e-3)
    assert page.evaluate("cfg.motor.sketch.constraints.length") == 0
    page.click("#skRedo")
    settle(page)
    assert math.hypot(*side(pts(page), 0)) == pytest.approx(18.0, abs=1e-6)


def test_conflict_is_shown_and_blocks_analysis(page):
    draw_trapezoid(page)
    page.fill("[data-sk-len='0']", "18")
    page.dispatch_event("[data-sk-len='0']", "change")
    settle(page)
    page.evaluate("skSelect([], [0, 1])")
    page.click("[data-sk-add=equal]")
    settle(page)
    page.fill("[data-sk-len='1']", "9")
    page.dispatch_event("[data-sk-len='1']", "change")
    settle(page)
    assert page.evaluate("__sk.res.state") == "conflict"
    assert "Widerspruch" in page.inner_text("#skStatus")
    assert page.locator(".skcons.conflict").count() >= 1
    page.wait_for_selector("#banner:not([hidden])")
    assert "widerspricht" in page.inner_text("#banner")


def test_insert_and_delete_point(page):
    page.evaluate("__sk.sk.points.length")
    n0 = page.evaluate("__sk.sk.points.length")
    p = pts(page)
    a, b = p[1], p[2]
    page.mouse.dblclick(*screen(page, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    page.wait_for_function(f"__sk.sk.points.length === {n0 + 1}")
    page.click("[data-sk-del='1']")
    page.wait_for_function(f"__sk.sk.points.length === {n0}")


def test_geometry_tab_shows_rod_and_sketch_note_and_disables_legacy_fields(page):
    draw_trapezoid(page)
    page.fill("[data-sk-len='0']", "18")
    page.dispatch_event("[data-sk-len='0']", "change")
    settle(page)
    page.click("[data-tab=geometry]")
    page.wait_for_selector("#sketchNote:not([hidden])")
    assert page.locator("#previewRod").count() == 1
    assert page.is_disabled("#in-motor-width") and page.is_disabled("#in-motor-gear_gap")
    page.click("#btnDropSketch")
    page.wait_for_selector("#sketchNote", state="hidden")
    assert not page.is_disabled("#in-motor-width")


def test_sketch_motor_runs_through_the_optimizer(page):
    draw_trapezoid(page)
    page.fill("[data-sk-len='0']", "14")
    page.dispatch_event("[data-sk-len='0']", "change")
    settle(page)
    page.click("[data-tab=geometry]")
    page.fill("#in-target_count", "6")
    page.dispatch_event("#in-target_count", "change")
    page.click("[data-tab=optim]")
    page.fill("#in-search-time_limit_s", "3")
    page.dispatch_event("#in-search-time_limit_s", "change")
    page.click("#btnStart")
    page.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    assert "6 von 6" in page.inner_text("#statusBox")
    assert "Keine Kollisionen" in page.inner_text("#collisions")
    assert page.errors == []


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def test_toolbar_constraints_parallel_equal_horizontal_fix(page):
    draw_trapezoid(page)
    page.evaluate("skSelect([], [0])")
    page.click("[data-sk-add=horizontal]")
    settle(page)
    page.evaluate("skSelect([], [0, 2])")
    page.click("[data-sk-add=parallel]")
    settle(page)
    page.evaluate("skSelect([], [1, 3])")
    page.click("[data-sk-add=equal]")
    settle(page)
    page.evaluate("skSelect([0], [])")
    fixed_at = pts(page)[0]
    page.click("[data-sk-add=fix]")
    settle(page)
    p = pts(page)
    assert abs(side(p, 0)[1]) < 1e-7
    assert abs(cross2(side(p, 0), side(p, 2))) < 1e-6 * math.hypot(*side(p, 0)) * math.hypot(*side(p, 2))
    assert math.hypot(*side(p, 1)) == pytest.approx(math.hypot(*side(p, 3)), abs=1e-6)
    assert p[0] == pytest.approx(fixed_at, abs=1e-6)
    # Gleiche Beziehung zweimal ist nicht moeglich
    page.evaluate("skSelect([], [0, 2])")
    page.click("[data-sk-add=parallel]")
    settle(page)
    assert "existiert bereits" in page.inner_text("#skStatus")
    # Fixierter Punkt bleibt beim Ziehen eines anderen Punktes stehen
    x, y = screen(page, *p[2])
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 50, y + 30, steps=6)
    page.mouse.up()
    settle(page)
    assert pts(page)[0] == pytest.approx(fixed_at, abs=1e-6)
    assert page.errors == []


def test_double_click_finishes_polygon(page):
    page.click("#skDraw")
    for p in [(-12, -30), (6, -30), (4, -8)]:
        page.mouse.click(*screen(page, *p))
    page.mouse.dblclick(*screen(page, -10, -8))
    page.wait_for_function("__sk.tool === null && __sk.sk.points.length === 4")
    assert len(pts(page)) == 4


def test_nonconvex_polygon_is_flagged_and_hull_repairs_it(page):
    page.click("#skDraw")
    for p in [(-14, -30), (8, -30), (-10, -16), (-14, -6)]:
        page.mouse.click(*screen(page, *p))
    page.keyboard.press("Enter")
    page.wait_for_function("__sk.tool === null && __sk.res")
    settle(page)
    assert page.evaluate("__sk.res.convex") is False
    assert "nicht konvex" in page.inner_text("#skStatus")
    page.wait_for_selector("#banner:not([hidden])")
    page.click("#skHull")
    page.wait_for_function("__sk.sk.points.length === 3 && __sk.res.convex")
    settle(page)
    page.wait_for_selector("#banner", state="hidden")


def test_distance_to_rod_dimension_is_measured_from_the_origin(page):
    draw_trapezoid(page)
    page.evaluate("skSelect([], [3])")
    page.click("[data-sk-add=dist_rod]")
    page.fill("#skInput", "7")
    page.press("#skInput", "Enter")
    settle(page)
    p = pts(page)
    d = side(p, 3)
    dist = abs(cross2(d, (-p[3][0], -p[3][1]))) / math.hypot(*d)
    assert dist == pytest.approx(7.0, abs=1e-6)
    assert page.evaluate("cfg.motor.sketch.constraints[0].type") == "dist_side"


def test_dragging_the_gear_changes_the_center_distance(page):
    before = page.evaluate("cfg.motor.center_distance")
    x, y = screen(page, -before, 0)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 30, y, steps=5)
    page.mouse.up()
    settle(page)
    after = page.evaluate("cfg.motor.center_distance")
    assert after > before
    assert float(page.locator("#skCdIn").input_value()) == pytest.approx(after, abs=1e-6)


def test_tables_work_in_millimetres(page):
    # The program works in mm only, there is no unit selection
    assert page.locator("#unitSel").count() == 0
    draw_trapezoid(page)
    assert "[mm]" in page.inner_text("#skSides")
    page.fill("[data-sk-len='0']", "15")
    page.dispatch_event("[data-sk-len='0']", "change")
    settle(page)
    assert math.hypot(*side(pts(page), 0)) == pytest.approx(15.0, abs=1e-6)


def test_svg_import_creates_a_sketch(page, tmp_path):
    f = tmp_path / "motor.svg"
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="30mm" viewBox="0 0 20 30"><path d="M0 0 L20 0 L20 20 L10 30 L0 20 Z"/></svg>')
    page.click("[data-tab=geometry]")
    page.set_input_files("#svgMotor", str(f))
    page.wait_for_function("cfg.motor.sketch && cfg.motor.sketch.points.length === 5")
    page.click("[data-tab=sketch]")
    page.wait_for_function("__sk.sk.points.length === 5 && __sk.attached")
    assert page.evaluate("__sk.res.convex") is True
    assert page.evaluate("__sk.res.errors.length") == 0
    page.wait_for_selector("#banner", state="hidden")
    assert page.errors == []


def test_from_rectangle_resets_to_dimensioned_rectangle(page):
    draw_trapezoid(page)
    page.click("#skFromMotor")
    page.wait_for_function("__sk.sk.points.length === 4 && __sk.sk.constraints.length === 6")
    settle(page)
    p = pts(page)
    assert math.hypot(*side(p, 0)) == pytest.approx(page.evaluate("cfg.motor.width"), abs=1e-6)
    for i in range(4):
        a, b = side(p, i), side(p, (i + 1) % 4)
        assert abs(a[0] * b[0] + a[1] * b[1]) < 1e-6 * math.hypot(*a) * math.hypot(*b)


def test_example_with_sketch_loads_into_the_editor(page):
    page.select_option("#exampleSel", "sketch_trapezoid_motor")
    page.wait_for_function("cfg.motor.sketch && cfg.motor.sketch.constraints.length === 6")
    page.click("[data-tab=sketch]")
    page.wait_for_function("__sk.attached && __sk.sk.constraints.length === 6 && __sk.res.ok")
    assert page.evaluate("__sk.res.convex") is True
    assert page.locator(".skcons").count() == 6
    assert "Abstand linke Flanke zur Stange" in page.inner_text("#skCons")
    p = pts(page)
    assert math.hypot(*side(p, 0)) == pytest.approx(16.0, abs=1e-6)
    assert page.errors == []
