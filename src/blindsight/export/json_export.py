"""JSON Export der berechneten Geometrie (Austauschformat, Grundlage fuer spaetere CAD Exporte)."""

from __future__ import annotations

import json


class JsonExporter:
    name = "json"  # key in EXPORTERS and in the API
    extension = "json"
    filename = "blindsight.json"
    mime = "application/json"
    label = "JSON"

    def export(self, geometry: dict) -> str:
        return json.dumps(geometry, indent=2, ensure_ascii=False)
