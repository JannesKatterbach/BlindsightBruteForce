# Project Blindsight, Motor und Gewindestangen Optimierer

Erste lauffähige Version eines geometrischen Optimierers. Berechnet, wie viele Gewindestangen mit seitlichen Motoren
in einem mehrschichtigen Aufbau (G0 bis Gn) dicht, gleichmäßig und kollisionsfrei angeordnet werden können.
Nur Python Standardbibliothek, keine Laufzeitabhängigkeiten.

## Installation und Start

```bash
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -e ".[dev]"                               # dev nur für pytest
python -m blindsight                                  # Web UI auf http://127.0.0.1:8765
```

Ohne Installation geht auch `PYTHONPATH=src python -m blindsight`.

Weitere Befehle

```bash
python -m blindsight --port 9000 --no-browser         # anderer Port, Browser nicht öffnen
python -m blindsight.cli examples/small_hex.json --svg out.svg --json out.json --time 20
python -m pytest                                      # Tests
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
| `optimizers/` | Schnittstelle `Optimizer`, Registry, `pattern_greedy` (Muster, gierig, lokale Suche) |
| `diagnose.py` | verständliche Gründe, wenn keine Lösung existiert |
| `export/` | `build_geometry` (formatneutral), SVG, JSON, Protokoll `Exporter` für weitere Formate |
| `service.py` | Hintergrundläufe in Threads mit Fortschritt und Abbruch |
| `web/` | HTTP Server (stdlib) und Oberfläche (HTML, JS, CSS) |
| `motor_import.py` | Motorkontur aus SVG, fragt nach dem Maßstab, wenn er nicht eindeutig ist |
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

## Parameter

Alle Längen in mm.

| Parameter | Bedeutung |
|---|---|
| `target_count` | gewünschte Anzahl Stangen mit Motoren |
| `clearance`, `tolerance` | Sicherheitsabstand und Toleranz, wirksam ist die Summe |
| `rod.diameter`, `rod.stroke` | Durchmesser und maximaler Hub über G0 |
| `rod.engage_below` / `engage_above` | Mindestgewinde unter/über der Zahnradachse bei vollem Aus/Einfahren |
| `rod.length_tolerance`, `rod.retract_depth`, `rod.hole_clearance` | Längenzuschlag, Einfahrtiefe, Lochspiel |
| `motor.width/depth/height` | Gehäuse |
| `motor.shaft_x`, `axis_height` | Lage der Abtriebsachse im Gehäuse |
| `motor.gear_diameter/gear_width/gear_gap` | Zahnrad |
| `motor.center_distance` | Achsabstand Zahnrad zu Stangenachse (Eingriff) |
| `motor.mount` | `top` oder `bottom` |
| `stack.n_motor_planes` | Anzahl Motorebenen, keine feste Obergrenze |
| `stack.mode` | `uniform`, `gaps` (Abstände G(i) zu G(i+1)) oder `distances` (zu G0) |
| `stack.allowed_planes`, `mount_zones` | erlaubte Ebenen, Montagebereiche |
| `bounds` | Bauraum, Randabstand |
| `obstacles` | feste Hindernisse (Rechteck oder Kreis, optional z0 und z1) |
| `search.weights` | Priorität der Ziele |
| `search.patterns`, `angle_step`, `allowed_angles` | Muster und erlaubte Motorwinkel |
| `search.time_limit_s`, `max_candidates`, `seed` | Limits und Reproduzierbarkeit |

Beispiele in `examples/` (im UI per Dropdown ladbar)
- `small_hex.json` kleine Standardaufgabe
- `three_levels_mixed_gaps.json` ungleiche Ebenenabstände mit Hindernis
- `bottom_mount_two_levels.json` Motoren unter den Ebenen
- `area_too_small.json` Bauraum zu klein, ehrliche Teillösung
- `infeasible_motor_too_tall.json` keine Lösung, Gründe werden gemeldet

## Export

SVG im Maßstab 1:1 (`width` und `height` in mm, `viewBox` in mm). Gruppe `top` ist die Draufsicht, `plane-N` je Motorebene mit
Gehäusen, Zahnrädern, Stangen und Durchgangslöchern. Die Y Achse ist gespiegelt (Ursprung links unten im Bauraum).
Das SVG ist ein geometrisches Ergebnis, kein fertiges PCB Layout. JSON enthält alle Konturen und Z Werte.

## Mechanische Annahmen und Einschränkungen

- Das Zahnrad ist ein Quader als Einhüllende, ohne Zahngeometrie. Der Eingriff steckt nur im Achsabstand. Ob das reale Zahnrad
  in das reale Gewinde passt, muss mit den echten Bauteilen geprüft werden
- Standardwerte sind Platzhalter, keine Herstellerdaten
- Gehäuse sind Rechtecke. Der SVG Import liefert nur Breite und Tiefe der Kontur (ein Rechteck oder Polygon)
- Bauraum ist ein Rechteck, Ebenen sind keine Platinen mit Leiterbahnen, Kabel und Stecker fehlen
- Die Suche ist heuristisch. Sehr große Aufgaben brauchen mehr Zeit, das Verfahren bevorzugt regelmäßige Muster
- Die 3D Ansicht ist eine einfache gedrehte Projektion
- Zahnrad und Gehäuse werden auch gegen die eigene Montageebene mit dem Sicherheitsabstand geprüft

## Nächste Schritte

1. Freie Motorkonturen (konvexe Polygone, später nicht konvex) und SVG Konturimport mit Zahnradposition
2. Zahnform und Gewindeeingriff als eigenes Modul, Toleranzketten
3. DXF und STEP Export, Bohrbilder für G0
4. Zweite Strategie (genetisch oder Constraint Löser) im selben `Optimizer` Interface, Vergleich der Läufe
5. Polygonale Bauräume, Kabelkanäle, Montagezonen mit UI
6. Echte 3D Ansicht (three.js), Messwerkzeug, Kollisionsanimation
7. Parallelisierung der Kandidatenprüfung
