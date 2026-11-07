"""JSON export of the computed geometry (exchange format, basis for CAD exports)."""

from __future__ import annotations

import json
from typing import Optional

from .base import ExportOptions


class JsonExporter:
    name = "json"  # key in EXPORTERS and in the API
    extension = "json"
    filename = "blindsight.json"
    mime = "application/json"
    layer_choice = False  # always the complete geometry
    contents: tuple[str, ...] = ()
    default_contents: tuple[str, ...] = ()

    def export(self, geometry: dict, options: Optional[ExportOptions] = None) -> str:
        return json.dumps(geometry, indent=2, ensure_ascii=False)
