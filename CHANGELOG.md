# Changelog

## 0.2.0
- Schemagetriebene Validierung (`FIELD_META`), NaN, inf, falsche Typen und Bool werden abgewiesen, Fehler nennen den Feldpfad
- Motorgehäuse als beliebiges konvexes Polygon (`motor.outline`), SVG Import übernimmt die Kontur
- Achsabstand optimierbar (`center_distance_min/max/steps`)
- Ebenen mit Einzeldicken, Kapazität je Ebene, Winkelbeschränkung je Ebene, Sperrzonen je Ebene
- Anordnungsziel `compact` oder `spread`, feste Rasterteilung, frühes Beenden bei Stagnation
- Neue Optimierer `anneal_free` (freie Verteilung) und `exhaustive_small` (exakt auf Raster), optionale parallele Seeds
- Exporte DXF und Bohrliste CSV, Export beliebiger Anordnungen (`/api/export-layout`)
- Manuelle Prüfung und Bearbeitung von Anordnungen (`/api/validate`), engste Bauteilpaare
- UI. Einheitenwahl, Feldfehler am Feld, Motor Editor mit Griffen und Konturzeichnen, Motor Bibliothek, Tabelleneditoren, Live Vorschau, 3D Drehung per Maus, Ergebnis speichern und laden
- Server. Host und Origin Prüfung, Größenlimit, saubere Fehlerantworten
- Fehlerbehebungen. Zeitaufteilung der Mustersuche, riesige Bauräume (Fenster um die Mitte), Abbruch paralleler Läufe
- Tests. Referenztests der Abstandsberechnung, Fuzz der Konfiguration, Eigenschaftstests, Stresstests, API und Browser Ende zu Ende

## 0.1.0
- Erste Version. Geometriemodell, Kollisionsprüfung, Mustersuche mit lokaler Suche, Web UI, SVG und JSON Export
