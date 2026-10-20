"""JSON Export der berechneten Geometrie (Austauschformat, Grundlage fuer spaetere CAD Exporte)."""

from __future__ import annotations

import json


class JsonExporter:
    extension = "json"
    mime = "application/json"

    def export(self, geometry: dict) -> str:
        return json.dumps(geometry, indent=2, ensure_ascii=False)
