"""Bohrliste (CSV) der Stangenloecher je Ebene sowie Stangenlaengen."""

from __future__ import annotations

import csv
import io

from .base import holes_by_plane


class DrillCsvExporter:
    extension = "csv"
    mime = "text/csv"
    label = "Bohrliste CSV"

    def export(self, geometry: dict) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["plane", "unit", "x_mm", "y_mm", "hole_diameter_mm", "motor_plane", "motor_angle_deg", "rod_length_mm"])
        by_id = {u["id"]: u for u in geometry["units"]}
        for idx, holes in holes_by_plane(geometry).items():
            for h in holes:
                u = by_id[h["unit"]]
                w.writerow([f"G{idx}", h["unit"], f"{h['x']:.4f}", f"{h['y']:.4f}", f"{h['d']:.4f}", f"G{u['plane']}", f"{u['angle']:.3f}", f"{u['rod']['length']:.3f}"])
        return buf.getvalue()
