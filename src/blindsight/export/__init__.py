"""Export formats.

Extending. A new exporter is a class with ``name``, ``extension``, ``filename``, ``mime`` and
``export(geometry) -> str`` (protocol ``base.Exporter``), a label in the catalogs (``export.<name>``)
and an entry in ``_EXPORTER_CLASSES``. Server, CLI and the format selection of the UI (via /api/schema)
then know it automatically.
"""

from ..i18n import tr
from .base import Exporter, build_geometry
from .csv_drill import DrillCsvExporter
from .dxf import DxfExporter
from .json_export import JsonExporter
from .rod_positions import RodPositionsExporter
from .svg import SvgExporter

_EXPORTER_CLASSES = (SvgExporter, RodPositionsExporter, JsonExporter, DxfExporter, DrillCsvExporter)
EXPORTERS = {cls.name: cls for cls in _EXPORTER_CLASSES}


def exporter_schema() -> list[dict]:
    """Description of the formats for the web UI (order as above)."""
    return [{"name": cls.name, "label": tr(f"export.{cls.name}"), "mime": cls.mime, "filename": cls.filename}
            for cls in _EXPORTER_CLASSES]


__all__ = [
    "Exporter", "build_geometry", "SvgExporter", "JsonExporter", "DxfExporter", "DrillCsvExporter", "RodPositionsExporter",
    "EXPORTERS",
    "exporter_schema",
]
