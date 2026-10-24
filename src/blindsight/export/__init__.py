"""Exportformate.

Erweitern. Ein neuer Exporter ist eine Klasse mit ``name``, ``extension``, ``filename``, ``mime``, ``label`` und
``export(geometry) -> str`` (Protokoll ``base.Exporter``) und ein Eintrag in ``_EXPORTER_CLASSES``.
Server, CLI und die Formatauswahl der UI (ueber /api/schema) kennen ihn dann automatisch.
"""

from .base import Exporter, build_geometry
from .csv_drill import DrillCsvExporter
from .dxf import DxfExporter
from .json_export import JsonExporter
from .rod_positions import RodPositionsExporter
from .svg import SvgExporter

_EXPORTER_CLASSES = (SvgExporter, RodPositionsExporter, JsonExporter, DxfExporter, DrillCsvExporter)
EXPORTERS = {cls.name: cls for cls in _EXPORTER_CLASSES}


def exporter_schema() -> list[dict]:
    """Beschreibung der Formate fuer die Web UI (Reihenfolge wie oben)."""
    return [{"name": cls.name, "label": cls.label, "mime": cls.mime, "filename": cls.filename} for cls in _EXPORTER_CLASSES]


__all__ = [
    "Exporter", "build_geometry", "SvgExporter", "JsonExporter", "DxfExporter", "DrillCsvExporter", "RodPositionsExporter",
    "EXPORTERS",
    "exporter_schema",
]
