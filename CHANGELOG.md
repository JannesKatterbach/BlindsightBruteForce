# Changelog

## 0.3.0
- Neuer Reiter Motor Skizze mit Zeichenfläche. Die Getriebestange liegt im Ursprung, der Motor dreht um sie (Drehvorschau, Hüllkurve, Loch und Eigenabstand Ring)
- Parametrische Skizze mit Constraints. Länge, Winkel (benachbart und beliebig), parallel, rechtwinklig, gleich lang, horizontal, vertikal, Punkt fixieren, Koordinaten, Abstand zu Stange und Zahnrad
- Solver in `sketch.py` mit Freiheitsgraden, redundanten und widersprüchlichen Constraints, Ziehen unter Constraints, Konvexitäts und Selbstschnitt Prüfung
- Punkte einfügen, löschen, konvexe Hülle, Rückgängig und Wiederholen, Zoom und Pan, Eingabe an der Skizze und in Tabellen, Einheiten mm, cm, in
- Modell rechnet im Stangenrahmen. Rückwärtskompatibel, per Golden Test gegen die alte Formel abgesichert
- SVG Import erzeugt eine Skizze, Geometrie Reiter zeigt eine Vorschau mit der Stange
- Fehlerbehebung. Bei einem Umriss, dessen Mitte nicht im Ursprung lag, saß das Zahnrad falsch (es hing an `depth / 2`, jetzt an der obersten Kante des Umrisses)
- Fehlerbehebung. Der Browser feuerte beim Neuzeichnen von Tabellen ein zweites change Ereignis und löste doppelte Änderungen aus
- Tests. Solver (Einzeltypen, Zufallsprüfung, Redundanz, Widerspruch, Ziehen, Randfälle), Modell, API, Browser Ende zu Ende

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
