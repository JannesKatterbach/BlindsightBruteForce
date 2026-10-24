"""End to end test of the UI with Playwright. Skipped when Playwright or Chromium is missing."""

import os
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from blindsight.web.server import serve  # noqa: E402

CHROMIUM = os.environ.get("BLINDSIGHT_CHROMIUM", "/opt/pw-browsers/chromium")


@pytest.fixture(scope="module")
def base_url():
    server = serve("127.0.0.1", 0, open_browser=False)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=CHROMIUM) if os.path.exists(CHROMIUM) else p.chromium.launch()
        except Exception as exc:  # no browser installed
            pytest.skip(f"Chromium nicht verfuegbar. {exc}")
        yield b
        b.close()


def test_full_flow(browser, base_url):
    pg = browser.new_page(locale="de-DE", viewport={"width": 1400, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(base_url)
    pg.wait_for_selector("#in-motor-width")
    pg.select_option("#exampleSel", "small_hex")
    pg.wait_for_function("document.querySelector('#in-target_count').value === '7'")
    # field errors are shown at the field
    pg.fill("#in-rod-diameter", "-3")
    pg.dispatch_event("#in-rod-diameter", "change")
    pg.wait_for_selector("#in-rod-diameter.err")
    pg.fill("#in-rod-diameter", "4")
    pg.dispatch_event("#in-rod-diameter", "change")
    pg.wait_for_selector("#in-rod-diameter:not(.err)")
    errors.clear()  # the deliberately invalid input causes a 400 response in the browser log
    # All lengths in mm, build area from the origin at the bottom left
    assert pg.locator("#unitSel").count() == 0
    assert "[mm]" in pg.inner_text("[data-label-for='rod.diameter']")
    assert pg.locator("#in-bounds-xmin").count() == 0 and pg.locator("#in-bounds-width").count() == 1
    # Optimierung
    pg.click("[data-tab=optim]")
    # Time buffer for full test runs. Once the target count is reached, stagnation ends the run early
    pg.fill("#in-search-time_limit_s", "10")
    pg.dispatch_event("#in-search-time_limit_s", "change")
    pg.click("#btnStart")
    pg.wait_for_selector("#resultBox:not([hidden])", timeout=40000)
    assert "7 von 7" in pg.inner_text("#statusBox")
    for view in ("plane", "section", "iso", "top"):
        pg.select_option("#viewSel", view)
        assert pg.locator("#view").inner_html() != ""
    # Editing and export
    pg.check("#optEdit")
    # Regression. Dragging a rod onto another must report collisions (helper lines must not catch clicks)
    def center(unit):
        bb = pg.locator(f"#view circle[data-unit='{unit}']").first.bounding_box()
        return bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
    (x0, y0), (x1, y1) = center(0), center(1)
    pg.mouse.move(x0, y0)
    pg.mouse.down()
    pg.mouse.move(x1 + 2, y1, steps=8)
    pg.mouse.up()
    pg.wait_for_function("document.querySelector('#statusBox').innerText.includes('Manuell bearbeitet')", timeout=10000)
    assert "Kein" not in pg.inner_text("#collisions")[:6]
    pg.click("#edReset")
    pg.wait_for_function("!document.querySelector('#statusBox').innerText.includes('Manuell bearbeitet')", timeout=10000)
    with pg.expect_download() as dl:
        pg.click("#btnExport")
    assert dl.value.suggested_filename.endswith(".svg")
    assert errors == []
    pg.close()
