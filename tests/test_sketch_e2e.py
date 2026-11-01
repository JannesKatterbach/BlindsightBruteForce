"""End to end test of the Onshape like motor sketch in the browser. Skipped when Playwright or Chromium is missing.

The results are measured again in Python independently of the solver (lengths, parallelism, relations)."""

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
    pg.wait_for_selector("#in-rod-diameter")
    pg.click("[data-step=motor]")
    pg.click("[data-motor-view=sketch]")
    pg.wait_for_function("__sk.res && __sk.sk.entities.length && __sk.busy === 0")
    # A view with free space right of the motor for drawing
    pg.evaluate("__sk.view = {cx: 8, cy: -12, k: 0.05}; skRender()")
    yield pg
    assert pg.errors == []
    pg.close()


def screen(pg, mx, my):
    cx, cy, k, w, h = pg.evaluate("(() => { const S = __sk, c = document.querySelector('#skCanvas'); return [S.view.cx, S.view.cy, S.view.k, c.clientWidth, c.clientHeight]; })()")
    box = pg.locator("#skCanvas").bounding_box()
    return box["x"] + w / 2 + (mx - cx) / k, box["y"] + h / 2 - (my - cy) / k


def click(pg, x, y):
    pg.mouse.click(*screen(pg, x, y))


def settle(pg):
    pg.wait_for_function("__sk.res && __sk.busy === 0")


def sk(pg):
    return pg.evaluate("__sk.sk")


def ends(s, k):
    a, b = s["entities"][k]["points"]
    return s["points"][a], s["points"][b]


def new_constraints(before, after, types=None):
    return [c for c in after["constraints"][len(before["constraints"]):] if types is None or c["type"] in types]


def draw_rect(pg, a, b):
    before = sk(pg)
    pg.keyboard.press("r")
    click(pg, *a)
    click(pg, *b)
    settle(pg)
    return before


def draw_line(pg, a, b):
    pg.keyboard.press("l")
    click(pg, *a)
    click(pg, *b)
    settle(pg)
    pg.keyboard.press("Escape")
    pg.keyboard.press("Escape")
    return len(sk(pg)["entities"]) - 1


def test_toolbar_and_preview(page):
    assert page.locator("#skToolbar button svg").count() >= 20
    assert page.evaluate("[__sk.res.state, __sk.attached]") == ["full", False]
    assert "Voll bestimmt" in page.inner_text("#skStatus") and "Achsabstand 5 mm" in page.inner_text("#skStatus")
    assert page.get_attribute("[data-sk-tool=line]", "title") == "Linie (L)"


def test_rectangle_tool_draws_lines_with_relations(page):
    before = draw_rect(page, (12, -25), (24, -12))
    after = sk(page)
    assert len(after["entities"]) == len(before["entities"]) + 4
    added = new_constraints(before, after)
    assert sorted(c["type"] for c in added) == ["coincident"] * 4 + ["horizontal"] * 2 + ["vertical"] * 2
    assert page.evaluate("__sk.attached && cfg.motor.sketch.entities.length") == len(after["entities"])
    # The housing hull now covers the new rectangle
    assert page.evaluate("__sk.res.profile.bbox.xmax") == pytest.approx(24, abs=0.01)


def test_line_chain_closes_on_the_start_point(page):
    before = sk(page)
    page.keyboard.press("l")
    for p in [(12, -25), (26, -25), (20, -12), (12, -25)]:
        click(page, *p)
        settle(page)
    after = sk(page)
    assert len(after["entities"]) == len(before["entities"]) + 3
    added = new_constraints(before, after)
    assert sum(c["type"] == "coincident" for c in added) == 3
    assert any(c["type"] == "horizontal" for c in added)  # the first line was drawn horizontally
    assert page.evaluate("__sk.draft") is None
    first = len(before["entities"])
    assert ends(after, first)[0] == pytest.approx(ends(after, first + 2)[1], abs=1e-6)


def test_relations_by_selection_and_with_an_armed_tool(page):
    a = draw_line(page, (12, -26), (25, -22))
    b = draw_line(page, (12, -16), (24, -11))
    page.keyboard.press("s")
    click(page, 18.5, -24)  # middle of line a
    click(page, 18, -13.5)  # middle of line b
    assert page.evaluate("[...__sk.sel]") == [f"e{a}", f"e{b}"]
    page.click("[data-sk-rel=parallel]")
    settle(page)
    s = sk(page)
    (p, q), (r, t) = ends(s, a), ends(s, b)
    assert abs((q[0] - p[0]) * (t[1] - r[1]) - (q[1] - p[1]) * (t[0] - r[0])) < 1e-6
    # Armed tool. Click the relation first, then the element
    page.click("[data-sk-rel=horizontal]")
    assert page.evaluate("__sk.tool") == "horizontal"
    p, q = ends(sk(page), a)
    click(page, (p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    settle(page)
    s = sk(page)
    for k in (a, b):  # line b follows through parallel
        p, q = ends(s, k)
        assert abs(p[1] - q[1]) < 1e-6


def test_dimension_tool_sets_a_length_and_double_click_edits_it(page):
    k = draw_line(page, (12, -26), (25, -22))
    page.keyboard.press("d")
    p, q = ends(sk(page), k)
    click(page, (p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    click(page, 18, -29)
    page.wait_for_selector("#skInput:not([hidden])")
    page.fill("#skInput", "15")
    page.keyboard.press("Enter")
    settle(page)
    p, q = ends(sk(page), k)
    assert math.dist(p, q) == pytest.approx(15, abs=1e-5)
    index = len(sk(page)["constraints"]) - 1
    box = page.locator(f"[data-sk-dim='{index}']").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.click(x, y)
    page.mouse.click(x, y)
    page.wait_for_selector("#skInput:not([hidden])")
    page.fill("#skInput", "18")
    page.keyboard.press("Enter")
    settle(page)
    p, q = ends(sk(page), k)
    assert math.dist(p, q) == pytest.approx(18, abs=1e-5)


def test_dragging_a_corner_keeps_the_rectangle(page):
    before = draw_rect(page, (12, -25), (24, -12))
    first = len(before["entities"])
    page.keyboard.press("s")
    corner = sk(page)["points"][sk(page)["entities"][first + 1]["points"][1]]  # top right corner
    x, y = screen(page, *corner)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 40, y - 30, steps=6)
    page.mouse.up()
    settle(page)
    s = sk(page)
    for k in (first, first + 2):
        p, q = ends(s, k)
        assert abs(p[1] - q[1]) < 1e-6
    for k in (first + 1, first + 3):
        p, q = ends(s, k)
        assert abs(p[0] - q[0]) < 1e-6
    assert s["points"][s["entities"][first + 1]["points"][1]][0] > corner[0] + 1


def test_delete_undo_and_redo(page):
    before = draw_rect(page, (12, -25), (24, -12))
    n = len(sk(page)["entities"])
    page.keyboard.press("s")
    click(page, 18, -25)  # bottom line
    page.keyboard.press("Delete")
    settle(page)
    after = sk(page)
    assert len(after["entities"]) == n - 1
    assert len(after["constraints"]) == len(before["constraints"]) + 8 - 3  # two corners and its horizontal are gone
    page.keyboard.press("Control+z")
    settle(page)
    assert len(sk(page)["entities"]) == n
    page.keyboard.press("Control+y")
    settle(page)
    assert len(sk(page)["entities"]) == n - 1


def test_construction_does_not_count_for_the_housing(page):
    page.keyboard.press("c")
    click(page, 20, -15)
    click(page, 24, -15)
    settle(page)
    k = len(sk(page)["entities"]) - 1
    assert page.evaluate("__sk.res.profile.bbox.xmax") == pytest.approx(24, abs=0.3)
    page.keyboard.press("s")
    click(page, 24, -15)
    page.keyboard.press("q")
    settle(page)
    assert sk(page)["entities"][k]["construction"] is True
    assert page.evaluate("__sk.res.profile.bbox.xmax") == pytest.approx(1.0, abs=1e-6)
    assert page.locator(f"#skCanvas circle.construction[data-sk-ref='e{k}']").count() == 1


def test_circle_arc_and_diameter(page):
    page.keyboard.press("c")
    click(page, 20, -15)
    click(page, 23, -15)
    settle(page)
    k = len(sk(page)["entities"]) - 1
    page.keyboard.press("d")
    click(page, 23, -15)
    click(page, 27, -10)
    page.wait_for_selector("#skInput:not([hidden])")
    page.fill("#skInput", "10")
    page.keyboard.press("Enter")
    settle(page)
    assert sk(page)["entities"][k]["radius"] == pytest.approx(5, abs=1e-5)
    assert sk(page)["constraints"][-1]["type"] == "diameter"
    page.keyboard.press("a")
    for p in [(14, -26), (18, -26), (14, -22)]:
        click(page, *p)
    settle(page)
    arc = sk(page)["entities"][-1]
    assert arc["type"] == "arc"
    c, s, e = (sk(page)["points"][i] for i in arc["points"])
    assert math.dist(c, s) == pytest.approx(math.dist(c, e), abs=1e-6)


def test_gear_dimensions_drive_the_motor(page):
    page.keyboard.press("f")  # fit, the label of the centre distance lies above the motor
    cons = sk(page)["constraints"]
    index = next(i for i, c in enumerate(cons) if c["type"] == "distance" and "o" in c["refs"])
    box = page.locator(f"[data-sk-dim='{index}']").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.click(x, y)
    page.mouse.click(x, y)
    page.wait_for_selector("#skInput:not([hidden])")
    page.fill("#skInput", "7")
    page.keyboard.press("Enter")
    settle(page)
    page.wait_for_function("cfg.motor.center_distance > 6.99 && cfg.motor.sketch")
    assert "Achsabstand 7 mm" in page.inner_text("#skStatus")
    page.click("[data-motor-view=dims]")
    page.wait_for_function("document.querySelector('#in-motor-center_distance').value === '7'")  # written debounced
    assert page.locator("#in-motor-center_distance").is_disabled()
    page.click("[data-motor-view=sketch]")
    page.keyboard.press("g")
    click(page, -20, 10)
    assert "schon ein Zahnrad" in page.inner_text("#skStatus")


def test_constraint_list_and_language(page):
    page.click("#skListToggle")
    rows = page.locator("#skCons .skcons")
    assert rows.count() == len(sk(page)["constraints"])
    n = rows.count()
    page.click("#skCons [data-sk-cons-del='0']")
    settle(page)
    assert page.locator("#skCons .skcons").count() == n - 1
    page.select_option("#langSel", "en")
    page.wait_for_function("document.querySelector('[data-sk-tool=line]').title === 'Line (L)'")
    page.wait_for_function("document.querySelector('#skStatus').innerText.includes('Under defined')")


def test_sketch_motor_is_used_by_the_optimization(page):
    draw_rect(page, (8, -26), (14, -18))  # widens the housing hull
    page.wait_for_function("cfg.motor.width > 20")
    page.click("[data-step=run]")
    page.fill("#in-search-time_limit_s", "4")
    page.dispatch_event("#in-search-time_limit_s", "change")
    page.click("#btnStart")
    page.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    page.wait_for_function("document.querySelector('#collisions').innerText.includes('Keine Kollisionen')")
