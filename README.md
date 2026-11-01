# Project Blindsight, Motor und Gewindestangen Optimierer

Geometrischer Optimierer. Berechnet, wie viele Gewindestangen mit seitlichen Motoren in einem mehrschichtigen Aufbau
(G0 bis Gn) dicht, gleichmäßig und kollisionsfrei angeordnet werden können, auf Wunsch in einem regelmäßigen, leicht zu
bohrenden Lochbild oder für fest vorgegebene Löcher. Nur Python Standardbibliothek, keine Laufzeitabhängigkeiten.
Oberfläche und Meldungen auf Deutsch, Englisch und Französisch.

Einheiten. Alle Längen in mm, Winkel in Grad, Zeiten in Sekunden. Der Ursprung (0, 0) liegt unten links im Bauraum,
x nach rechts, y nach oben, z = 0 an der Oberseite von G0.

## Installation und Start

Die Laufzeit braucht nur Python 3.10 oder neuer, keine Pakete. Der einfachste Start ohne Installation, in jeder Shell

```bash
python run.py                    # Web UI auf http://127.0.0.1:8765
python run.py --port 9000 --no-browser
```

Mit virtueller Umgebung (nur nötig für die Tests oder die Befehle `blindsight` und `blindsight-cli`). Die Aktivierung hängt von der Shell ab

```bash
python -m venv .venv
source .venv/bin/activate          # bash, zsh
source .venv/bin/activate.fish     # fish
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
blindsight                         # Web UI, oder python -m blindsight
blindsight-cli examples/small_hex.json --svg out.svg   # Kommandozeile
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
PYTHONPATH=src python -m blindsight.cli examples/small_hex.json --rods rods.json --lang en   # Schraubenpositionen, Ausgabe Englisch
PYTHONPATH=src python -m blindsight.cli examples/small_hex.json --holes examples/holes/grid_3x3.json --rods rods.json
python -m pytest                                       # Tests (braucht pytest, Browser Tests zusätzlich Playwright)
```

Exitcodes der Kommandozeile

| Code | Bedeutung |
|---|---|
| 0 | Lösung gefunden, Dateien geschrieben |
| 1 | keine gültige Lösung gefunden |
| 2 | Konfiguration nicht lesbar oder ungültig (auch nach `--time` und `--seed`) |
| 3 | Ausgabedatei nicht schreibbar |

## Architektur

| Modul | Aufgabe |
|---|---|
| `units.py` | Einheiten, zentrale Toleranzen (`EPS`, `ANGLE_TOL_DEG`, ...), Zahlprüfung, Winkelnormierung |
| `errors.py` | Fehlerklassen mit Meldungsliste (`ValidationError`, `ConfigError`, `SketchError`) |
| `i18n/` | Kataloge `de.json`, `en.json`, `fr.json`, `tr()` liefert `LocalText`, das in jeder Sprache neu darstellbar ist |
| `holes.py` | Lochbild Dateien (`blindsight.holes`, auch der Schraubenpositionen Export), Prüfung einzelner Löcher |
| `config.py` | Eingabedaten als Dataclasses, JSON laden und speichern, `FIELD_META` (Schema für Validierung, UI und Doku), Prüfung je Abschnitt |
| `geometry.py` | Prismen (Kreis oder konvexes Polygon plus Z Intervall), exakte Abstände, SAT, Hülle, Flächen, Rotation |
| `model.py` | Ebenen, Stangenlängen, Bauteile je Platzierung, Bauraum, statische Prüfung je Ebene |
| `layout.py` | Menge platzierter Einheiten, Einheitenregeln (`UNIT_RULES`), inkrementelle Kollisionsprüfung mit Raumraster |
| `patterns.py` | Kandidatenmuster (`PATTERNS`) und Reihenfolgen (`ORDER_TABLE`) |
| `scoring.py` | Zielfunktion mit Teilzielen (`OBJECTIVES`), Kennzahlen, Obergrenze der Anzahl (Ungleichung von Oler) |
| `optimizers/` | Register (`registry.py`), Basisklasse mit Rahmen (`base.py`), gemeinsame Suche und lokale Suche (`common.py`), `pattern_greedy`, `anneal_free`, `exhaustive_small`, `periodic_tile`, `fixed_holes`, `parallel` |
| `diagnose.py` | verständliche Gründe, wenn keine Lösung existiert |
| `analysis.py` | abgeleitete Größen ohne Optimierung (Ebenen, Stangenlängen, Probleme) |
| `sketch/` | Motor Skizze wie Onshape. `entities` (Punkte, Linien, Kreise, Bögen, Referenzen), `constraints` (Register der Beziehungen und Maße), `numeric` (Levenberg Marquardt, Rang), `solver`, `profile` (Gehäusehülle, Zahnrad), `motor` |
| `export/` | `build_geometry` (formatneutral), Register `EXPORTERS` mit SVG, Schraubenpositionen JSON, JSON, DXF, Bohrliste CSV |
| `service.py` | Hintergrundläufe in Threads mit Fortschritt, Abbruch und Herunterfahren |
| `web/server.py` | HTTP Server (stdlib) mit Routentabelle, einheitlicher Fehlerform, Host, Origin und Content Type Prüfung |
| `web/static/js/` | Oberfläche als klassische Skripte ohne Build Schritt. `core` (Hilfen, Zustand, Sprachen), `i18n` (Kataloge der UI), `ui` (Reiter), `sketch` (Skizze) |
| `motor_import.py` | Motorkontur aus SVG (Polygon), fragt nach dem Maßstab, wenn er nicht eindeutig ist |
| `docs.py` | erzeugt die Parametertabelle aus `FIELD_META` |
| `cli.py` | Optimierung ohne UI |

Entscheidungen
- Eigene Geometrie statt shapely. Alle Körper sind konvex (Quader, Zylinder), Abstände sind exakt und es ist nichts zu installieren
- Stdlib Server statt Flask. Die UI ist nur Darstellung, der Kern ist von ihr getrennt und einzeln testbar
- Register statt verstreuter Fallunterscheidungen. Optimierer, Muster, Teilziele, Exportformate, Constraint Typen und Einheitenregeln sind je eine Tabelle, Tests prüfen, dass Register und Konfigurationsoptionen übereinstimmen

## Konventionen

- Alle Längen in mm (Eingabe, Speicherung, Rechenkern, Export), andere Größen in SI Einheiten, Winkel in Grad. Nur der SVG Import rechnet echte SVG Einheiten (cm, in, pt) in mm um
- Winkel in der Konfiguration in Grad (`angle_deg`), im Rechenkern in Radiant (`angle_rad`). Winkellisten werden auf 0 bis unter 360 Grad normiert
- Koordinaten. Welt mit z = 0 an der Oberseite von G0, nach unten negativ. Motoren im Stangenrahmen, Ursprung ist die eigene Gewindestange, das Zahnrad liegt bei (-Achsabstand, 0)
- Polygone gegen den Uhrzeigersinn. Seite i geht von Punkt i nach Punkt i+1
- Meldungen beginnen mit dem Feldpfad (`rod.diameter. Muss größer als 0 sein`), damit die UI sie dem Feld zuordnet. Prüfungen sammeln alle Probleme statt beim ersten abzubrechen
- Sprache. Code, Kommentare und Docstrings auf Englisch. Sichtbare Texte stehen nur in den Katalogen (`src/blindsight/i18n/*.json` für den Kern, `web/static/js/i18n/*.js` für die UI), alle Sprachen haben dieselben Schlüssel und Platzhalter (geprüft in `tests/test_i18n.py`). Standardsprache ist Deutsch
- Sprachwahl. Die UI sendet die gewählte Sprache mit jeder Anfrage (`X-Language`), der Server antwortet darin, auch für Ergebnisse früherer Läufe. Die CLI nutzt `--lang` oder `BLINDSIGHT_LANG`

## Erweitern

Neue Beziehung oder neues Maß der Skizze
1. In `sketch/constraints.py` eine Residuen Fabrik `(refs, c, v, x0) -> (x -> Liste)` schreiben (`v` greift auf Punkte, Linien und Radien im Unbekanntenvektor zu)
2. Einen `ConstraintType` in `CONSTRAINT_TYPES` eintragen (erlaubte Referenzarten `point`, `line`, `curve` je Signatur, Werteart `len`, `deg` oder keine, Prüfung des Werts)
3. Bezeichnung `constraint.<name>` in den Katalogen des Kerns
4. Für eine Beziehung einen Knopf mit `data-sk-rel` in `index.html`, den Namen in `RELATIONS` (`js/sketch/state.js`), ein Symbol in `ICONS` (`js/sketch/panels.js`), eine Glyphe in `GLYPHS` (`js/sketch/render.js`) und die Texte `ui.sk.rel.<name>` in den UI Katalogen. Signaturen und Werteart kommen über `/api/schema`

Neues Kandidatenmuster
1. Funktion `(pitch, region) -> Punkte` in `patterns.py`, Eintrag in `PATTERNS` und `PATTERN_DENSITY`
2. Die Konfiguration erlaubt den Namen in `search.patterns` automatisch

Neuer Optimierer
1. Modul in `optimizers/` mit einer Unterklasse von `Optimizer`, die `search` implementiert und mit `@register` markiert ist. Den Rahmen (Zähler, Abbruch, Machbarkeit) übernimmt `Optimizer.run`, gemeinsame Bausteine liegen in `common.SearchBase`
2. Import in `optimizers/__init__.py`, Option in `search.optimizer` (`FIELD_META`) mit Text `option.search.optimizer.<name>` in den Katalogen. `supports_parallel = False`, wenn weitere Seeds nichts bringen

Neues Teilziel der Bewertung
1. Funktion `(LayoutStats) -> float` in `scoring.OBJECTIVES`
2. Gleichnamiges Feld in `config.WeightsSpec` und ein `FIELD_META` Eintrag in der Gruppe `weights`. Der Regler in der UI entsteht daraus

Neues Exportformat
1. Klasse mit `name`, `extension`, `filename`, `mime` und `export(geometry) -> str` in `export/`, Bezeichnung `export.<name>` in den Katalogen
2. Eintrag in `_EXPORTER_CLASSES` (`export/__init__.py`). Server, CLI und Formatauswahl der UI kennen es dann

Neue Sprache
1. Kataloge `src/blindsight/i18n/<code>.json` und `web/static/js/i18n/<code>.js` mit allen Schlüsseln anlegen
2. Code in `LANGUAGES` und `LANGUAGE_NAMES` (`i18n/__init__.py`) und in `LANGUAGES` (`js/core/i18n.js`) eintragen, Skript in `index.html` einbinden

Neue Ergebnisansicht oder Einheitenregel
- Ansicht. Zeichenfunktion in `VIEWS` (`js/ui/views.js`) und eine Option in `#viewSel`
- Regel für eine einzelne Einheit. Funktion `(model, placement, parts) -> Meldung` in `layout.UNIT_RULES`, sie gilt dann für `check` und `all_collisions`

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

Gleichmäßigkeit gilt für eine einzelne Einheit als erfüllt. Regelmäßigkeit braucht mindestens 4 Nachbarn und ist sonst 0.

## Wiederholendes Muster (`periodic_tile`)

Für ein regelmäßiges, leicht zu bohrendes Lochbild. Eingabe im Reiter Optimierung, sichtbar sind nur die Felder des gewählten Musters

| Muster (`search.pattern`) | Lochbild | Abstände |
|---|---|---|
| `square` | Quadrat | a |
| `centered_square` | Würfel Fünf, Quadrat mit Mittelloch | a zu den vier nächsten Löchern |
| `hex`, `hex_rotated` | Hexagonal, Reihen in x oder (gedreht) in y | a zu allen sechs Nachbarn |
| `staggered` | versetzte Reihen wie aneinandergelegte Kreise, jede zweite Reihe um a/2 verschoben | a in der Reihe, Reihenabstand b (leer heißt dicht, b = a·0.866) |
| `rectangle` | Rechteck | a in x, b in y (leer heißt b = a) |
| `free` | frühere Kachel. `tile_rods` Schrauben je Kachel, optional `tile_width` und `tile_height` | in x und y getrennt gesucht |
| `custom` | eigene Kachel aus dem Lochbild Generator (`search.custom_tile`), fest oder skalierbar | wie gezeichnet |

- a ist `search.pattern_pitch`, b ist `search.pattern_pitch_y`. Leer heißt automatisch. `compact` sucht den kleinsten Abstand
  auf dem Raster `search.tile_step`, `spread` den größten, bei dem die Zielanzahl in den Bauraum passt
- Ebene, Motorwinkel und Achsabstand je Loch werden per Backtracking für einen Block aus m x n Zellen gesucht und wiederholen
  sich mit dem Block. Blöcke werden nach Lochzahl aufsteigend probiert (höchstens `search.max_block_holes` Löcher), die
  Motoranordnung wiederholt sich also so früh wie möglich. Ein Block ist gültig, wenn er gegen alle seine Kopien in Reichweite
  kollisionsfrei ist. Dann ist das ganze unendliche Gitter gültig, und jede Teilmenge davon auch
- Platziert werden einzelne Löcher des Gitters, jedes muss Rand, Hindernisse, Montagebereiche und Kapazität einhalten. Die
  Anzahl ist genau die Zielanzahl. Die Ergebnisansicht zeigt Muster, Abstand und Wiederholblock (gestrichelte Blockgrenzen)
- Der gefundene Abstand ist der kleinste auf dem Raster gefundene, nicht als kleinster bewiesen

## Feste Löcher (`fixed_holes`) und Lochbild Generator

Sind die Löcher von G0 vorgegeben, bestimmt `fixed_holes` je Loch Motorebene, Motorwinkel und Achsabstand.
- Exakte Suche. Das Loch mit den wenigsten verbleibenden Möglichkeiten zuerst, nach jeder Wahl werden kollidierende
  Möglichkeiten der Nachbarn gestrichen. Endet die Suche ohne Lösung und ohne Zeit oder Knotenlimit, ist bewiesen, dass nicht
  alle Löcher gleichzeitig bedient werden können
- Ohne vollständige Lösung gibt es die größte gefundene Menge bedienter Löcher (gierig in vielen Reihenfolgen plus
  Umsetzen eines blockierenden Nachbarn). Jedes übrige Loch wird mit Grund gemeldet (außerhalb des Bauraums, kollidiert mit
  den bedienten Löchern 3, 4 und 8, Kapazität erschöpft)
- Die Löcher stehen in `holes` der Konfiguration, die Zielanzahl ist dann die Lochzahl

Reiter Lochbild (Generator). Löcher als Tabelle eingeben, aus Text oder Excel einfügen (`x;y`, `x,y`, Tabulator), mit einem
Muster füllen, in der Vorschau klicken, ziehen und per Rechtsklick löschen. Der Kern prüft live auf Löcher außerhalb des
Bauraums und zu nahe Löcher. Umschalter Eigene Kachel für ein wiederholendes Muster (Breite, Höhe, Löcher in der Kachel,
fest oder skalierbar). Knöpfe JSON herunterladen, JSON laden und Für Optimierung verwenden.

Dateiformat `blindsight.holes` (mm, Ursprung unten links). Gelesen wird auch der Export der Schraubenpositionen, so lässt
sich ein Ergebnis wieder als festes Lochbild laden

```json
{"format": "blindsight.holes", "version": 1, "units": {"length": "mm"},
 "holes": [{"id": 0, "x": 30, "y": 30}, {"id": 1, "x": 60, "y": 30}],
 "tile": {"width": 40, "height": 40, "scalable": true, "holes": [{"x": 0, "y": 0}, {"x": 20, "y": 20}]}}
```

`holes` ist das feste Lochbild, `tile` die eigene Kachel (eines von beiden genügt). Beispiele in `examples/holes/`.

## Ehrlichkeit der Ergebnisse

Das Ergebnis ist die beste gefundene Lösung und wird nie als global optimal bezeichnet. Nur wenn die
Obergrenze der Anzahl erreicht wird, wird Optimalität gemeldet. Die Obergrenze folgt aus der Ungleichung von Oler für
Punkte mit Mindestabstand d (Stangendurchmesser plus Sicherheitsabstand) im Rechteck der zulässigen Stangenmitten mit
Fläche A und Umfang P, N <= 2/sqrt(3) A/d² + P/(2d) + 1. Motoren bleiben dabei unberücksichtigt.

## Motor Skizze (CAD Stil wie Onshape)

Im Reiter "Motor Skizze" wird der Motor in der Draufsicht wie in einer Onshape Skizze gezeichnet. Einfache Elemente
zeichnen, Beziehungen und Maße direkt in der Zeichnung setzen, fertig. Daneben gibt es nur eine Statuszeile und eine
einklappbare Liste der Beziehungen.

Koordinatensystem
- Der Ursprung ist die Achse der Gewindestange. Sie ist als Kreis gezeichnet, dazu das gestrichelte Loch (Stange plus
  Lochspiel) und der Ring des Eigenabstands. Der Ursprung lässt sich wie ein Punkt anklicken (Koinzident, Abstand)
- Das Zahnrad liegt auf der negativen x Achse, die Welle zeigt in y Richtung, das Gehäuse sitzt dahinter
- Der ganze Motor dreht bei der Platzierung um die Stange. Unter "Ansicht" zeigen Drehvorschau und Hüllkurve das

Elemente und Werkzeuge (Kürzel in Klammern, Esc bricht ab)
| Werkzeug | Bedienung |
|---|---|
| Auswahl (S) | Klick wählt aus und fügt zur Auswahl hinzu, Klick ins Leere leert sie. Punkte, Linien und Kreise lassen sich ziehen, leere Fläche verschiebt die Ansicht |
| Linie (L) | Klick, Klick, ... als Kette. Doppelklick, Enter oder Esc beendet, Klick auf den Startpunkt schließt die Kontur |
| Rechteck (R) | zwei Ecken. Ergibt vier Linien mit Koinzident, Horizontal und Vertikal |
| Kreis (C) | Mitte, dann Radius |
| Bogen (A) | Mitte, Start, Ende (gegen den Uhrzeigersinn) |
| Zahnrad (G) | zwei Ecken. Rechteck mit Rolle Zahnrad, die Mitte liegt auf der x Achse. Nur ein Zahnrad je Skizze |
| Konstruktion (Q) | schaltet die Auswahl auf Hilfsgeometrie (gestrichelt), sie zählt nicht zum Gehäuse |
| Bemaßung (D) | ein Element (Linie Länge, Kreis Durchmesser, Bogen Radius) oder zwei (Abstand, Winkel, Punkt zu Linie), dann die Maßzahl platzieren und den Wert eintippen |
| Rückgängig, Wiederholen | Strg+Z, Strg+Y oder Strg+Umschalt+Z |
| Einpassen (F), Entf | Ansicht einpassen, Auswahl löschen (samt ihrer Beziehungen) |

Beim Zeichnen rastet der Mauszeiger wie in Onshape ein. Auf vorhandene Punkte und den Ursprung (Koinzident), auf Linien,
Kreise und Bögen (Punkt liegt darauf), sonst auf das Raster. Fast waagerechte oder senkrechte Linien bekommen Horizontal
oder Vertikal. Das Fangsymbol erscheint am Mauszeiger.

Beziehungen. Elemente anklicken und dann die Beziehung wählen, oder erst die Beziehung (sie bleibt aktiv) und dann die
Elemente. Mehrere Linien auf einmal werden zum Beispiel alle horizontal oder alle parallel zur ersten.
| Typ | Elemente | Bedeutung |
|---|---|---|
| `coincident` (I) | Punkt und Punkt, Linie, Kreis oder Bogen | Punkte liegen aufeinander oder der Punkt liegt auf dem Element |
| `horizontal` (H), `vertical` (V) | Linie oder zwei Punkte | parallel zur x oder y Achse |
| `parallel`, `perpendicular` | zwei Linien | parallel oder senkrecht |
| `equal` (E) | zwei Linien oder zwei Kreise und Bögen | gleich lang oder gleicher Radius |
| `midpoint` | Punkt und Linie | Punkt in der Mitte der Linie |
| `concentric` | zwei Kreise und Bögen, oder Kreis und Punkt | gleiche Mitte |
| `fix` | Punkt | hält den Punkt an seiner Lage fest |

Maße (Werte in mm, Winkel in Grad)
| Typ | Elemente | Bedeutung |
|---|---|---|
| `length` | Linie | Länge |
| `distance` | zwei Punkte, Punkt und Linie, zwei parallele Linien | Abstand (Lot bei Linien) |
| `hdistance`, `vdistance` | zwei Punkte | waagerechter oder senkrechter Abstand. Entsteht, wenn die Maßzahl neben den beiden Punkten liegt |
| `angle` | zwei Linien | Winkel, an einer gemeinsamen Ecke der Innenwinkel |
| `diameter`, `radius` | Kreis oder Bogen | Durchmesser oder Radius |

Maßzahlen lassen sich ziehen, Doppelklick ändert den Wert. Ein Klick auf ein Beziehungssymbol wählt die Beziehung aus,
Entf löscht sie. In der Liste "Beziehungen" stehen alle Beziehungen und Maße mit Zustand, Wert, an und aus und Löschen.

Zustand und Farben
- blau frei (Freiheitsgrade übrig), schwarz voll bestimmt (im dunklen Modus hell), rot Widerspruch, orange Auswahl
- Statuszeile. Voll bestimmt, Unterbestimmt mit Anzahl der Freiheitsgrade, Überbestimmt (redundant, aber widerspruchsfrei)
  oder Widerspruch. Der Solver benennt die Beziehung, die nicht mehr zu den vorherigen passt, und behält die letzte
  widerspruchsfreie Lösung
- Eine Skizze muss nicht voll bestimmt sein. Die aktuelle Lösung wird verwendet

Gehäuse und Zahnrad
- Gehäuse ist die konvexe Hülle aller normalen Elemente ohne Zahnrad (hell gefüllt). Kreise und Bögen gehen als
  umschreibende Vielecke ein (konservativ), Konstruktionsgeometrie zählt nicht
- Das Zahnrad ist ein achsparalleles Rechteck aus vier Linien mit Rolle `gear` und seiner Mitte auf der x Achse.
  Durchmesser ist die Ausdehnung in x, Breite die in y, Achsabstand der Abstand der Mitte zum Ursprung. Das Werkzeug legt
  dazu eine Konstruktionsdiagonale und einen Mittelpunkt an, das Maß Ursprung zu Mittelpunkt ist der Achsabstand
- Mit Skizze werden `width`, `depth`, `gear_diameter`, `gear_width` und `center_distance` aus der Skizze übernommen
  (auch beim Laden im Kern), die Felder im Reiter Geometrie sind dann gesperrt. `shaft_x`, `gear_gap` und `outline`
  werden ignoriert
- Ohne Skizze zeigt der Reiter eine Vorschau aus den Motorfeldern (voll bemaßtes Rechteck plus Zahnrad). Die erste
  Änderung übernimmt sie in die Konfiguration, "Skizze verwerfen" geht zurück zu den Feldern

Datenformat in der Konfiguration (`motor.sketch`, mm im Stangenrahmen)

```json
"sketch": {
  "points": [[-24, -27], [-12, -27], [-12, -27], [-12, -3], [-18, -15]],
  "entities": [
    {"type": "line", "points": [0, 1], "construction": false, "role": ""},
    {"type": "line", "points": [2, 3]},
    {"type": "circle", "points": [4], "radius": 3.0}
  ],
  "constraints": [
    {"type": "coincident", "refs": ["p1", "p2"]},
    {"type": "horizontal", "refs": ["e0"]},
    {"type": "vertical", "refs": ["e1"]},
    {"type": "length", "refs": ["e0"], "value": 12.0, "label": [-18, -30]},
    {"type": "diameter", "refs": ["e2"], "value": 6.0},
    {"type": "hdistance", "refs": ["o", "p1"], "value": 12.0}
  ]
}
```

Ein Bogen hat `"points": [Mitte, Start, Ende]`, die Linien des Zahnrads haben `"role": "gear"`. Vollständige Skizzen mit
Zahnrad stehen in `examples/sketch_rectangle_dimensions.json` und `examples/sketch_trapezoid_motor.json`.

- `points` ist der Punktpool. Jedes Element besitzt eigene Punkte (Linie zwei, Kreis die Mitte, Bogen Mitte, Start und
  Ende, Punkt einen), Verbindungen sind Koinzident Beziehungen wie in Onshape
- Referenzen sind Texte. `p3` Punkt 3, `e2` Element 2, `o` Ursprung (fest)
- `value` gibt es nur bei Maßen, `label` ist die Lage der Maßzahl (nur Anzeige), `enabled` schaltet aus, `name` ist ein
  freier Name, `at` die Lage eines fixierten Punktes
- Beim Laden werden die Punkte als Startlage genommen und die Beziehungen gelöst, das Modell nutzt immer die gelöste Skizze

Regeln und Grenzen
- Das Gehäuse ist immer konvex (Hülle). Das Zahnrad darf nicht ins Gehäuse ragen (Warnung in der Skizze, Fehler in der
  Konfiguration), der Abstand der Stange zum Gehäuse muss `motor.own_clearance` einhalten
- Höchstens 400 Punkte, 200 Elemente und 400 Beziehungen, der Solver bricht nach 3 s ab
- Der Solver ist reines Python (Levenberg Marquardt mit Minimum Norm Schritten, Rang und Freiheitsgrade über den
  Zeilenraum) im Paket `sketch/`. Die UI ruft ihn über `/api/sketch/solve` (mit optionalem Ziehen) und
  `/api/sketch/from-motor` auf. Strukturänderungen (Element löschen samt Beziehungen) macht die UI, der Kern prüft jede
  Skizze vollständig
- SVG Import erzeugt eine geschlossene Linienkette ohne Maße plus Zahnrad aus den Motorfeldern

## Optimierer

| Name | Verfahren | Aussage |
|---|---|---|
| `pattern_greedy` | Quadrat und Hexagonalraster, gierige Zuordnung, Teilungssuche, lokale Suche | beste gefundene Lösung |
| `anneal_free` | freie Verteilung, Mehrfachstart, Simulated Annealing | beste gefundene Lösung |
| `exhaustive_small` | Backtracking auf diskretem Raster, Fenster der Stangenmitten mit den wenigsten Rasterpunkten | bewiesen nur bezogen auf das Raster und nur ohne Knotenlimit, bis 14 Stangen |
| `periodic_tile` | wiederholendes Lochbild, Motoranordnung je Block per Backtracking (siehe oben) | kleinster gefundener Abstand auf dem Raster |
| `fixed_holes` | vorgegebene Löcher, exaktes Backtracking mit Vorausprüfung, sonst größte Teilmenge | Unmöglichkeit bewiesen, wenn die Suche vollständig war |

Anordnungsziel `compact` packt dicht (kleine Grundfläche), `spread` verteilt gleichmäßig über den Bauraum.
`search.workers` größer 1 startet unabhängige Seeds in getrennten Prozessen und führt die Ergebnisse zusammen.
Mit `search.stagnation_s` endet ein Lauf früh, sobald die bestbewertete Lösung die Zielanzahl erreicht und sich so lange nichts
mehr verbessert. Hat die bestbewertete Lösung wegen der Gewichtung weniger Einheiten als eine andere, steht das in den Hinweisen.

## Parameter

Alle Längen in mm (die UI rechnet auf Wunsch aus cm und inch um). Die Tabelle wird aus `FIELD_META` in `config.py` erzeugt
(`python -m blindsight.docs --update`), dieselbe Quelle füllt die UI Formulare, Tooltips und die Validierung.

<!-- PARAMS:BEGIN -->
| Parameter | Bedeutung | Einheit | Grenzen |
|---|---|---|---|
| `name` | Name. Bezeichnung des Projekts |  |  |
| `target_count` | Gewünschte Anzahl Stangen. So viele Gewindestangen mit Motoren sollen platziert werden |  | >= 1, <= 100000 |
| `clearance` | Sicherheitsabstand. Mindestabstand zwischen allen fremden Bauteilen | mm | >= 0, <= 1000 |
| `tolerance` | Toleranz. Wird zum Sicherheitsabstand addiert (Fertigung, Rundung). Wirksamer Abstand = Sicherheitsabstand + Toleranz | mm | >= 0, <= 1000 |
| `rod.diameter` | Durchmesser. Außendurchmesser des Gewindes | mm | > 0, <= 1000 |
| `rod.stroke` | Maximaler Hub über G0. So weit muss jede Stange oberhalb von G0 ausfahren können, unabhängig von der Motorebene | mm | > 0, <= 100000 |
| `rod.engage_below` | Gewinde unter Zahnradachse (ausgefahren). Mindestgewinde unter der Zahnradachse bei maximalem Ausfahren | mm | >= 0, <= 100000 |
| `rod.engage_above` | Gewinde über Zahnradachse (eingefahren). Mindestgewinde über der Zahnradachse bei vollem Einfahren | mm | >= 0, <= 100000 |
| `rod.length_tolerance` | Längenzuschlag. Zusätzlicher Sicherheitszuschlag der Stangenlänge | mm | >= 0, <= 100000 |
| `rod.retract_depth` | Spitze eingefahren unter G0. Tiefe der Stangenspitze unter G0 bei vollem Einfahren (0 = bündig) | mm | >= 0, <= 100000 |
| `rod.hole_clearance` | Radiales Lochspiel. Spiel der Durchgangslöcher in den Ebenen (je Seite) | mm | >= 0, <= 1000 |
| `motor.width` | Breite (x). Gehäusebreite quer zur Welle | mm | > 0, <= 10000 |
| `motor.depth` | Tiefe (y, Wellenrichtung). Gehäusetiefe entlang der Welle | mm | > 0, <= 10000 |
| `motor.height` | Höhe (z). Gehäusehöhe senkrecht zur Ebene | mm | > 0, <= 10000 |
| `motor.shaft_x` | Abtriebsachse, x Versatz. Seitlicher Versatz der Abtriebsachse zur Gehäusemitte | mm | >= -10000, <= 10000 |
| `motor.axis_height` | Achshöhe über Montagefläche. Höhe der Abtriebsachse über der Montagefläche | mm | >= 0, <= 10000 |
| `motor.gear_diameter` | Zahnrad Durchmesser. Außendurchmesser des Antriebszahnrads | mm | > 0, <= 10000 |
| `motor.gear_width` | Zahnrad Breite. Axiale Breite des Zahnrads | mm | > 0, <= 10000 |
| `motor.gear_gap` | Abstand Gehäuse zu Zahnrad. Axialer Abstand zwischen Gehäusekante und Zahnrad | mm | >= 0, <= 10000 |
| `motor.center_distance` | Achsabstand Zahnrad zu Stange. Abstand der Abtriebsachse zur Stangenachse. Der Eingriff ist nur über diesen Abstand modelliert | mm | >= 0, <= 10000 |
| `motor.center_distance_min` | Achsabstand min (optional). Untergrenze, wenn der Optimierer den Achsabstand variieren darf | mm | >= 0, <= 10000 |
| `motor.center_distance_max` | Achsabstand max (optional). Obergrenze, wenn der Optimierer den Achsabstand variieren darf | mm | >= 0, <= 10000 |
| `motor.center_distance_steps` | Achsabstand Stufen. Anzahl der Stufen zwischen min und max (1 = nur nominal) |  | >= 1, <= 50 |
| `motor.own_clearance` | Eigenabstand Gehäuse zur Stange. Mindestabstand des Gehäuses zur eigenen Stange | mm | >= 0, <= 1000 |
| `motor.mount` | Montage. Motor steht auf der Ebene oder hängt darunter |  | `top` / `bottom` |
| `stack.n_motor_planes` | Anzahl Motorebenen. Anzahl der Ebenen G1 bis Gn, keine feste Obergrenze |  | >= 1, <= 1000 |
| `stack.mode` | Abstandsmodus. Wie die Ebenenhöhen angegeben werden |  | `uniform` / `gaps` / `distances` |
| `stack.uniform_spacing` | Einheitlicher Ebenenabstand. Abstand zwischen allen Ebenen (Modus uniform) | mm | > 0, <= 100000 |
| `stack.gaps` | Einzelabstände (Liste). Abstände G0-G1, G1-G2, ... (Modus gaps) | mm |  |
| `stack.distances` | Abstände zu G0 (Liste). Abstand jeder Motorebene zu G0, aufsteigend (Modus distances) | mm |  |
| `stack.thickness` | Dicke Motorebenen. Plattendicke der Ebenen G1 bis Gn | mm | > 0, <= 1000 |
| `stack.g0_thickness` | Dicke G0. Plattendicke der oberen Referenzebene | mm | > 0, <= 1000 |
| `stack.thicknesses` | Dicke je Ebene (Liste, optional). Eigene Dicke für jede Motorebene, überschreibt die gemeinsame Dicke | mm |  |
| `stack.allowed_planes` | Erlaubte Motorebenen (Liste, leer = alle) (optional). Nur diese Ebenen dürfen Motoren tragen |  |  |
| `bounds.width` | Breite (x). Ausdehnung des Bauraums in x ab dem Ursprung unten links | mm | > 0, <= 1e+06 |
| `bounds.height` | Höhe (y). Ausdehnung des Bauraums in y ab dem Ursprung unten links | mm | > 0, <= 1e+06 |
| `bounds.edge_margin` | Sperrrand für alle Bauteile. Zusätzlicher Abstand aller Bauteile zum Plattenrand | mm | >= 0, <= 1e+06 |
| `bounds.parts_in_bounds` | Über den Plattenrand ragen dürfen. Ob Motoren und Zahnräder über die Platte hinausragen dürfen |  | `all` / `rods` |
| `bounds.border` | Randbereich nur für Motoren. Am Plattenrand ein Streifen, in den nur Motoren ragen dürfen, die Löcher bleiben innerhalb |  |  |
| `bounds.border_width` | Breite des Randbereichs. So breit ist der Streifen am Plattenrand, in den nur Motoren ragen dürfen | mm | >= 0, <= 1e+06 |
| `search.optimizer` | Optimierer. Suchstrategie |  | `pattern_greedy` / `anneal_free` / `exhaustive_small` / `periodic_tile` / `pattern_holes` / `fixed_holes` |
| `search.layout_goal` | Anordnungsziel. compact packt dicht (kleine Fläche), spread verteilt gleichmäßig über den ganzen Bauraum |  | `compact` / `spread` |
| `search.patterns` | Muster (square, hex_x, hex_y). Verteilungsstruktur der Kandidaten |  |  |
| `search.fixed_pitch` | Feste Teilung (optional). Nur diese Rasterteilung verwenden statt sie zu suchen | mm | > 0, <= 100000 |
| `search.angle_step` | Winkelschritt (Grad). Raster der zulässigen Motorwinkel |  | > 0, <= 360 |
| `search.angle_min` | Winkel von (Grad). Kleinster Motorwinkel |  | >= -3600, <= 3600 |
| `search.angle_max` | Winkel bis (Grad, exklusiv). 360 = voller Kreis |  | >= -3600, <= 3600 |
| `search.allowed_angles` | Nur diese Winkel (Liste, leer = Raster) (optional). Explizite Liste erlaubter Motorwinkel |  |  |
| `search.time_limit_s` | Zeitlimit (s). Maximale Rechenzeit |  | > 0, <= 86400 |
| `search.max_candidates` | Max. Kandidaten. Maximale Anzahl geprüfter Platzierungen |  | >= 1 |
| `search.seed` | Seed. Zufallsstartwert für reproduzierbare Läufe |  | >= 0 |
| `search.top_k` | Anzahl Lösungen. Wie viele beste Lösungen behalten werden |  | >= 1, <= 50 |
| `search.refine_fraction` | Anteil lokale Suche. Zeitanteil der Verfeinerung (0 bis 0.9) |  | >= 0, <= 0.9 |
| `search.stagnation_s` | Stagnation (s, optional). Beenden, wenn das Ziel erreicht ist und sich so lange nichts verbessert |  | > 0, <= 86400 |
| `search.pattern` | Muster. Wiederholendes Muster. Form des Lochbilds. Die Motoranordnung je Loch sucht das Programm und wiederholt sie |  | `square` / `centered_square` / `hex` / `hex_rotated` / `staggered` / `rectangle` / `free` / `custom` |
| `search.pattern_task` | Aufgabe. Was das Programm mit dem Muster erreichen soll |  | `dense` / `count` / `pitch` |
| `search.pattern_fill` | Ganze Platte füllen. Statt der gewünschten Anzahl so viele Löcher setzen, wie auf die Platte passen |  |  |
| `search.pattern_pitch` | Lochabstand (optional). Wiederholendes Muster. Abstand zum nächsten Loch. Leer heißt automatisch (kompakt kleinster, verteilt größter passender Abstand). Bei eigener Kachel die Kachelbreite | mm | > 0, <= 100000 |
| `search.pattern_pitch_y` | Zweiter Abstand (optional). Rechteck. Abstand in y. Versetzte Reihen. Reihenabstand. Leer heißt gleich dem Lochabstand (Rechteck) bzw. dicht wie Kreise (versetzte Reihen) | mm | > 0, <= 100000 |
| `search.max_block_holes` | Größter Wiederholblock. Wiederholendes Muster. Höchstens so viele Löcher umfasst der Block, nach dem sich die Motoranordnung wiederholt |  | >= 1, <= 36 |
| `search.tile_rods` | Schrauben je Kachel. Nur Muster frei. So viele Schrauben enthält eine Kachel, die sich über den Bauraum wiederholt (Ebene und Motorwinkel wiederholen sich mit) |  | >= 1, <= 8 |
| `search.tile_width` | Kachelbreite (optional). Nur Muster frei. Breite der Kachel in x, leer heißt kleinste passende Breite suchen | mm | > 0, <= 100000 |
| `search.tile_height` | Kachelhöhe (optional). Nur Muster frei. Höhe der Kachel in y, leer heißt kleinste passende Höhe suchen | mm | > 0, <= 100000 |
| `search.tile_step` | Musterraster. Wiederholendes Muster. Raster, auf dem Lochabstände und Kachelgrößen gesucht werden | mm | > 0, <= 100 |
| `search.workers` | Parallele Läufe. Anzahl Prozesse für unabhängige Seeds (1 = ohne Parallelisierung) |  | >= 1, <= 64 |
| `search.weights.count` | Anzahl Stangen. Gewicht des Ziels Anzahl |  | >= 0, <= 1000 |
| `search.weights.area` | Kleine Grundfläche. Gewicht des Ziels Grundfläche |  | >= 0, <= 1000 |
| `search.weights.uniformity` | Gleichmäßige Verteilung. Gewicht der gleichmäßigen Nachbarabstände |  | >= 0, <= 1000 |
| `search.weights.regularity` | Regelmäßiges Muster. Gewicht der Quadrat oder Hexagonalordnung |  | >= 0, <= 1000 |
| `search.weights.layers` | Wenig Ebenen. Motoren möglichst auf die oberen Ebenen legen, damit weniger Platten nötig sind |  | >= 0, <= 1000 |
| `search.weights.border` | Kleiner Rand. Motoren ragen möglichst wenig in den Randbereich |  | >= 0, <= 1000 |
| `search.weights.alignment` | Saubere Ausrichtung. Die Richtungen der Motoren wiederholen sich regelmäßig |  | >= 0, <= 1000 |
<!-- PARAMS:END -->

Weitere Felder ohne Tabellenzeile
- `stack.mount_zones` Montagebereiche je Ebene, zum Beispiel `{"1": [[0, 0, 60, 120]]}`
- `stack.max_per_plane` maximale Motoranzahl je Ebene, zum Beispiel `{"1": 6}`
- `stack.plane_angles` erlaubte Winkel je Ebene, zum Beispiel `{"3": [0, 90, 180, 270]}`
- `motor.outline` konvexes Polygon des Gehäuses im lokalen Motorsystem, ersetzt das Rechteck
- `motor.sketch` Skizze aus Linien, Kreisen und Bögen mit Beziehungen und Maßen im Stangenrahmen, ersetzt Rechteck, `outline` und die Zahnradfelder (siehe Abschnitt Motor Skizze)
- `search.custom_tile` eigene Kachel (`width`, `height`, `holes` [[x, y], ...], `scalable`) für das Muster `custom`
- `holes` feste Löcher von G0 [[x, y], ...] in mm für den Optimierer `fixed_holes`
- `obstacles` feste Hindernisse (`shape` rect oder circle, `x`, `y`, `w`, `h`, `r`, `angle`, optional `z0`, `z1`, `plane` für eine Sperrzone nur auf einer Motorebene)

Beispiele in `examples/` (im UI per Dropdown ladbar)
- `small_hex.json` kleine Standardaufgabe
- `spread_even.json` gleichmäßig über den Bauraum verteilt
- `polygon_motor_variable_center_distance.json` gezeichnete Motorkontur, Achsabstand wird mitoptimiert
- `plane_rules.json` Kapazität, Winkel, Sperrzone und Dicke je Ebene
- `exact_small.json` exakte Suche auf dem Raster
- `repeating_tile.json` wiederholendes Muster Würfel Fünf
- `pattern_hex_spread.json` hexagonales Muster gleichmäßig über den Bauraum verteilt
- `fixed_holes_grid.json` feste Löcher 3 x 3, Motorlage je Loch wird bestimmt
- `sketch_trapezoid_motor.json` Trapez Motor als Skizze mit Parallel, Winkel, Länge, Abstand und Zahnrad
- `sketch_rectangle_dimensions.json` Rechteck als voll bemaßte Skizze mit Zahnrad
- `three_levels_mixed_gaps.json` ungleiche Ebenenabstände mit Hindernis
- `bottom_mount_two_levels.json` Motoren unter den Ebenen
- `area_too_small.json` Bauraum zu klein, ehrliche Teillösung
- `infeasible_motor_too_tall.json` keine Lösung, Gründe werden gemeldet

## Export

Schraubenpositionen (JSON, `blindsight.rod_positions`). Je Ebene G0 bis Gn die Stangen, getrennt nach `always_present`
(Stange steckt in jeder Lage des Hubs in der Ebene), `present_when_retracted` (nur eingefahren, tiefe Ebenen),
`present_when_extended` und `present_during_travel`. Koordinaten in mm ab (0, 0) unten links. Dazu `motors` mit Ebene,
Winkel, Achsabstand und Lage der Zahnradachse je Stange. CLI `--rods datei.json`.

SVG im Maßstab 1:1 (`width` und `height` in mm, `viewBox` in mm). Gruppe `top` ist die Draufsicht, `plane-N` je Motorebene mit
Gehäusen, Zahnrädern, Stangen und Durchgangslöchern. Die Y Achse ist gespiegelt (Ursprung links unten im Bauraum).
Das SVG ist ein geometrisches Ergebnis, kein fertiges PCB Layout. JSON enthält alle Konturen und Z Werte.
DXF (R12, mm) hat Layer `BOUNDS`, `OBSTACLES`, `TOP_RODS` sowie je Ebene `Gn_MOTOR`, `Gn_GEAR` und `Gn_HOLES`.
Die Bohrliste (CSV) enthält je Ebene alle Durchgangslöcher (jede Stange braucht ein Loch in jeder Ebene, die sie durchquert,
auch die eingefahrene Stange unterhalb ihrer Motorebene).

## Oberfläche

- Kopfzeile. Sprachwahl Deutsch, Englisch, Französisch (gemerkt im Browser, Start in der Browsersprache)
- Hilfe. Komplexere Felder und Bereiche haben einen i Knopf mit einer Erklärung (Texte in den Katalogen, Felder unter `field.<pfad>.help`, Bereiche unter `ui.help.*` mit `data-help` in `index.html`)
- Einfach zuerst. Selten geänderte Felder liegen eingeklappt unter "Weitere Einstellungen" (die Zusammenfassung zeigt, wie viele davon geändert sind, ein Fehler klappt sie auf). Felder, die zur aktuellen Wahl nicht passen, sind ausgeblendet (zum Beispiel nur das Abstandsfeld des gewählten Abstandsmodus). Die Liste der eingeklappten Felder steht in `ADVANCED_FIELDS` (`js/ui/forms.js`)
- Rückfragen vor Standardwerte, Skizze verwerfen und Alle Löcher löschen. Leere Tabellen und der Reiter Ergebnisse ohne Lauf sagen, was als Nächstes zu tun ist
- Tastatur. Alle Knöpfe sind mit Tab erreichbar (auch die Dateiauswahl), der Fokus ist sichtbar, Symbolknöpfe und Auswahllisten haben Beschriftungen für Screenreader
- Reiter Geometrie. Formulare mit Tooltips, Fehler direkt am Feld, Motor Vorschau mit Stange im Ursprung,
  SVG Import mit Maßstabsabfrage, lokale Motor Bibliothek
- Reiter Motor Skizze. Motor wie in Onshape zeichnen, Beziehungen und Maße setzen, Zahnrad und Achsabstand (siehe oben)
- Reiter Ebenen. Abstandsmodi, Tabelle je Ebene (erlaubt, Kapazität, Winkel, Dicke), berechnete Stangenlängen und Seitenschnitt
- Reiter Bauraum. Rand, Hindernisse, Sperrzonen, Montagebereiche
- Reiter Lochbild. Generator für feste Löcher und eigene Kacheln (siehe oben)
- Reiter Optimierung. Gewichte mit Reglern und Voreinstellungen, Suchparameter (nur die zum Optimierer und Muster passenden), Fortschritt, Live Vorschau der besten Lösung
- Reiter Ergebnisse. Erste Zeile Ansicht (Lösung, Draufsicht, Einzelebene, Seitenschnitt, räumliche Ansicht mit der Maus drehen,
  Abstände, manuelles Bearbeiten mit sofortiger Prüfung), zweite Zeile Dateien (Export SVG, Schraubenpositionen, DXF, CSV, JSON,
  Ergebnis speichern und laden). Daneben Kennzahlen, Kollisionen, engste Stellen und Vergleich der Top Lösungen

Server Sicherheit. Der Server bindet standardmäßig nur an 127.0.0.1, prüft Host und Origin (Schutz gegen fremde Webseiten,
`Origin: null` wird abgewiesen), nimmt POST nur als `application/json` an, weist NaN und zu tief verschachteltes JSON ab und
begrenzt die Größe von Anfragen. Fehlerantworten haben immer die Form `{"error": ..., "errors": [...]}`.

## Mechanische Annahmen und Einschränkungen

- Das Zahnrad ist ein Quader als Einhüllende, ohne Zahngeometrie. Der Eingriff steckt nur im Achsabstand. Ob das reale Zahnrad
  in das reale Gewinde passt, muss mit den echten Bauteilen geprüft werden
- Standardwerte sind Platzhalter, keine Herstellerdaten
- Gehäuse sind konvex (Rechteck, konvexes Polygon oder Hülle der Skizze). Nicht konvexe SVG Konturen werden durch ihre Hülle ersetzt
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
