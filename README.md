# Project Blindsight, Motor und Gewindestangen Optimierer

Erste lauffähige Version eines geometrischen Optimierers. Berechnet, wie viele Gewindestangen mit seitlichen Motoren
in einem mehrschichtigen Aufbau (G0 bis Gn) dicht, gleichmäßig und kollisionsfrei angeordnet werden können.
Nur Python Standardbibliothek, keine Laufzeitabhängigkeiten.

## Installation und Start

Die Laufzeit braucht nur Python 3.10 oder neuer, keine Pakete. Der einfachste Start ohne Installation, in jeder Shell

```bash
python run.py                    # Web UI auf http://127.0.0.1:8765
python run.py --port 9000 --no-browser
```

Mit virtueller Umgebung (nur nötig für die Tests oder den Befehl `blindsight`). Die Aktivierung hängt von der Shell ab

```bash
python -m venv .venv
source .venv/bin/activate          # bash, zsh
source .venv/bin/activate.fish     # fish
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
blindsight                         # oder python -m blindsight
```

Ohne Aktivierung geht es immer direkt über die Programme der Umgebung (auch bei Arch Linux mit "externally-managed-environment")

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m blindsight
.venv/bin/python -m pytest
```

Weitere Befehle

```bash
python run.py --port 9000 --no-browser                 # anderer Port, Browser nicht öffnen
PYTHONPATH=src python -m blindsight.cli examples/small_hex.json --svg out.svg --json out.json --time 20
python -m pytest                                       # Tests (braucht pytest)
```

## Architektur

| Modul | Aufgabe |
|---|---|
| `units.py` | zentrale Einheiten, intern mm und Grad in der Konfiguration |
| `config.py` | Eingabedaten als Dataclasses, JSON laden und speichern, Validierung mit Fehlerliste |
| `geometry.py` | Prismen (Kreis oder konvexes Polygon plus Z Intervall), exakte Abstände, SAT |
| `model.py` | Ebenen, Stangenlängen, Bauteile je Platzierung, Bauraum, statische Prüfung je Ebene |
| `layout.py` | Menge platzierter Einheiten, inkrementelle Kollisionsprüfung mit Raumraster, Kollisionsliste |
| `patterns.py` | Kandidatengenerierung (Quadrat, Hexagon in x oder y) |
| `scoring.py` | Zielfunktion mit konfigurierbaren Gewichten und Aufschlüsselung |
| `optimizers/` | Schnittstelle `Optimizer`, Registry, gemeinsame Bausteine (`common.py`), `pattern_greedy`, `anneal_free`, `exhaustive_small`, `parallel` |
| `diagnose.py` | verständliche Gründe, wenn keine Lösung existiert |
| `export/` | `build_geometry` (formatneutral), SVG, JSON, DXF, Bohrliste CSV, Protokoll `Exporter` für weitere Formate |
| `service.py` | Hintergrundläufe in Threads mit Fortschritt und Abbruch |
| `web/` | HTTP Server (stdlib) und Oberfläche (HTML, JS, CSS) |
| `sketch.py` | parametrische Motor Skizze, Constraint Solver, Freiheitsgrade, Konvexität |
| `motor_import.py` | Motorkontur aus SVG (Polygon), fragt nach dem Maßstab, wenn er nicht eindeutig ist |
| `docs.py` | erzeugt die Parametertabelle aus `FIELD_META` |
| `cli.py` | Optimierung ohne UI |

Entscheidungen
- Eigene Geometrie statt shapely. Alle Körper sind konvex (Quader, Zylinder), Abstände sind exakt und es ist nichts zu installieren
- Stdlib Server statt Flask. Die UI ist nur Darstellung, der Kern ist von ihr getrennt und einzeln testbar
- Optimierer und Bewertung sind austauschbar. Neue Strategien kommen in `optimizers/__init__.py`

## Geometrisches Modell

Z=0 ist die Oberseite von G0, nach unten negativ. Motoren stehen auf der Oberseite ihrer Ebene (`mount: top`) oder hängen
darunter (`mount: bottom`).

Lokales Motorsystem bei Winkel 0 Grad
- Gehäuse ist ein Quader (Breite x, Tiefe y, Höhe z), um den Ursprung zentriert
- Die Abtriebsachse liegt horizontal parallel zu y und tritt an der +y Seite aus
- Das Zahnrad ist ein Quader (Durchmesser mal Breite) im Abstand `gear_gap` hinter dem Gehäuse
- Die Gewindestange steht senkrecht im Abstand `center_distance` zur Achse (in +x) auf Höhe der Zahnradmitte
- Der Motorwinkel dreht alles um die vertikale Stangenachse. Alle Winkel 0 bis 360 Grad sind erlaubt

Stangenlänge, sauber getrennt
1. feste Motorebene (Montageflächenhöhe `z_mount`)
2. Länge unter der Motorebene (`length_below_mount`)
3. Hub über G0 (`stroke`), für alle Ebenen gleich
4. Gewindeüberstand und Zuschläge (`engage_below`, `length_tolerance`)

```
unteres Ende (ausgefahren) = z_Achse - engage_below - length_tolerance
Länge                      = stroke - unteres Ende
```

Jede tiefere Ebene bekommt damit automatisch eine längere Stange (Tabelle im Reiter Ebenen). Für die Kollisionsprüfung
gilt die Stange als Zylinder über den gesamten Verfahrweg, von der eingefahrenen Stellung bis `G0 + Hub`. Deshalb stoßen
Stangen tiefer Ebenen auch an Motoren auf den Ebenen darüber. Durchgangslöcher (Durchmesser Stange plus `2 x hole_clearance`)
werden im SVG je Ebene gezeichnet.

Kollisionsregel. Alle Paare fremder Bauteile (Gehäuse, Zahnrad, Stange, Hindernis, Bauraumgrenze) brauchen einen echten
Mindestabstand im Raum von mindestens `clearance + tolerance`. Der eigene Eingriff Zahnrad zu Stange ist keine Kollision.
Zusätzlich muss das Gehäuse samt Zahnrad vertikal zwischen die Ebenen passen und die eigene Stange freihalten.

## Optimierung

`pattern_greedy`
1. Kandidaten. Quadrat und Hexagonalraster, Teilung per Suche zwischen dem dichtesten und dem lockersten Wert
2. Zuordnung. Je Rasterpunkt wird eine Kombination aus Ebene und Winkel gesucht, die alle Bedingungen erfüllt. Ungültiges wird sofort verworfen
3. Lokale Suche (Simulated Annealing) verschiebt Stangen zur Mitte, ändert Winkel und Ebenen und ergänzt fehlende Einheiten
4. Bewertung und Top K Lösungen. Jede ausgegebene Lösung wird zusätzlich vollständig neu auf Kollisionen geprüft

Zielfunktion (alle Teilziele in 0 bis 1, Gewichte relativ und normiert)

| Ziel | Bedeutung |
|---|---|
| `count` | platzierte Anzahl relativ zur Zielanzahl |
| `area` | 1 minus genutzte Bounding Box geteilt durch Bauraum |
| `uniformity` | gleichmäßige Nachbarabstände |
| `regularity` | Quadrat oder Hexagonalordnung (psi4, psi6) |

Ehrlichkeit. Das Ergebnis ist die beste gefundene Lösung und wird nie als global optimal bezeichnet. Nur wenn die einfache
Flächenschranke erreicht wird, wird Optimalität gemeldet.

## Motor Skizze (CAD Stil)

Im Reiter "Motor Skizze" wird die Gehäusekontur wie in einer CAD Skizze aufgebaut und bemaßt.

Koordinatensystem
- Der Ursprung ist die Achse der Gewindestange (Getriebestange). Sie ist als schwarzer Kreis gezeichnet, dazu das gestrichelte Loch (Stange plus Lochspiel) und der Ring des Eigenabstands (rot, wenn das Gehäuse zu nah kommt)
- Das Zahnrad liegt fest bei (-Achsabstand, 0), die Welle zeigt in y Richtung, das Gehäuse sitzt dahinter
- Der ganze Motor dreht bei der Platzierung um die Stange. Der Regler "Drehvorschau" zeigt das, "Hüllkurve" den größten Kreis, den der Motor überstreicht
- Die Zahnradachse lässt sich in der Zeichnung ziehen (Achsabstand), das Gehäuse bleibt in der Skizze

Bedienung
- Polygon zeichnen. Klick setzt Punkte, Enter oder Doppelklick schließt. Punkte lassen sich ziehen (der Solver hält alle Constraints ein), Doppelklick auf eine Seite fügt einen Punkt ein, Rechtsklick oder Entf löscht ihn
- Seiten und Punkte anklicken (Umschalt für mehrere), dann ein Werkzeug wählen. Werte erscheinen direkt an der Skizze
- Alternativ die Tabellen "Seiten" und "Punkte". Länge, Winkel und Koordinaten eintippen setzt den passenden Constraint, die Auswahl "parallel zu" legt Parallelität fest
- Rückgängig und Wiederholen (Strg+Z, Strg+Y), Zoom mit Mausrad, Verschieben mit der Maus auf leerer Fläche, Raster mit Fang
- Maße lassen sich in mm, cm oder inch eingeben, Winkel immer in Grad

Constraints
| Typ | Bedeutung |
|---|---|
| `length` | Länge einer Seite |
| `angle` | Innenwinkel an einem Punkt (benachbarte Seiten) |
| `angle_sides` | Winkel zwischen zwei beliebigen Seiten |
| `parallel` | zwei Seiten parallel (auch gegenläufig) |
| `perpendicular` | zwei Seiten rechtwinklig |
| `equal` | zwei Seiten gleich lang |
| `horizontal`, `vertical` | Seite parallel zur x oder y Achse |
| `fix`, `coord_x`, `coord_y` | Punkt festhalten oder eine Koordinate vorgeben |
| `dist_point`, `dist_side` | Abstand eines Punktes oder einer Seite (Lot) zur Stange (`rod`) oder zur Zahnradachse (`gear`) |

Jeder Constraint kann deaktiviert werden. Der Status steht an jeder Zeile
- blau oder grün bestimmt (grün bei voll bestimmter Skizze, 0 Freiheitsgrade)
- orange redundant (bereits durch andere bestimmt, aber widerspruchsfrei)
- rot Widerspruch. Der Solver benennt den ersten Constraint, der nicht mehr zu den vorherigen passt, und behält die letzte widerspruchsfreie Lösung

Eine Skizze muss nicht voll bestimmt sein. Unterbestimmt heißt nur, dass noch Freiheitsgrade bleiben. Die aktuelle Lösung wird verwendet.

Datenformat in der Konfiguration (`motor.sketch`, Punkte im Stangenrahmen, gegen den Uhrzeigersinn)

```json
"sketch": {
  "points": [[-13, -27], [3, -27], [0, -6], [-11, -6]],
  "constraints": [
    {"type": "horizontal", "a": 0},
    {"type": "length", "a": 0, "value": 16.0},
    {"type": "parallel", "a": 0, "b": 2},
    {"type": "angle", "a": 1, "value": 78.0},
    {"type": "dist_side", "a": 3, "ref": "rod", "value": 9.0}
  ]
}
```

Seite `i` geht von Punkt `i` nach Punkt `i+1` (zyklisch), der Winkel an Punkt `i` liegt zwischen Seite `i-1` und `i`.
Beim Laden werden die Punkte als Startlage genommen und die Constraints gelöst, das Modell nutzt immer die gelöste Kontur.

Regeln und Grenzen
- Die Kontur muss konvex sein (Voraussetzung der Kollisionsprüfung). Nicht konvexe Konturen werden gemeldet, "Konvexe Hülle" repariert sie
- Das Zahnrad darf nicht ins Gehäuse ragen (Warnung in der Skizze, Fehler in der Konfiguration), der Abstand der Stange zum Gehäuse muss `motor.own_clearance` einhalten
- Mit Skizze werden `width`, `depth`, `shaft_x`, `gear_gap` und `outline` ignoriert, `width` und `depth` zeigen dann die Bounding Box
- Höchstens 40 Punkte und 150 Constraints, der Solver bricht nach 3 s ab
- Der Solver ist reines Python (Levenberg Marquardt mit Minimum Norm Schritten) und liegt in `sketch.py`, die UI ruft ihn über `/api/sketch/solve`, `from-motor`, `hull`, `insert` und `delete` auf
- SVG Import erzeugt eine Skizze ohne Constraints, die Kontur wird wie ein Umriss zum Zahnrad gesetzt

## Optimierer

| Name | Verfahren | Aussage |
|---|---|---|
| `pattern_greedy` | Quadrat und Hexagonalraster, gierige Zuordnung, Teilungssuche, lokale Suche | beste gefundene Lösung |
| `anneal_free` | freie Verteilung, Mehrfachstart, Simulated Annealing | beste gefundene Lösung |
| `exhaustive_small` | Backtracking auf diskretem Raster, kleinstes Fenster der Stangenmitten | bewiesen nur bezogen auf das Raster und nur ohne Knotenlimit, bis 14 Stangen |

Anordnungsziel `compact` packt dicht (kleine Grundfläche), `spread` verteilt gleichmäßig über den Bauraum.
`search.workers` größer 1 startet unabhängige Seeds in getrennten Prozessen und führt die Ergebnisse zusammen.
Mit `search.stagnation_s` endet ein Lauf früh, sobald die Zielanzahl erreicht ist und sich nichts mehr verbessert.

## Parameter

Alle Längen in mm (die UI rechnet auf Wunsch aus cm und inch um). Die Tabelle wird aus `FIELD_META` in `config.py` erzeugt
(`python -m blindsight.docs --update`), dieselbe Quelle füllt die UI Formulare, Tooltips und die Validierung.

<!-- PARAMS:BEGIN -->
| Parameter | Bedeutung | Einheit | Grenzen |
|---|---|---|---|
| `name` | Name. Bezeichnung des Projekts |  |  |
| `target_count` | Gewuenschte Anzahl Stangen. So viele Gewindestangen mit Motoren sollen platziert werden |  | >= 1, <= 100000 |
| `clearance` | Sicherheitsabstand. Mindestabstand zwischen allen fremden Bauteilen | mm | >= 0, <= 1000 |
| `tolerance` | Toleranz. Wird zum Sicherheitsabstand addiert (Fertigung, Rundung). Wirksamer Abstand = Sicherheitsabstand + Toleranz | mm | >= 0, <= 1000 |
| `rod.diameter` | Durchmesser. Aussendurchmesser des Gewindes | mm | > 0, <= 1000 |
| `rod.stroke` | Maximaler Hub ueber G0. So weit muss jede Stange oberhalb von G0 ausfahren koennen, unabhaengig von der Motorebene | mm | > 0, <= 100000 |
| `rod.engage_below` | Gewinde unter Zahnradachse (ausgefahren). Mindestgewinde unter der Zahnradachse bei maximalem Ausfahren | mm | >= 0, <= 100000 |
| `rod.engage_above` | Gewinde ueber Zahnradachse (eingefahren). Mindestgewinde ueber der Zahnradachse bei vollem Einfahren | mm | >= 0, <= 100000 |
| `rod.length_tolerance` | Laengenzuschlag. Zusaetzlicher Sicherheitszuschlag der Stangenlaenge | mm | >= 0, <= 100000 |
| `rod.retract_depth` | Spitze eingefahren unter G0. Tiefe der Stangenspitze unter G0 bei vollem Einfahren (0 = buendig) | mm | >= 0, <= 100000 |
| `rod.hole_clearance` | Radiales Lochspiel. Spiel der Durchgangsloecher in den Ebenen (je Seite) | mm | >= 0, <= 1000 |
| `motor.width` | Breite (x). Gehaeusebreite quer zur Welle | mm | > 0, <= 10000 |
| `motor.depth` | Tiefe (y, Wellenrichtung). Gehaeusetiefe entlang der Welle | mm | > 0, <= 10000 |
| `motor.height` | Hoehe (z). Gehaeusehoehe senkrecht zur Ebene | mm | > 0, <= 10000 |
| `motor.shaft_x` | Abtriebsachse, x Versatz. Seitlicher Versatz der Abtriebsachse zur Gehaeusemitte | mm | >= -10000, <= 10000 |
| `motor.axis_height` | Achshoehe ueber Montageflaeche. Hoehe der Abtriebsachse ueber der Montageflaeche | mm | >= 0, <= 10000 |
| `motor.gear_diameter` | Zahnrad Durchmesser. Aussendurchmesser des Antriebszahnrads | mm | > 0, <= 10000 |
| `motor.gear_width` | Zahnrad Breite. Axiale Breite des Zahnrads | mm | > 0, <= 10000 |
| `motor.gear_gap` | Abstand Gehaeuse zu Zahnrad. Axialer Abstand zwischen Gehaeusekante und Zahnrad | mm | >= 0, <= 10000 |
| `motor.center_distance` | Achsabstand Zahnrad zu Stange. Abstand der Abtriebsachse zur Stangenachse. Der Eingriff ist nur ueber diesen Abstand modelliert | mm | >= 0, <= 10000 |
| `motor.center_distance_min` | Achsabstand min (optional). Untergrenze, wenn der Optimierer den Achsabstand variieren darf | mm | >= 0, <= 10000 |
| `motor.center_distance_max` | Achsabstand max (optional). Obergrenze, wenn der Optimierer den Achsabstand variieren darf | mm | >= 0, <= 10000 |
| `motor.center_distance_steps` | Achsabstand Stufen. Anzahl der Stufen zwischen min und max (1 = nur nominal) |  | >= 1, <= 50 |
| `motor.own_clearance` | Eigenabstand Gehaeuse zur Stange. Mindestabstand des Gehaeuses zur eigenen Stange | mm | >= 0, <= 1000 |
| `motor.mount` | Montage. Motor steht auf der Ebene oder haengt darunter |  | `top` / `bottom` |
| `stack.n_motor_planes` | Anzahl Motorebenen. Anzahl der Ebenen G1 bis Gn, keine feste Obergrenze |  | >= 1, <= 1000 |
| `stack.mode` | Abstandsmodus. Wie die Ebenenhoehen angegeben werden |  | `uniform` / `gaps` / `distances` |
| `stack.uniform_spacing` | Einheitlicher Ebenenabstand. Abstand zwischen allen Ebenen (Modus uniform) | mm | > 0, <= 100000 |
| `stack.gaps` | Einzelabstaende (Liste). Abstaende G0-G1, G1-G2, ... (Modus gaps) | mm |  |
| `stack.distances` | Abstaende zu G0 (Liste). Abstand jeder Motorebene zu G0, aufsteigend (Modus distances) | mm |  |
| `stack.thickness` | Dicke Motorebenen. Plattendicke der Ebenen G1 bis Gn | mm | > 0, <= 1000 |
| `stack.g0_thickness` | Dicke G0. Plattendicke der oberen Referenzebene | mm | > 0, <= 1000 |
| `stack.thicknesses` | Dicke je Ebene (Liste, optional). Eigene Dicke fuer jede Motorebene, ueberschreibt die gemeinsame Dicke | mm |  |
| `stack.allowed_planes` | Erlaubte Motorebenen (Liste, leer = alle) (optional). Nur diese Ebenen duerfen Motoren tragen |  |  |
| `bounds.xmin` | x min. Bauraum, linke Grenze | mm | >= -1e+06, <= 1e+06 |
| `bounds.xmax` | x max. Bauraum, rechte Grenze | mm | >= -1e+06, <= 1e+06 |
| `bounds.ymin` | y min. Bauraum, untere Grenze | mm | >= -1e+06, <= 1e+06 |
| `bounds.ymax` | y max. Bauraum, obere Grenze | mm | >= -1e+06, <= 1e+06 |
| `bounds.edge_margin` | Randabstand. Zusaetzlicher Abstand aller Bauteile zum Rand | mm | >= 0, <= 1e+06 |
| `bounds.parts_in_bounds` | Im Bauraum muessen liegen. Alle Bauteile oder nur die Stangen |  | `all` / `rods` |
| `search.optimizer` | Optimierer. Suchstrategie |  | `pattern_greedy` / `anneal_free` / `exhaustive_small` |
| `search.layout_goal` | Anordnungsziel. compact packt dicht (kleine Flaeche), spread verteilt gleichmaessig ueber den ganzen Bauraum |  | `compact` / `spread` |
| `search.patterns` | Muster (square, hex_x, hex_y). Verteilungsstruktur der Kandidaten |  |  |
| `search.fixed_pitch` | Feste Teilung (optional). Nur diese Rasterteilung verwenden statt sie zu suchen | mm | > 0, <= 100000 |
| `search.angle_step` | Winkelschritt (Grad). Raster der zulaessigen Motorwinkel |  | > 0, <= 360 |
| `search.angle_min` | Winkel von (Grad). Kleinster Motorwinkel |  | >= -3600, <= 3600 |
| `search.angle_max` | Winkel bis (Grad, exklusiv). 360 = voller Kreis |  | >= -3600, <= 3600 |
| `search.allowed_angles` | Nur diese Winkel (Liste, leer = Raster) (optional). Explizite Liste erlaubter Motorwinkel | mm |  |
| `search.time_limit_s` | Zeitlimit (s). Maximale Rechenzeit |  | > 0, <= 86400 |
| `search.max_candidates` | Max. Kandidaten. Maximale Anzahl geprueften Platzierungen |  | >= 1 |
| `search.seed` | Seed. Zufallsstartwert fuer reproduzierbare Laeufe |  | >= 0 |
| `search.top_k` | Anzahl Loesungen. Wie viele beste Loesungen behalten werden |  | >= 1, <= 50 |
| `search.refine_fraction` | Anteil lokale Suche. Zeitanteil der Verfeinerung (0 bis 0.9) |  | >= 0, <= 0.9 |
| `search.stagnation_s` | Stagnation (s, optional). Beenden, wenn das Ziel erreicht ist und sich so lange nichts verbessert |  | > 0, <= 86400 |
| `search.workers` | Parallele Laeufe. Anzahl Prozesse fuer unabhaengige Seeds (1 = ohne Parallelisierung) |  | >= 1, <= 64 |
| `search.weights.count` | Anzahl Stangen. Gewicht des Ziels Anzahl |  | >= 0, <= 1000 |
| `search.weights.area` | Kleine Grundflaeche. Gewicht des Ziels Grundflaeche |  | >= 0, <= 1000 |
| `search.weights.uniformity` | Gleichmaessige Verteilung. Gewicht der gleichmaessigen Nachbarabstaende |  | >= 0, <= 1000 |
| `search.weights.regularity` | Regelmaessiges Muster. Gewicht der Quadrat oder Hexagonalordnung |  | >= 0, <= 1000 |
<!-- PARAMS:END -->

Weitere Felder ohne Tabellenzeile
- `stack.mount_zones` Montagebereiche je Ebene, zum Beispiel `{"1": [[0, 0, 60, 120]]}`
- `stack.max_per_plane` maximale Motoranzahl je Ebene, zum Beispiel `{"1": 6}`
- `stack.plane_angles` erlaubte Winkel je Ebene, zum Beispiel `{"3": [0, 90, 180, 270]}`
- `motor.outline` konvexes Polygon des Gehäuses im lokalen Motorsystem, ersetzt das Rechteck
- `motor.sketch` parametrische Kontur mit Constraints im Stangenrahmen, ersetzt Rechteck und `outline` (siehe Abschnitt Motor Skizze)
- `obstacles` feste Hindernisse (`shape` rect oder circle, `x`, `y`, `w`, `h`, `r`, `angle`, optional `z0`, `z1`, `plane` für eine Sperrzone nur auf einer Motorebene)

Beispiele in `examples/` (im UI per Dropdown ladbar)
- `small_hex.json` kleine Standardaufgabe
- `spread_even.json` gleichmäßig über den Bauraum verteilt
- `polygon_motor_variable_center_distance.json` gezeichnete Motorkontur, Achsabstand wird mitoptimiert
- `plane_rules.json` Kapazität, Winkel, Sperrzone und Dicke je Ebene
- `exact_small.json` exakte Suche auf dem Raster
- `sketch_trapezoid_motor.json` Trapez Motor mit Parallelität, Winkel, Länge und Abstand zur Stange
- `sketch_rectangle_dimensions.json` Rechteck als bemaßte Skizze
- `three_levels_mixed_gaps.json` ungleiche Ebenenabstände mit Hindernis
- `bottom_mount_two_levels.json` Motoren unter den Ebenen
- `area_too_small.json` Bauraum zu klein, ehrliche Teillösung
- `infeasible_motor_too_tall.json` keine Lösung, Gründe werden gemeldet

## Export

SVG im Maßstab 1:1 (`width` und `height` in mm, `viewBox` in mm). Gruppe `top` ist die Draufsicht, `plane-N` je Motorebene mit
Gehäusen, Zahnrädern, Stangen und Durchgangslöchern. Die Y Achse ist gespiegelt (Ursprung links unten im Bauraum).
Das SVG ist ein geometrisches Ergebnis, kein fertiges PCB Layout. JSON enthält alle Konturen und Z Werte.
DXF (R12, mm) hat Layer `BOUNDS`, `OBSTACLES`, `TOP_RODS` sowie je Ebene `Gn_MOTOR`, `Gn_GEAR` und `Gn_HOLES`.
Die Bohrliste (CSV) enthält je Ebene alle Durchgangslöcher (jede Stange braucht ein Loch in jeder Ebene, die sie durchquert,
auch die eingefahrene Stange unterhalb ihrer Motorebene).

## Oberfläche

- Reiter Geometrie. Formulare mit Tooltips, Einheitenwahl, Fehler direkt am Feld. Motor Editor mit ziehbaren Griffen
  (Größe, Zahnrad, Achsabstand), Konturzeichnen (wird automatisch konvex), SVG Import mit Maßstabsabfrage, lokale Motor Bibliothek
- Reiter Ebenen. Abstandsmodi, Tabelle je Ebene (erlaubt, Kapazität, Winkel, Dicke), berechnete Stangenlängen und Seitenschnitt
- Reiter Bauraum. Rand, Hindernisse, Sperrzonen, Montagebereiche
- Reiter Optimierung. Gewichte mit Reglern und Voreinstellungen, Suchparameter, Fortschritt, Live Vorschau der besten Lösung
- Reiter Ergebnisse. Draufsicht, Einzelebene, Seitenschnitt, räumliche Ansicht (mit der Maus drehen), Kollisionen, engste Stellen,
  Vergleich der Top Lösungen, manuelles Bearbeiten mit sofortiger Prüfung, Export (SVG, DXF, CSV, JSON), Ergebnis speichern und laden

Server Sicherheit. Der Server bindet standardmäßig nur an 127.0.0.1, prüft Host und Origin (Schutz gegen fremde Webseiten) und
begrenzt die Größe von Anfragen.

## Mechanische Annahmen und Einschränkungen

- Das Zahnrad ist ein Quader als Einhüllende, ohne Zahngeometrie. Der Eingriff steckt nur im Achsabstand. Ob das reale Zahnrad
  in das reale Gewinde passt, muss mit den echten Bauteilen geprüft werden
- Standardwerte sind Platzhalter, keine Herstellerdaten
- Gehäuse sind konvex (Rechteck, konvexes Polygon oder Skizze). Nicht konvexe SVG Konturen werden durch ihre Hülle ersetzt
- Die Stange gilt über den ganzen Verfahrweg als Zylinder, auch eingefahren unterhalb des Motors. Das ist konservativ
- Bauraum ist ein Rechteck, Ebenen sind keine Platinen mit Leiterbahnen, Kabel und Stecker fehlen
- Die Suche ist heuristisch. Sehr große Aufgaben brauchen mehr Zeit. Bei kompakter Anordnung wird nur ein Fenster um die Mitte des Bauraums gerastert
- `exhaustive_small` untersucht Fenster der Stangenmitten ab der Ecke des Bauraums und beweist nur Rasteroptimalität
- Die 3D Ansicht ist eine einfache gedrehte Projektion
- Zahnrad und Gehäuse werden auch gegen die eigene Montageebene mit dem Sicherheitsabstand geprüft

## Nächste Schritte

1. Nicht konvexe Motorkonturen (Zerlegung in konvexe Teile), Zahnradposition aus SVG
2. Zahnform und Gewindeeingriff als eigenes Modul, Toleranzketten
3. STEP Export, Bohrbilder mit Bemaßung
4. Genetischer oder Constraint Optimierer im selben `Optimizer` Interface
5. Polygonale Bauräume, Kabelkanäle
6. Echte 3D Ansicht (three.js), Messwerkzeug, Kollisionsanimation
