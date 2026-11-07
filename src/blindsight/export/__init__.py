"""Export formats.

Extending. A new exporter is a class with ``name``, ``extension``, ``filename``, ``mime``, the choices
``layer_choice``, ``contents`` and ``default_contents`` and ``export(geometry, options) -> str`` (protocol
``base.Exporter``), a label in the catalogs (``export.<name>``) and an entry in ``_EXPORTER_CLASSES``.
Server, CLI and the export menu of the UI (via /api/schema) then know it automatically.
"""

from ..i18n import tr
from .base import (
    ALL_LAYERS, CONTENTS, ExportOptions, Exporter, build_geometry, export_filename, export_options,
)
from .csv_drill import DrillCsvExporter
from .dxf import DxfExporter
from .json_export import JsonExporter
from .rod_positions import RodPositionsExporter
from .svg import SvgExporter

_EXPORTER_CLASSES = (SvgExporter, RodPositionsExporter, JsonExporter, DxfExporter, DrillCsvExporter)
EXPORTERS = {cls.name: cls for cls in _EXPORTER_CLASSES}

# Presets of the export menu (labels and hints in the catalogs as export.preset.<name>[.hint]).
# format None keeps the chosen format, contents None takes the defaults of the format.
EXPORT_PRESETS = (
    {"name": "kicad_edge", "format": "dxf", "layer": 0, "contents": ["outline", "holes"]},
    {"name": "drill_template", "format": "svg", "layer": 0, "contents": ["outline", "margins", "holes", "labels"]},
    {"name": "motor_layer", "format": "dxf", "layer": 1, "contents": ["outline", "holes", "housings", "gears", "obstacles"]},
    {"name": "everything", "format": None, "layer": ALL_LAYERS, "contents": None},
)


def exporter_schema() -> list[dict]:
    """Description of the formats for the web UI (order as above)."""
    return [{"name": cls.name, "label": tr(f"export.{cls.name}"), "mime": cls.mime, "filename": cls.filename,
             "layer_choice": cls.layer_choice, "contents": list(cls.contents), "default_contents": list(cls.default_contents)}
            for cls in _EXPORTER_CLASSES]


def export_menu_schema() -> dict:
    """Parts and presets of the export menu."""
    return {
        "contents": [{"name": c, "label": tr(f"export.content.{c}")} for c in CONTENTS],
        "presets": [{**p, "label": tr(f"export.preset.{p['name']}"), "hint": tr(f"export.preset.{p['name']}.hint")}
                    for p in EXPORT_PRESETS],
    }


__all__ = [
    "Exporter", "ExportOptions", "build_geometry", "export_options", "export_filename",
    "SvgExporter", "JsonExporter", "DxfExporter", "DrillCsvExporter", "RodPositionsExporter",
    "EXPORTERS", "EXPORT_PRESETS", "CONTENTS",
    "exporter_schema", "export_menu_schema",
]
