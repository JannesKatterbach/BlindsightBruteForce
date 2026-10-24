"""JSON export of the computed geometry (exchange format, basis for CAD exports)."""

from __future__ import annotations

import json


class JsonExporter:
    name = "json"  # key in EXPORTERS and in the API
    extension = "json"
    filename = "blindsight.json"
    mime = "application/json"

    def export(self, geometry: dict) -> str:
        return json.dumps(geometry, indent=2, ensure_ascii=False)
