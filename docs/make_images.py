"""Draws the labelled figures of docs/ERKLAERUNG.md (SVG, German labels).

Run from the repository root with  PYTHONPATH=src python docs/make_images.py
(--variant-only skips the optimizer runs and draws only the schematic figures)
The figures 1 to 3, 5 and 6 are schematic but use the default values of the project. The figures 4, 7 and 8
come from real results of the optimizers with the default values (computed when the script runs, about 30 s).
Every figure has a white background so that it stays readable in dark themes.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from blindsight.config import Project
from blindsight.export import build_geometry
from blindsight.model import Model
from blindsight.optimizers import run_optimizer
from blindsight.tiling import tile_project

OUT = Path(__file__).resolve().parent / "images"
INK, MUTED, LIGHT, RED, BLUE = "#1d2330", "#5b6475", "#eef0f4", "#c62828", "#1565c0"
PLATE, PLATE_G0, ROD, GEAR = "#c3c8d1", "#8f96a3", "#2b2f36", "#e8a33d"
PLANE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1"]  # like the SVG export, G1 first
FONT = "DejaVu Sans, Arial, Helvetica, sans-serif"


def plane_color(plane: int) -> str:
    return PLANE_COLORS[(plane - 1) % len(PLANE_COLORS)]


def num(value: float, digits: int = 1) -> str:
    """Number in German notation (comma), without trailing zeros and without -0."""
    value = round(value, digits) + 0.0
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


class Svg:
    """Minimal SVG writer in pixels with dimension lines and labels."""

    def __init__(self, width: float, height: float, title: str):
        self.width, self.height, self.title, self.items = width, height, title, []

    @staticmethod
    def _attrs(style: dict) -> str:
        return " ".join(f'{k.rstrip("_").replace("_", "-")}="{v}"' for k, v in style.items() if v is not None)

    def add(self, text: str) -> None:
        self.items.append(text)

    def rect(self, x, y, w, h, **style):
        self.add(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" {self._attrs(style)}/>')

    def line(self, x1, y1, x2, y2, **style):
        style.setdefault("stroke", INK)
        self.add(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {self._attrs(style)}/>')

    def circle(self, cx, cy, r, **style):
        self.add(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" {self._attrs(style)}/>')

    def poly(self, points, **style):
        pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.add(f'<polygon points="{pts}" {self._attrs(style)}/>')

    def text(self, x, y, label, size=13, anchor="start", weight=None, fill=INK, italic=False):
        style = {"font_size": size, "text_anchor": anchor, "font_weight": weight, "fill": fill,
                 "font_style": "italic" if italic else None}
        for i, part in enumerate(label.split("\n")):
            self.add(f'<text x="{x:.2f}" y="{y + i * size * 1.25:.2f}" {self._attrs(style)}>{escape(part)}</text>')

    def arrow(self, x1, y1, x2, y2, both=True, color=INK, width=1.0):
        self.line(x1, y1, x2, y2, stroke=color, stroke_width=width, marker_start="url(#arrow)" if both else None,
                  marker_end="url(#arrow)")

    def dim(self, x1, y1, x2, y2, label, side=1, size=12):
        """Dimension line with arrows at both ends and the label beside its middle (side 1 above or right)."""
        self.arrow(x1, y1, x2, y2)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lines = label.count("\n") + 1
        if abs(x2 - x1) >= abs(y2 - y1):
            self.text(mx, my - 6 - (lines - 1) * size * 1.25 if side > 0 else my + 15, label, size=size, anchor="middle")
        else:
            self.text(mx + (7 if side > 0 else -7), my + 4 - (lines - 1) * size * 0.62, label, size=size,
                      anchor="start" if side > 0 else "end")

    def leader(self, x1, y1, x2, y2, label, size=12):
        """Thin line from a point of the drawing to its label on the right."""
        self.circle(x1, y1, 2.2, fill=INK)
        self.line(x1, y1, x2, y2, stroke=MUTED, stroke_width=0.8)
        self.text(x2 + 4, y2 + 4, label, size=size)

    def save(self, name: str) -> None:
        defs = ('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" fill="{INK}"/></marker></defs>')
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" height="{self.height:.0f}" '
                f'viewBox="0 0 {self.width:.0f} {self.height:.0f}" font-family="{FONT}">')
        body = [head, f"<title>{escape(self.title)}</title>", defs, '<rect width="100%" height="100%" fill="#ffffff"/>',
                *self.items, "</svg>"]
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text("\n".join(body) + "\n", encoding="utf-8")
        print("written", OUT / name)


def side_unit(svg: Svg, model: Model, plane: int, rx: float, Z, s: float, extended: bool = False) -> None:
    """Side view (looking along y) of one unit. Housing behind the gear, gear as a circle, the rod."""
    proj, m = model.project, model.project.motor
    rod = model.rod_geometry(plane)
    col = plane_color(plane)
    gx = rx - m.center_distance * s
    z_low = rod.z_mount if m.mount == "top" else rod.z_mount - m.height
    svg.rect(gx - m.width / 2 * s, Z(z_low + m.height), m.width * s, m.height * s, fill=col, fill_opacity=0.25,
             stroke=col, stroke_width=1.2)
    svg.circle(gx, Z(rod.z_axis), m.gear_diameter / 2 * s, fill=col, fill_opacity=0.85, stroke=INK, stroke_width=0.8)
    svg.circle(gx, Z(rod.z_axis), 1.6, fill="#ffffff")
    rw = proj.rod.diameter * s
    tip, bottom = (rod.tip_extended, rod.bottom_extended) if extended else (rod.tip_retracted, rod.bottom_retracted)
    svg.rect(rx - rw / 2, Z(tip), rw, (tip - bottom) * s, fill=ROD)


def plates(svg: Svg, model: Model, Z, s: float, x0: float, x1: float, rods: list[float], count: int | None = None) -> None:
    """Plates of the stack with a through hole at every rod and the layer names on the left."""
    hole = model.hole_r * s
    for p in model.stack.planes[:count]:
        cuts = [x0] + [v for r in sorted(rods) for v in (r - hole, r + hole)] + [x1]
        for a, b in zip(cuts[::2], cuts[1::2]):
            svg.rect(a, Z(p.z_top), b - a, (p.z_top - p.z_bottom) * s, fill=PLATE_G0 if p.index == 0 else PLATE,
                     stroke=INK, stroke_width=0.6)
        svg.text(x0 - 10, Z(p.z_top) + 10, p.name, size=15, anchor="end", weight="bold")


# -- Figure 1. Side section of the stack -----------------------------------------------------------------
def figure_stack(model: Model) -> None:
    proj = model.project
    s, zmax, top = 3.0, 60.0, 30
    Z = lambda z: top + (zmax - z) * s  # noqa: E731
    svg = Svg(1080, top + (zmax + 125) * s + 30, "Aufbau im Seitenschnitt")
    x0, x1 = 70, 640
    rods = [190, 360, 530]  # schematic x positions of three units (pulled apart)
    plates(svg, model, Z, s, x0, x1, rods)
    for i, rx in enumerate(rods):
        side_unit(svg, model, i + 1, rx, Z, s)
        rod = model.rod_geometry(i + 1)
        rw = proj.rod.diameter * s
        svg.rect(rx - rw / 2, Z(rod.tip_extended), rw, (rod.tip_extended - rod.tip_retracted) * s, fill="none",
                 stroke=ROD, stroke_width=1, stroke_dasharray="4 3")
        svg.text(rx, Z(rod.bottom_retracted) + 16, f"Stange mit Motor auf G{i + 1}\n{num(rod.length)} mm lang", size=12, anchor="middle")
    g1 = model.stack.planes[1]
    svg.dim(x0 + 22, Z(0), x0 + 22, Z(g1.z_top), f"{num(proj.stack.uniform_spacing)} mm", side=1)
    svg.dim(rods[0] - 40, Z(0), rods[0] - 40, Z(proj.rod.stroke), f"Hub\n{num(proj.rod.stroke)} mm", side=-1)
    # Labels on the right, anchored at the rightmost unit (G3)
    lx, rx = 690, rods[2]
    rod3 = model.rod_geometry(3)
    m = proj.motor
    gx = rx - m.center_distance * s
    svg.leader(rx, Z(32), lx, Z(36), "ausgefahren (gestrichelt). Jede Stange erreicht\ndenselben Hub über G0, egal auf welcher Ebene\nihr Motor sitzt (Maximaler Hub über G0)")
    svg.leader(x1 - 3, Z(-3), lx, Z(4), f"G0, die Lochplatte oben, Dicke {num(proj.stack.g0_thickness)} mm.\nIhre Oberseite ist z = 0, nach unten wird z negativ")
    svg.leader(x1 - 3, Z(g1.z_top - 0.8), lx, Z(-17), f"G1 bis G{proj.stack.n_motor_planes}, die Motorebenen, Dicke {num(proj.stack.thickness)} mm,\nje {num(proj.stack.uniform_spacing)} mm Abstand (Einheitlicher Ebenenabstand)")
    svg.leader(rx + model.hole_r * s, Z(-40.8), lx, Z(-37), f"Durchgangsloch ⌀ {num(2 * model.hole_r)} mm in jeder Ebene, durch die\neine Stange läuft (Stange {num(proj.rod.diameter)} mm + 2 x {num(proj.rod.hole_clearance)} mm Lochspiel)")
    svg.leader(gx + m.width / 2 * s - 6, Z(rod3.z_mount + m.height) + 3, lx, Z(-52), "Motorgehäuse, steht auf seiner Ebene\n(Montage. Motor steht auf der Ebene)")
    svg.leader(gx + 4, Z(rod3.z_axis) + 5, lx, Z(-67), f"Zahnrad ⌀ {num(m.gear_diameter)} mm auf der Motorwelle, {num(m.axis_height)} mm\nüber der Ebene. Es greift ins Gewinde und schiebt\ndie Stange auf und ab")
    svg.leader(rx + 6, Z(-95), lx, Z(-92), "Gewindestange eingefahren, die Spitze bündig mit\nG0. Sie hängt durch alle Ebenen darunter und\nbraucht dort überall ein Loch")
    svg.text(lx, Z(-112), "Schematisch. z ist maßstäblich mit den Standardwerten,\ndie drei Einheiten sind in x auseinandergezogen.", size=11, fill=MUTED, italic=True)
    svg.save("01_aufbau_seitenschnitt.svg")


# -- Figure 2. Motor in the rod frame (top view) ---------------------------------------------------------
def figure_motor(model: Model) -> None:
    m, rod = model.project.motor, model.project.rod
    s = 13.0
    ox, oy = 330, 120  # pixel position of the rod axis
    X = lambda x: ox + x * s  # noqa: E731
    Y = lambda y: oy - y * s  # noqa: E731
    cx = m.shaft_x - m.center_distance  # housing centre in x
    hx0, hx1 = cx - m.width / 2, cx + m.width / 2
    hy1 = -m.gear_width / 2 - m.gear_gap
    hy0 = hy1 - m.depth
    bottom = Y(hy0) + 60  # room for the width dimension below the housing
    svg = Svg(940, bottom + 30, "Motor im Stangenrahmen, Draufsicht")
    gx0, gx1 = -m.center_distance - m.gear_diameter / 2, -m.center_distance + m.gear_diameter / 2
    gy0, gy1 = -m.gear_width / 2, m.gear_width / 2
    svg.line(X(-17), Y(0), X(10), Y(0), stroke=MUTED, stroke_width=0.8, stroke_dasharray="5 4")
    svg.line(X(0), Y(6), X(0), Y(hy0 - 4), stroke=MUTED, stroke_width=0.8, stroke_dasharray="5 4")
    svg.text(X(10) + 4, Y(0) + 4, "x", size=13, fill=MUTED)
    svg.text(X(0) + 5, Y(6), "y", size=13, fill=MUTED)
    col = plane_color(1)
    svg.rect(X(hx0), Y(hy1), m.width * s, m.depth * s, fill=col, fill_opacity=0.18, stroke=col, stroke_width=1.6)
    svg.text(X(cx), Y((hy0 + hy1) / 2), "Motorgehäuse", size=14, anchor="middle", weight="bold")
    svg.text(X(cx), Y((hy0 + hy1) / 2) + 18, f"Höhe (z) {num(m.height)} mm", size=12, anchor="middle")
    svg.line(X(-m.center_distance), Y(hy1), X(-m.center_distance), Y(gy0), stroke=INK, stroke_width=2.5)  # shaft
    svg.rect(X(gx0), Y(gy1), m.gear_diameter * s, m.gear_width * s, fill=GEAR, stroke=INK, stroke_width=1)
    svg.text(X(-m.center_distance), Y(0) + 4, "Zahnrad", size=11, anchor="middle")
    svg.circle(X(0), Y(0), model.hole_r * s, fill="none", stroke=INK, stroke_width=1, stroke_dasharray="4 3")
    svg.circle(X(0), Y(0), rod.diameter / 2 * s, fill=ROD)
    # Dimensions with the labels of the motor fields
    svg.dim(X(hx0), Y(hy0) + 24, X(hx1), Y(hy0) + 24, f"Breite (x) {num(m.width)} mm", side=-1)
    svg.dim(X(hx0) - 24, Y(hy1), X(hx0) - 24, Y(hy0), f"Tiefe (y,\nWellenrichtung)\n{num(m.depth)} mm", side=-1)
    svg.dim(X(gx0), Y(gy1) - 20, X(gx1), Y(gy1) - 20, f"Zahnrad Durchmesser {num(m.gear_diameter)} mm", side=1)
    svg.dim(X(-m.center_distance), Y(gy1) - 62, X(0), Y(gy1) - 62, f"Achsabstand Zahnrad zu Stange {num(m.center_distance)} mm", side=1)
    for x in (-m.center_distance, 0):
        svg.line(X(x), Y(gy1) - 62, X(x), Y(0), stroke=MUTED, stroke_width=0.6, stroke_dasharray="2 2")
    svg.dim(X(gx0) - 16, Y(gy1), X(gx0) - 16, Y(gy0), f"Zahnrad Breite\n{num(m.gear_width)} mm", side=-1)
    # Motor angle, an arc right below the rod
    r = 4.2 * s
    a0, a1 = math.radians(-75), math.radians(-15)  # counter clockwise like the motor angle
    p0 = (X(0) + r * math.cos(a0), Y(0) - r * math.sin(a0))
    p1 = (X(0) + r * math.cos(a1), Y(0) - r * math.sin(a1))
    svg.add(f'<path d="M{p0[0]:.1f},{p0[1]:.1f} A{r:.1f},{r:.1f} 0 0 0 {p1[0]:.1f},{p1[1]:.1f}" fill="none" stroke="{RED}" '
            'stroke-width="1.4" marker-end="url(#arrow)"/>')
    svg.text(X(3.6), Y(-4.8), "Motorwinkel", size=12, fill=RED)
    # Labels on the right
    lx = 560
    svg.leader(X(0) + model.hole_r * s * 0.72, Y(0) - model.hole_r * s * 0.72, lx, Y(5.5), f"Durchgangsloch ⌀ {num(2 * model.hole_r)} mm (gestrichelt),\nStange + 2 x Radiales Lochspiel")
    svg.leader(X(0) + 6, Y(0) + 2, lx, Y(1), f"Gewindestange ⌀ {num(rod.diameter)} mm im Ursprung (0, 0)\ndes Motors. Um ihre Achse dreht der ganze\nMotor (Motorwinkel)")
    svg.leader(X(-m.center_distance) + 2, Y(hy1 + m.gear_gap / 2), lx, Y(-6.5), f"Motorwelle in y Richtung. Zwischen Gehäuse\nund Zahnrad {num(m.gear_gap)} mm (Abstand Gehäuse zu Zahnrad)")
    svg.leader(X(hx1) - 2, Y(hy1) + 2, lx, Y(-11.5), f"Ecke des Gehäuses nahe der Stange. Es muss\n{num(m.own_clearance)} mm Abstand zur eigenen Stange halten\n(Eigenabstand Gehäuse zur Stange)")
    svg.text(lx, Y(-18), "Das Zahnrad ist ein Quader (Durchmesser x Breite).\nZähne gibt es im Modell nicht, der Eingriff ins\n"
                         "Gewinde steckt nur im Achsabstand. Er ist so\ngewählt, dass Zahnrad und Stange sich berühren\n"
                         f"({num(m.gear_diameter / 2)} mm Zahnradradius + {num(rod.diameter / 2)} mm Stangenradius).", size=12)
    svg.text(30, bottom + 10, "Maßstäblich mit den Standardwerten (N20 mit Encoder). Gezeigt ist der Motorwinkel 0 Grad, das Zahnrad liegt dann in -x der Stange, "
                      "das Gehäuse in -y.", size=11, fill=MUTED, italic=True)
    svg.save("02_motor_draufsicht.svg")


# -- Figure 3. Rod length of the G1 unit, retracted and extended -------------------------------------------
def figure_rod_length(model: Model) -> None:
    proj = model.project
    rod = model.rod_geometry(1)
    s, zmax, top = 3.2, 58.0, 40
    Z = lambda z: top + (zmax - z) * s  # noqa: E731
    svg = Svg(1060, top + (zmax + 82) * s + 90, "Stangenlänge eingefahren und ausgefahren")
    columns = [("eingefahren", 300, False), ("ausgefahren", 720, True)]
    for title, cx, extended in columns:
        svg.text(cx, 24, title, size=16, anchor="middle", weight="bold")
        plates(svg, model, Z, s, cx - 120, cx + 90, [cx], count=3)
        side_unit(svg, model, 1, cx, Z, s, extended=extended)
        svg.line(cx - 112, Z(rod.z_axis), cx + 84, Z(rod.z_axis), stroke=RED, stroke_width=0.9, stroke_dasharray="5 3")
        tip, bottom = (rod.tip_extended, rod.bottom_extended) if extended else (rod.tip_retracted, rod.bottom_retracted)
        svg.text(cx + 10, Z(bottom) + 16, f"unteres Ende z = {num(bottom)}", size=12)
        svg.text(cx + 10, Z(tip) - 6, f"Spitze z = {num(tip)}", size=12)
    cx = columns[0][1]
    svg.dim(cx + 105, Z(rod.z_axis), cx + 105, Z(rod.tip_retracted),
            f"{num(rod.engage_above_actual)} mm Gewinde über der\nZahnradachse (gefordert\nmindestens {num(proj.rod.engage_above)} mm)", side=1)
    svg.dim(cx - 150, Z(rod.tip_retracted), cx - 150, Z(rod.bottom_retracted), f"Länge\n{num(rod.length)} mm", side=-1)
    cx = columns[1][1]
    svg.dim(cx + 105, Z(rod.z_axis), cx + 105, Z(rod.bottom_extended),
            f"{num(proj.rod.engage_below)} mm Gewinde unter der\nZahnradachse + {num(proj.rod.length_tolerance)} mm\nLängenzuschlag", side=1)
    svg.dim(cx + 105, Z(0), cx + 105, Z(rod.tip_extended), f"Hub {num(proj.rod.stroke)} mm über G0", side=1)
    svg.text(510, Z(-30), f"rot gestrichelt die Zahnradachse\nz = {num(rod.z_axis)} (Ebene G1 bei {num(rod.z_mount)}\n+ Achshöhe {num(proj.motor.axis_height)})",
             size=12, anchor="middle", fill=RED)
    fy = Z(-82) + 34
    svg.text(40, fy, "So rechnet das Programm die Länge (Motor auf G1, Standardwerte)", size=13, weight="bold")
    svg.text(40, fy + 20, f"unteres Ende ausgefahren = Zahnradachse - Gewinde unter der Achse - Längenzuschlag = "
                          f"{num(rod.z_axis)} - {num(proj.rod.engage_below)} - {num(proj.rod.length_tolerance)} = {num(rod.bottom_extended)}", size=12)
    others = ", ".join(f"G{k} {num(model.rod_geometry(k).length)} mm" for k in range(2, proj.stack.n_motor_planes + 1))
    svg.text(40, fy + 38, f"Länge = Hub - unteres Ende = {num(proj.rod.stroke)} - ({num(rod.bottom_extended)}) = {num(rod.length)} mm. "
                          f"Tiefere Ebenen brauchen längere Stangen ({others})", size=12)
    svg.save("03_stangenlaenge.svg")


# -- Drawing of real arrangements from build_geometry ---------------------------------------------------
def draw_arrangement(svg: Svg, geometry: dict, X, Y, scale: float) -> None:
    """Housings and gears coloured by layer (lower layers first), rods with their holes."""
    for u in sorted(geometry["units"], key=lambda u: -u["plane"]):
        col = plane_color(u["plane"])
        for p in u["parts"]:
            pts = [(X(x), Y(y)) for x, y in p["outline"]]
            if p["kind"] == "housing":
                svg.poly(pts, fill=col, fill_opacity=0.28, stroke=col, stroke_width=1.1)
            elif p["kind"] == "gear":
                svg.poly(pts, fill=col, fill_opacity=0.85, stroke=INK, stroke_width=0.5)
    for u in geometry["units"]:
        svg.circle(X(u["x"]), Y(u["y"]), geometry["hole_diameter"] / 2 * scale, fill="#ffffff", stroke=INK, stroke_width=0.8)
        svg.circle(X(u["x"]), Y(u["y"]), geometry["rod_diameter"] / 2 * scale, fill=ROD)


def legend(svg: Svg, x: float, y: float, planes: list[int]) -> None:
    for i, plane in enumerate(planes):
        col = plane_color(plane)
        svg.rect(x + i * 125, y - 10, 14, 14, fill=col, fill_opacity=0.5, stroke=col)
        svg.text(x + i * 125 + 20, y + 2, f"Motor auf G{plane}", size=12)
    svg.circle(x + len(planes) * 125 + 7, y - 3, 4, fill=ROD)
    svg.text(x + len(planes) * 125 + 16, y + 2, "Stange im Loch", size=12)


def solve(optimizer: str):
    proj = Project()
    proj.search.optimizer = optimizer
    proj.search.time_limit_s = 20
    model = Model(proj)
    result = run_optimizer(model)
    if not result.best:
        sys.exit(f"no result for {optimizer}")
    return model, result


def nearest_distance(placements) -> float:
    return min(math.dist((a.x, a.y), (b.x, b.y)) for i, a in enumerate(placements) for b in placements[i + 1:])


# -- Figure 4. Real result 2a (top view) -------------------------------------------------------------------
def figure_result(model: Model, result) -> None:
    geo = build_geometry(model, result.best.placements)
    b = geo["bounds"]
    s, pad = 4.6, 40
    X = lambda x: pad + (x - b["xmin"]) * s  # noqa: E731
    Y = lambda y: pad + (b["ymax"] - y) * s  # noqa: E731
    w, h = (b["xmax"] - b["xmin"]) * s, (b["ymax"] - b["ymin"]) * s
    svg = Svg(pad * 2 + w + 330, pad * 2 + h + 40, "Echtes Ergebnis Muster 2a, Draufsicht")
    svg.rect(X(b["xmin"]), Y(b["ymax"]), w, h, fill=LIGHT, stroke=INK, stroke_width=1.2)
    draw_arrangement(svg, geo, X, Y, s)
    tile = result.best.tile
    ox, oy = tile["origins"][0]
    svg.rect(X(ox - tile["cell"][0] / 2), Y(oy + tile["cell"][1] / 2), tile["width"] * s, tile["height"] * s,
             fill="none", stroke=RED, stroke_width=1.8, stroke_dasharray="6 4")
    svg.text(X(b["xmin"]), Y(b["ymin"]) + 20, "(0, 0)", size=12, fill=MUTED)
    svg.text(X(b["xmax"]), Y(b["ymin"]) + 20, f"x = {num(b['xmax'])} mm", size=12, anchor="end", fill=MUTED)
    legend(svg, pad, pad + h + 40, sorted({u["plane"] for u in geo["units"]}))
    lx = pad + w + 30
    angle = result.best.placements[0].angle
    svg.text(lx, pad + 10, "Was man sieht", size=14, weight="bold")
    svg.text(lx, pad + 34, f"{len(geo['units'])} Löcher im Muster Quadrat,\nLochabstand {num(tile['pitch'])} mm.\n\n"
                           "Die Gehäuse überlappen sich in der\nDraufsicht. Sie liegen aber auf\n"
                           "verschiedenen Ebenen (Farbe) und\nstoßen im Raum nicht zusammen.\n\n"
                           f"Alle Motoren sind um {num(angle)} Grad gedreht.\n"
                           "Rot gestrichelt ein Block. Ein Motor\nauf G1 und einer auf G2 wechseln\n"
                           "sich ab, der Block wiederholt sich\nüber die ganze Platte.\n\n"
                           "Gerechnet mit den Standardwerten\n(Platte 120 x 120 mm, Stange 4 mm,\n"
                           f"Motor N20 mit Encoder {num(model.project.motor.width)} x {num(model.project.motor.depth)} mm,\n"
                           "3 Motorebenen, Muster Quadrat, so\nviele Löcher wie "
                           "passen, Lochabstand\nso klein wie möglich).", size=12)
    svg.save("04_ergebnis_muster_2a.svg")


# -- Figure 5. Board, keep out strip, edge strip and hole area ---------------------------------------------
def figure_board() -> None:
    proj = Project()
    proj.bounds.edge_margin = 3.0
    proj.bounds.border = True
    proj.bounds.border_width = 10.0
    model = Model(proj)
    b = proj.bounds
    s, pad, left = 4.0, 50, 100
    X = lambda x: left + x * s  # noqa: E731
    Y = lambda y: pad + (b.height - y) * s  # noqa: E731
    svg = Svg(left + pad + b.width * s + 360, pad * 2 + b.height * s + 30, "Platte, Sperrrand, Randbereich und Lochbereich")
    svg.rect(X(0), Y(b.height), b.width * s, b.height * s, fill="#fbe9d0", stroke=INK, stroke_width=1.6)
    inner, em = b.rod_margin, b.edge_margin
    svg.rect(X(inner), Y(b.height - inner), (b.width - 2 * inner) * s, (b.height - 2 * inner) * s, fill="#ffffff",
             stroke=INK, stroke_width=1, stroke_dasharray="6 4")
    svg.rect(X(em), Y(b.height - em), (b.width - 2 * em) * s, (b.height - 2 * em) * s, fill="none", stroke=MUTED,
             stroke_width=0.9, stroke_dasharray="2 3")
    # A unit whose motor points into the edge strip on the right (angle 90 turns the housing to +x)
    unit = (82.0, 62.0)
    for part in model.unit_parts(0, unit[0], unit[1], 1, 90.0):
        pts = [(X(x), Y(y)) for x, y in part.prism.fp.outline()]
        if part.kind == "housing":
            svg.poly(pts, fill=plane_color(1), fill_opacity=0.35, stroke=plane_color(1), stroke_width=1.2)
        elif part.kind == "gear":
            svg.poly(pts, fill=plane_color(1), fill_opacity=0.85, stroke=INK, stroke_width=0.6)
    holes = [(x, y) for x in (25.0, 47.0, 69.0) for y in (22.0, 44.0, 66.0, 88.0)] + [unit, (88.0, 25.0), (91.0, 98.0)]
    for x, y in holes:
        svg.circle(X(x), Y(y), model.hole_r * s, fill="#ffffff", stroke=INK)
        svg.circle(X(x), Y(y), model.rod_r * s, fill=ROD)
    svg.dim(X(0), Y(b.height) - 18, X(b.width), Y(b.height) - 18, f"Breite (x) {num(b.width)} mm", side=1)
    svg.dim(X(0) - 18, Y(b.height), X(0) - 18, Y(0), f"Höhe (y)\n{num(b.height)} mm", side=-1)
    svg.arrow(X(0), Y(6), X(inner), Y(6))
    svg.text(X(inner) + 4, Y(6) + 4, f"{num(inner)} mm = Sperrrand {num(em)} + Randbereich {num(b.border_width)}", size=11)
    svg.text(X(0), Y(0) + 20, "(0, 0) Ursprung unten links", size=12, fill=MUTED)
    lx = left + b.width * s + 50
    svg.leader(X(b.width - em), Y(110), lx, Y(110), f"Sperrrand für alle Bauteile {num(em)} mm.\nKein Bauteil kommt näher an den Plattenrand")
    svg.leader(X(b.width - 6.5), Y(84), lx, Y(88), f"Randbereich nur für Motoren {num(b.border_width)} mm\n(Breite des Randbereichs). Motoren und\nZahnräder dürfen hinein, Löcher nicht")
    svg.leader(X(b.width - 4), Y(62), lx, Y(60), "Dieser Motor ragt in den Randbereich, das ist\nerlaubt. Das Ziel Kleiner Rand hält solche\nÜberstände möglichst klein")
    svg.leader(X(b.width - inner), Y(36), lx, Y(34), f"Lochbereich (gestrichelt). Jede Stange liegt\nganz darin, also mindestens {num(inner)} mm vom\nPlattenrand entfernt")
    svg.save("05_platte_und_rand.svg")


# -- Figure 6. Pattern shapes ------------------------------------------------------------------------------
def pattern_cell(pattern: str, a: float, b: float | None = None):
    """Lattice cell (width, height, holes) like optimizers/periodic_tile.pattern_cell."""
    r3, r2 = math.sqrt(3), math.sqrt(2)
    if pattern == "square":
        return a, a, [(0, 0)]
    if pattern == "centered_square":
        return a * r2, a * r2, [(0, 0), (a * r2 / 2, a * r2 / 2)]
    if pattern == "hex":
        return a, a * r3, [(0, 0), (a / 2, a * r3 / 2)]
    if pattern == "hex_rotated":
        return a * r3, a, [(0, 0), (a * r3 / 2, a / 2)]
    if pattern == "staggered":
        row = b or a * r3 / 2
        return a, 2 * row, [(0, 0), (a / 2, row)]
    return a, b or a * 1.5, [(0, 0)]  # rectangle


def figure_patterns() -> None:
    panels = [("square", "Quadrat"), ("centered_square", "Würfel Fünf\n(Quadrat mit Mittelloch)"), ("hex", "Hexagonal"),
              ("hex_rotated", "Hexagonal, 90 Grad gedreht"), ("staggered", "Versetzte Reihen"), ("rectangle", "Rechteck")]
    pw, ph, a, s = 300, 250, 15.0, 3.2
    svg = Svg(pw * 3 + 20, ph * 2 + 76, "Musterformen mit Lochabstand a und zweitem Abstand b")
    for k, (name, label) in enumerate(panels):
        px, py = 10 + (k % 3) * pw, 10 + (k // 3) * ph
        svg.rect(px + 4, py + 4, pw - 8, ph - 8, fill="#fafbfc", stroke="#d6dae2", rx=8)
        svg.text(px + pw / 2, py + 26, label, size=13, anchor="middle", weight="bold")
        b = 1.6 * a if name == "rectangle" else (0.75 * a if name == "staggered" else None)
        cw, chh, holes = pattern_cell(name, a, b)
        x0, y0 = px + 44, py + ph - 30
        for i in range(-1, 9):
            for j in range(-1, 9):
                for u, v in holes:
                    x, y = x0 + (i * cw + u) * s, y0 - (j * chh + v) * s
                    if px + 22 < x < px + pw - 22 and py + 54 < y < py + ph - 18:
                        svg.circle(x, y, 3.2, fill=ROD)
        svg.rect(x0, y0 - chh * s, cw * s, chh * s, fill="none", stroke=MUTED, stroke_width=0.8, stroke_dasharray="4 3")
        # a. In the row for rectangle and staggered rows, otherwise to the nearest hole of the cell
        if name in ("rectangle", "staggered", "square"):
            ax, ay = x0 + a * s, y0
        else:
            u, v = holes[1]
            ax, ay = x0 + u * s, y0 - v * s
        svg.line(x0, y0, ax, ay, stroke=RED, stroke_width=1.6)
        svg.text((x0 + ax) / 2 + 2, (y0 + ay) / 2 + (16 if ay == y0 else -6), "a", size=14, weight="bold", fill=RED)
        if name in ("rectangle", "staggered"):
            yb = y0 - (chh if name == "rectangle" else chh / 2) * s
            svg.arrow(x0 - 14, y0, x0 - 14, yb, color=BLUE, width=1.4)
            svg.text(x0 - 30, (y0 + yb) / 2 + 5, "b", size=14, weight="bold", fill=BLUE)
    svg.text(14, ph * 2 + 30, "a ist der Lochabstand. Bei Quadrat, Würfel Fünf und den Hexagonalen der Abstand zum nächsten Loch,\n"
                              "bei Rechteck und Versetzte Reihen der Abstand in der Reihe. b ist der zweite Abstand, beim Rechteck in y,\n"
                              "bei Versetzte Reihen der Reihenabstand. Gestrichelt eine Zelle des Gitters.", size=11, fill=MUTED, italic=True)
    svg.save("06_musterformen.svg")


# -- Figure 7. 2a and 2b side by side (real results, a window of the board) ---------------------------------
def window_figure(svg: Svg, model: Model, placements, ox: float, oy: float, title: str, text: str, window=(20, 20, 100, 100)) -> None:
    geo = build_geometry(model, placements)
    x0, y0, x1, y1 = window
    s = 3.6
    X = lambda x: ox + (x - x0) * s  # noqa: E731
    Y = lambda y: oy + (y1 - y) * s  # noqa: E731
    clip = f"clip{int(ox)}"
    svg.add(f'<clipPath id="{clip}"><rect x="{ox}" y="{oy}" width="{(x1 - x0) * s}" height="{(y1 - y0) * s}"/></clipPath>')
    svg.rect(ox, oy, (x1 - x0) * s, (y1 - y0) * s, fill=LIGHT, stroke=INK)
    svg.add(f'<g clip-path="url(#{clip})">')
    draw_arrangement(svg, geo, X, Y, s)
    svg.add("</g>")
    svg.text(ox, oy - 26, title, size=15, weight="bold")
    svg.text(ox, oy + (y1 - y0) * s + 22, text, size=12)


def figure_2a_2b(model_a: Model, result_a, model_b: Model, result_b) -> None:
    svg = Svg(1000, 480, "Muster 2a und 2b mit den Standardwerten")
    window_figure(svg, model_a, result_a.best.placements, 30, 50, "2a. Löcher und Motoren wiederholen sich",
                  f"Lochabstand {num(result_a.best.tile['pitch'])} mm. Jeder Motor gleich gedreht,\n"
                  "G1 und G2 wechseln sich ab. Als Block beliebig\nerweiterbar (Muster kacheln)")
    placements = result_b.best.placements
    angles = {p.angle for p in placements}
    planes = sorted({p.plane for p in placements})
    window_figure(svg, model_b, placements, 520, 50, "2b. Nur die Löcher bilden das Muster",
                  f"Lochabstand {num(nearest_distance(placements))} mm. Jeder Motor einzeln gedreht\n"
                  f"({len(angles)} verschiedene Winkel) auf G{planes[0]} bis G{planes[-1]}. Kein Block,\n"
                  "die Anordnung gilt nur für diese Platte")
    legend(svg, 30, 460, [1, 2, 3])
    svg.text(560, 462, "Ausschnitt x und y von 20 bis 100 mm", size=11, fill=MUTED, italic=True)
    svg.save("07_muster_2a_2b.svg")


# -- Figure 8. Tiling the block of 2a --------------------------------------------------------------------
def figure_tiling(model: Model, result) -> None:
    tile = result.best.tile
    nx, ny = 3, 3
    project, placements, _ = tile_project(model.project, tile, nx, ny)
    tiled = Model(project)
    first = tile["units"][0]
    dx, dy = placements[0].x - first["x"], placements[0].y - first["y"]  # origin of the first block on the new board
    cw, ch = tile["cell"]
    svg = Svg(1000, 420, "Muster kacheln")
    # Left the block
    block = placements[:len(tile["units"])]
    s, ox, oy = 3.8, 40, 90
    X = lambda x: ox + (x - dx + 22) * s  # noqa: E731
    Y = lambda y: oy + (dy + 34 - y) * s  # noqa: E731
    draw_arrangement(svg, build_geometry(tiled, block), X, Y, s)
    svg.rect(X(dx - cw / 2), Y(dy - ch / 2 + tile["height"]), tile["width"] * s, tile["height"] * s,
             fill="none", stroke=RED, stroke_width=1.6, stroke_dasharray="6 4")
    svg.text(ox, 40, f"Block {num(tile['width'])} x {num(tile['height'])} mm, {len(block)} Löcher", size=15, weight="bold")
    # Right the tiled arrangement on its fitted board, block borders cut at the board
    b = project.bounds
    s2 = min(540 / b.width, 360 / b.height)
    ox2, oy2 = 420, 60
    X2 = lambda x: ox2 + (x - b.xmin) * s2  # noqa: E731
    Y2 = lambda y: oy2 + (b.ymax - y) * s2  # noqa: E731
    svg.rect(X2(b.xmin), Y2(b.ymax), b.width * s2, b.height * s2, fill=LIGHT, stroke=INK)
    svg.add(f'<clipPath id="board"><rect x="{X2(b.xmin)}" y="{Y2(b.ymax)}" width="{b.width * s2}" height="{b.height * s2}"/></clipPath>')
    draw_arrangement(svg, build_geometry(tiled, placements), X2, Y2, s2)
    svg.add('<g clip-path="url(#board)">')
    for i in range(nx):
        for j in range(ny):
            x, y = dx - cw / 2 + i * tile["width"], dy - ch / 2 + j * tile["height"]
            svg.rect(X2(x), Y2(y + tile["height"]), tile["width"] * s2, tile["height"] * s2, fill="none",
                     stroke=RED, stroke_width=1, stroke_dasharray="5 4")
    svg.add("</g>")
    svg.text(ox2, 40, f"Gekachelt {nx} x {ny}, {len(placements)} Löcher, Platte {num(b.width)} x {num(b.height)} mm", size=15, weight="bold")
    svg.arrow(300, 220, 400, 220, both=False, width=2)
    svg.text(350, 190, f"Blöcke in x {nx}\nBlöcke in y {ny}", size=12, anchor="middle")
    svg.text(40, 405, "Der Block ist gegen alle seine Kopien kollisionsfrei geprüft, darum darf man ihn beliebig oft "
                      "aneinandersetzen. Die Platte wird passend gerechnet.", size=12, fill=MUTED, italic=True)
    svg.save("08_muster_kacheln.svg")


# -- Figures 9 and 10. Variant with a rotating tube (docs/MOTORVARIANTE_ROHR.md) -------------------------------------
# One tile of cad/onshape/rohrantrieb.fs with the default stroke of 40 mm, all in mm. z = 0 is the top surface.
TUBE_VARIANT = {
    "stroke": 40.0, "pitch": 0.7,
    "rod_d": 4.0, "flats": 3.4, "rod_len": 58.0, "flat_len": 46.5,
    "half_x": 6.9, "pitch_x": 14.0, "inner_half": 6.1, "top": -6.0, "slot_half": 1.75,
    "tube_r": 4.0, "tube_top": -7.0, "thread_bottom": -15.0, "bore_r": 2.3, "bore_end": -59.5, "d_top": -60.5,
    "motor_face": -71.0, "shaft_top": -61.0, "gearbox": 9.0, "can": 15.0, "encoder": 8.0,
    "housing_bottom": -103.0, "floor_bottom": -105.0, "cable_half": 4.0,
}


def figure_tube_section() -> None:
    v = TUBE_VARIANT
    s, zmax, top = 6.0, 48.0, 40
    cx = 330.0
    Z = lambda z: top + (zmax - z) * s  # noqa: E731
    X = lambda x: cx + x * s  # noqa: E731
    pts = lambda seq: [(X(x), Z(z)) for x, z in seq]  # noqa: E731
    height = top + (zmax - v["floor_bottom"]) * s + 70
    svg = Svg(1080, height, "Variante Rohrantrieb, Schnitt durch eine Kachel")
    PRINT, TUBE, MOTOR = "#d5d9e0", "#eb7a2e", "#4e79a7"
    hx, hi, p = v["half_x"], v["inner_half"], v["pitch"]
    tt, tb, mf = v["tube_top"], v["thread_bottom"], v["motor_face"]
    # Neighbour tiles, only their edges, 0.2 mm gap
    for sign in (-1, 1):
        svg.rect(X(min(sign * (hx + 0.2), sign * 10.5)), Z(0), 3.3 * s, (0 - v["housing_bottom"]) * s, fill=PRINT,
                 fill_opacity=0.35, stroke=MUTED, stroke_width=0.6, stroke_dasharray="4 3")
    # Floor of the tray with the cable slot
    for a, b in ((-10.5, -v["cable_half"]), (v["cable_half"], 10.5)):
        svg.rect(X(a), Z(v["housing_bottom"]), (b - a) * s, 2 * s, fill=PLATE_G0, stroke=INK, stroke_width=0.6)
    # Housing, printed. Sleeve with a closed top, the top is the Sicherung with the double D slot
    for sign in (-1, 1):
        shape = [(hx, 0), (v["slot_half"], 0), (v["slot_half"], v["top"]), (hi, v["top"]), (hi, v["housing_bottom"]),
                 (hx, v["housing_bottom"])]
        svg.poly(pts([(sign * x, z) for x, z in shape]), fill=PRINT, stroke=INK, stroke_width=0.8)
    # Tube, printed. Open end with the internal thread, free bore, closed bottom with the D bore
    r = v["tube_r"]
    for sign in (-1, 1):
        wall = [(2.08, tt), (r - 0.5, tt), (r, tt - 0.5), (r, mf + 0.5), (r - 0.5, mf), (2.5, mf), (2.5, mf + 1), (1.55, mf + 1),
                (1.55, v["d_top"]), (0.0, v["d_top"]), (0.0, v["bore_end"]), (v["bore_r"], v["bore_end"]), (v["bore_r"], tb),
                (2.08, tb)]
        svg.poly(pts([(sign * x, z) for x, z in wall]), fill=TUBE, fill_opacity=0.8, stroke=INK, stroke_width=0.7)
        z = tb
        while z < tt - 0.01:  # internal thread teeth
            svg.poly(pts([(sign * 2.08, z), (sign * 1.65, z + p / 2), (sign * 2.08, min(z + p, tt))]), fill=TUBE, stroke="none")
            z += p
    # N20 motor with the bearing boss, D shaft into the tube
    z = mf
    for length, col, op in ((v["gearbox"], "#b8bec9", 1.0), (v["can"], MOTOR, 0.35), (v["encoder"], "#59a14f", 0.45)):
        svg.rect(X(-6), Z(z), 12 * s, length * s, fill=col, fill_opacity=op, stroke=INK, stroke_width=0.8)
        z -= length
    svg.rect(X(-2), Z(mf + 0.5), 4 * s, 0.5 * s, fill="#8a919c", stroke=INK, stroke_width=0.4)
    svg.rect(X(-1.5), Z(v["shaft_top"]), 3 * s, (v["shaft_top"] - mf) * s, fill="#55595f")
    svg.rect(X(0.9), Z(v["shaft_top"]), 0.6 * s, (v["shaft_top"] - mf) * s, fill="#ffffff", fill_opacity=0.35)
    # Threaded rod, retracted (solid, thread teeth on the round part) and extended (dashed)
    f = v["flats"] / 2
    fb, rb = -v["flat_len"], -v["rod_len"]
    svg.rect(X(-f), Z(0), 2 * f * s, (0 - fb) * s, fill=ROD)
    svg.rect(X(-1.6), Z(fb), 3.2 * s, (fb - rb) * s, fill=ROD)
    z = rb
    while z < fb - 0.01:
        for sign in (-1, 1):
            svg.poly(pts([(sign * 1.6, z), (sign * 2.0, z + p / 2), (sign * 1.6, z + p)]), fill=ROD, stroke="none")
        z += p
    svg.rect(X(-2), Z(v["stroke"]), 4 * s, v["rod_len"] * s, fill="none", stroke=ROD, stroke_width=1, stroke_dasharray="4 3")
    # Motion arrows
    svg.arrow(X(4.5), Z(32), X(4.5), Z(12), both=True, color=RED, width=1.6)
    svg.text(X(5.5), Z(22) + 4, "Stange\nfährt", size=11, fill=RED)
    rx, ry = X(0), Z(-38)
    svg.add(f'<path d="M{rx - 26:.1f},{ry:.1f} A26,7 0 0 0 {rx + 26:.1f},{ry:.1f}" fill="none" stroke="{RED}" '
            f'stroke-width="1.6" marker-end="url(#arrow)"/>')
    svg.text(rx + 30, ry + 16, "Rohr dreht", size=11, fill=RED)
    # Dimensions
    svg.dim(X(-hx - 0.1), Z(44), X(hx + 0.1), Z(44), f"Raster {num(v['pitch_x'], 0)} mm", side=-1)
    svg.dim(X(-16), Z(0), X(-16), Z(v["stroke"]), f"Hub\n{num(v['stroke'], 0)} mm", side=-1)
    svg.dim(X(14), Z(0), X(14), Z(v["floor_bottom"]), f"{num(-v['floor_bottom'], 0)} mm\nunter der\nOberfläche", side=1)
    # Labels
    lx = 650
    svg.leader(X(0.5), Z(40), lx, Z(44), "Gewindestange M4 ausgefahren (gestrichelt)")
    svg.leader(X(1.7), Z(-2), lx, Z(20), f"Gewindestange M4, oben Doppel D (Schlüsselweite\n{num(v['flats'])} mm) über "
                                        f"{num(v['flat_len'])} mm, sonst volles Gewinde")
    svg.leader(X(4.5), Z(-3), lx, Z(4), "Sicherung. Geschlossene Oberseite des Gehäuses\nmit Doppel D Schlitz, hält die Stange gegen Drehen")
    svg.leader(X(1.9), Z(-11), lx, Z(-11), "Offenes Ende des Rohres mit M4 Innengewinde,\n8 mm lang, nach dem Druck eingeschnitten")
    svg.leader(X(4), Z(-25), lx, Z(-28), "Rohr, gedruckt, dreht. Innen frei für die Stange")
    svg.leader(X(-6.5), Z(-45), lx, Z(-44), "Gehäuse, gedruckt. Außen 13,8 x 11,8 mm, Wand 0,8 mm,\nist die Kachel")
    svg.leader(X(1.2), Z(-64), lx, Z(-60), "D Bohrung, die D Welle des N20 ist der Key.\nNur Drehmoment, 0,5 mm Luft über dem Wellenende")
    svg.leader(X(3.5), Z(-71), lx, Z(-74), "Rohr steht auf der Getriebeplatte und gibt die\nAxialkraft dorthin ab, Aussparung für den Lagerbund")
    svg.leader(X(6), Z(-87), lx, Z(-88), "N20 mit Encoder, die Tasche hält das Drehmoment")
    svg.leader(X(9), Z(-60), lx, Z(-98), "Nachbarkachel, Spalt 0,2 mm")
    svg.leader(X(-6), Z(-104), lx, Z(-108), "Boden der Wanne mit Kabelschlitz")
    svg.text(40, height - 22, "Schnitt durch eine Kachel, maßstäblich nach cad/onshape/rohrantrieb.fs mit Hub 40 mm. "
                              "Eingefahren ist die Spitze bündig mit der Oberfläche.", size=11, fill=MUTED, italic=True)
    svg.save("09_rohrantrieb_schnitt.svg")


def figure_double_d() -> None:
    v = TUBE_VARIANT
    s = 30.0
    svg = Svg(900, 330, "Doppel D Abflachung im Querschnitt")
    for i, (title, with_bush) in enumerate((("Stange M4 mit Doppel D", False), ("in der Sicherung", True))):
        cx, cy = 150 + i * 520, 160
        r, f = v["rod_d"] / 2, v["flats"] / 2
        if with_bush:
            svg.rect(cx - 3.6 * s, cy - 3.6 * s, 7.2 * s, 7.2 * s, fill="#f4c542", stroke=INK)
            a = math.degrees(math.acos((f + 0.05) / (r + 0.05)))
            path_bush = _double_d_path(cx, cy, (r + 0.05) * s, (f + 0.05) * s, a)
            svg.add(f'<path d="{path_bush}" fill="#ffffff" stroke="{INK}" stroke-width="1"/>')
        a = math.degrees(math.acos(f / r))
        svg.add(f'<path d="{_double_d_path(cx, cy, r * s, f * s, a)}" fill="{ROD}" stroke="none"/>')
        svg.circle(cx, cy, r * s, fill="none", stroke=MUTED, stroke_width=1, stroke_dasharray="4 3")
        svg.text(cx, 30, title, size=14, anchor="middle", weight="bold")
    cx, cy = 150, 160
    svg.dim(cx - v["flats"] / 2 * s, cy + 2.8 * s, cx + v["flats"] / 2 * s, cy + 2.8 * s, f"Schlüsselweite {num(v['flats'])} mm", side=-1)
    svg.dim(cx - 2.8 * s, cy - 2 * s, cx - 2.8 * s, cy + 2 * s, "Ø 4", side=-1)
    svg.text(290, 130, "Zwei parallele Flächen, wie bei einem\nSchraubenschlüssel. Gestrichelt das\nursprüngliche Gewinde. Zwischen den\nFlächen bleibt Gewinde stehen und\ngreift weiter in die Mutter.", size=12)
    svg.text(670, 300, "Die Sicherung steht fest. Die Flächen liegen an und\nverhindern das Drehen, auf und ab gleitet die Stange.", size=12, anchor="middle")
    svg.save("10_doppel_d.svg")


def _double_d_path(cx: float, cy: float, r: float, f: float, half_angle_deg: float) -> str:
    """Circle of radius r cut by two vertical flats at x = +-f (pixels)."""
    h = math.sqrt(max(r * r - f * f, 0.0))
    return (f"M{cx + f:.2f},{cy - h:.2f} L{cx + f:.2f},{cy + h:.2f} A{r:.2f},{r:.2f} 0 0 1 {cx - f:.2f},{cy + h:.2f} "
            f"L{cx - f:.2f},{cy - h:.2f} A{r:.2f},{r:.2f} 0 0 1 {cx + f:.2f},{cy - h:.2f} Z")


def main() -> None:
    model = Model(Project())
    figure_stack(model)
    figure_motor(model)
    figure_rod_length(model)
    figure_board()
    figure_patterns()
    figure_tube_section()
    figure_double_d()
    if "--variant-only" in sys.argv:
        return
    model_a, result_a = solve("periodic_tile")
    model_b, result_b = solve("pattern_holes")
    figure_result(model_a, result_a)
    figure_2a_2b(model_a, result_a, model_b, result_b)
    figure_tiling(model_a, result_a)


if __name__ == "__main__":
    main()
