"""Exporter protocol and shared, format independent geometry data.

All exporters (SVG, JSON, DXF, CSV, rod positions) work on the dictionary from build_geometry and know
neither optimizers nor the UI.

Export menu. An exporter may offer the choice of one layer (``layer_choice``) and of the parts it draws
(``contents``, a selection of CONTENTS with ``default_contents`` as default). The choice arrives as
ExportOptions, export_options checks a request against the exporter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from ..config import with_layers
from ..i18n import tr
from ..layout import Placement, layout_from_placements
from ..model import Model


# Parts a drawing can contain (labels in the catalogs as export.content.<name>)
CONTENTS = ("outline", "margins", "holes", "rods", "housings", "gears", "obstacles", "labels", "distances", "collisions")
ALL_LAYERS = "all"


@dataclass(frozen=True)
class ExportOptions:
    """Choice of the export menu. layer None means all layers, otherwise the index of one layer (0 is G0).
    contents are the parts to draw, None means the defaults of the exporter."""
    layer: Optional[int] = None
    contents: Optional[frozenset[str]] = None

    def on_layer(self, index: int) -> bool:
        return self.layer is None or self.layer == index


class Exporter(Protocol):
    name: str  # key in EXPORTERS and in the API (/api/export/<job>.<name>)
    extension: str  # file extension
    filename: str  # suggested file name for downloads
    mime: str  # the label in the UI comes from the catalogs (key export.<name>)
    layer_choice: bool  # one layer can be chosen
    contents: tuple[str, ...]  # parts that can be chosen (from CONTENTS), empty if the format has no choice
    default_contents: tuple[str, ...]

    def export(self, geometry: dict, options: Optional[ExportOptions] = None) -> str: ...


def chosen_contents(exporter: Exporter, options: Optional[ExportOptions]) -> frozenset[str]:
    """The parts to draw, the defaults of the exporter without a choice."""
    if options is None or options.contents is None:
        return frozenset(exporter.default_contents)
    return options.contents


def _layer_index(value: Any, count: int) -> Optional[int]:
    """None for all layers, otherwise the index of a layer ("G2", "2" or 2)."""
    if value is None or value == ALL_LAYERS:
        return None
    text = str(value).strip()
    try:
        index = int(text[1:] if text[:1] in ("G", "g") else text)
    except ValueError:
        index = -1
    if isinstance(value, bool) or not 0 <= index < count:
        raise ValueError(tr("export.bad_layer", layer=value, last=count - 1))
    return index


def export_options(exporter: Exporter, layer: Any = None, contents: Any = None, geometry: Optional[dict] = None) -> ExportOptions:
    """Check the choice of a request. Parts the format cannot draw are ignored, unknown names are an error."""
    count = len(geometry["planes"]) if geometry else 1 << 30
    index = _layer_index(layer, count)
    if index is not None and not exporter.layer_choice:
        raise ValueError(tr("export.no_layer_choice", format=tr(f"export.{exporter.name}")))
    if contents is None:
        return ExportOptions(index, None)
    if isinstance(contents, str):
        contents = [c for c in contents.split(",") if c.strip()]
    if not isinstance(contents, (list, tuple)) or not all(isinstance(c, str) for c in contents):
        raise ValueError(tr("export.bad_contents"))
    unknown = [c.strip() for c in contents if c.strip() not in CONTENTS]
    if unknown:
        raise ValueError(tr("export.unknown_content", content=", ".join(unknown), known=", ".join(CONTENTS)))
    chosen = frozenset(c.strip() for c in contents) & frozenset(exporter.contents)
    if exporter.contents and not chosen:
        raise ValueError(tr("export.no_content"))
    return ExportOptions(index, chosen)


def export_filename(exporter: Exporter, options: Optional[ExportOptions] = None) -> str:
    """File name for downloads, with the layer if only one is exported (blindsight-G0.dxf)."""
    if options is None or options.layer is None:
        return exporter.filename
    stem, dot, ext = exporter.filename.rpartition(".")
    return f"{stem}-G{options.layer}{dot}{ext}"


def result_model(model: Model, placements: list[Placement]) -> Model:
    """Model of an arrangement. With a layer count that is not fixed only the layers in use (G1 to Gk)."""
    proj = model.project
    if proj.stack.layers_fixed or not placements:
        return model
    k = max(p.plane for p in placements)
    return model if k >= proj.stack.n_motor_planes else Model(with_layers(proj, k))


def build_geometry(model: Model, placements: list[Placement]) -> dict:
    """Complete, serialisable geometry of an arrangement (all dimensions in mm). Layers that are not needed
    are left out when the layer count is not fixed."""
    model = result_model(model, placements)
    proj = model.project
    lay = layout_from_placements(model, placements)
    units = []
    for uid in sorted(lay.units):
        pl = lay.units[uid]
        parts = []
        for p in lay.parts_of(uid):
            parts.append({
                "kind": p.kind,
                "z0": p.prism.z0,
                "z1": p.prism.z1,
                "shape": p.prism.fp.kind,
                "outline": [list(pt) for pt in p.prism.fp.outline()],
                **({"cx": p.prism.fp.cx, "cy": p.prism.fp.cy, "r": p.prism.fp.r} if p.prism.fp.kind == "c" else {}),
            })
        units.append({
            "id": uid,
            "x": pl.x,
            "y": pl.y,
            "plane": pl.plane,
            "angle": pl.angle,
            "cd": pl.cd,
            "rod": model.rod_geometry(pl.plane).as_dict(),
            "parts": parts,
        })
    obstacles = []
    for o in model.obstacles:
        obstacles.append({
            "label": o.label, "z0": o.prism.z0, "z1": o.prism.z1, "shape": o.prism.fp.kind,
            "outline": [list(pt) for pt in o.prism.fp.outline()],
        })
    b = proj.bounds
    return {
        "name": proj.name,
        "units_of_length": "mm",
        "bounds": {"xmin": b.xmin, "ymin": b.ymin, "xmax": b.xmax, "ymax": b.ymax, "edge_margin": b.edge_margin,
                   "rod_margin": b.rod_margin},
        "clearance": proj.clearance,
        "tolerance": proj.tolerance,
        "required_gap": model.gap,
        "rod_diameter": proj.rod.diameter,
        "center_distance_nominal": proj.motor.center_distance,
        "hole_diameter": 2 * model.hole_r,
        "stroke": proj.rod.stroke,
        "planes": [
            {"index": p.index, "name": p.name, "z_top": p.z_top, "z_bottom": p.z_bottom, "thickness": p.thickness}
            for p in model.stack.planes
        ],
        "units": units,
        "obstacles": obstacles,
        "collisions": [c.as_dict() for c in lay.all_collisions()],
        "closest_pairs": lay.closest_pairs(12),
    }


PRESENCE_ALWAYS = "always"  # the rod reaches into the layer in every position of its stroke
PRESENCE_RETRACTED = "retracted"  # only when retracted (layers below the rod's lower end when extended)
PRESENCE_EXTENDED = "extended"  # only when extended (layers above the retracted tip)
PRESENCE_TRAVEL = "travel"  # only in between, the rod is shorter than the layer distance it travels


def _overlaps(bottom: float, top: float, plane: dict) -> bool:
    return bottom <= plane["z_top"] and top >= plane["z_bottom"]


def rod_presence(rod: dict, plane: dict) -> str | None:
    """When the rod of a unit reaches into a layer, one of the PRESENCE_* values, or None if never.

    The rod is a segment that moves from the retracted position (bottom_retracted to tip_retracted) to
    the extended position (bottom_extended to tip_extended). The positions in which it overlaps a layer
    form one interval, so overlapping in both end positions means overlapping in every position."""
    retracted = _overlaps(rod["bottom_retracted"], rod["tip_retracted"], plane)
    extended = _overlaps(rod["bottom_extended"], rod["tip_extended"], plane)
    if retracted and extended:
        return PRESENCE_ALWAYS
    if retracted:
        return PRESENCE_RETRACTED
    if extended:
        return PRESENCE_EXTENDED
    if _overlaps(rod["bottom_retracted"], rod["tip_extended"], plane):
        return PRESENCE_TRAVEL
    return None


def rod_passes(geometry: dict, unit: dict, plane_index: int) -> bool:
    """Does the rod of the unit pass through the layer at any time (through hole needed)?"""
    return rod_presence(unit["rod"], geometry["planes"][plane_index]) is not None


def holes_by_plane(geometry: dict, layer: Optional[int] = None) -> dict[int, list[dict]]:
    """Through holes per layer (including G0), with layer only of that layer. Every rod needs a hole in
    every layer it passes through."""
    planes = [p for p in geometry["planes"] if layer is None or p["index"] == layer]
    out: dict[int, list[dict]] = {p["index"]: [] for p in planes}
    for u in geometry["units"]:
        for p in planes:
            if rod_passes(geometry, u, p["index"]):
                out[p["index"]].append({"unit": u["id"], "x": u["x"], "y": u["y"], "d": geometry["hole_diameter"]})
    return out


def obstacles_of_layer(geometry: dict, layer: Optional[int]) -> list[dict]:
    """Obstacles of a drawing. For one layer those that reach into the plate or the motors of the layer."""
    if layer is None:
        return geometry["obstacles"]
    plane = geometry["planes"][layer]
    spans = [(plane["z_bottom"], plane["z_top"])]
    spans += [(p["z0"], p["z1"]) for u in geometry["units"] if u["plane"] == layer for p in u["parts"]]
    return [o for o in geometry["obstacles"] if any(o["z0"] <= top and o["z1"] >= bottom for bottom, top in spans)]


def margin_rects(bounds: dict) -> list[tuple[str, float]]:
    """Inner frames of the board. The keep out strip of all parts and, if the edge strip is on, the area of
    the holes. (name, distance to the board edge)"""
    edge, rods = bounds["edge_margin"], bounds.get("rod_margin", bounds["edge_margin"])
    out = [("edge-margin", edge)] if edge > 0 else []
    return out + ([("hole-area", rods)] if rods > edge else [])
