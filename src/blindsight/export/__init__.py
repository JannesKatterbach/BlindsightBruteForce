"""Exportformate.

Erweitern. Ein neuer Exporter ist eine Klasse mit ``extension``, ``mime``, ``label`` und
``export(geometry) -> str`` (Protokoll ``base.Exporter``) und ein Eintrag in ``_EXPORTER_CLASSES``.
Server, CLI und die Formatauswahl der UI (ueber /api/schema) kennen ihn dann automatisch.
"""

from .base import Exporter, build_geometry
from .csv_drill import DrillCsvExporter
from .dxf import DxfExporter
from .json_export import JsonExporter
from .svg import SvgExporter

_EXPORTER_CLASSES = (SvgExporter, JsonExporter, DxfExporter, DrillCsvExporter)
EXPORTERS = {cls.extension: cls for cls in _EXPORTER_CLASSES}


def exporter_schema() -> list[dict]:
    """Beschreibung der Formate fuer die Web UI (Reihenfolge wie oben)."""
    return [{"name": cls.extension, "label": cls.label, "mime": cls.mime} for cls in _EXPORTER_CLASSES]


__all__ = [
    "Exporter", "build_geometry", "SvgExporter", "JsonExporter", "DxfExporter", "DrillCsvExporter", "EXPORTERS",
    "exporter_schema",
]
