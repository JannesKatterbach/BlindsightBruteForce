# Changelog

## 0.9.0
Rückmeldung zum geführten Ablauf
- Muster mit zwei einfachen Fragen statt Aufgabe und "Ganze Platte füllen". Wie viele Löcher (so viele wie auf die Platte
  passen oder genau N) und welcher Lochabstand (so klein wie möglich, so groß wie möglich oder fest). Unsinnige Kombinationen
  sind ausgegraut, das Feld heißt hier "Anzahl Löcher". Neu ist genau N mit festem Abstand
- Ebenen fest oder nicht fest in den Grundlagen. Nur bei nicht fest gibt es das Ziel Wenig Ebenen, und Ergebnis und Export
  enthalten dann nur die genutzten Ebenen mit passenden Stangenlängen
- Ziele frei einstellbar. Regler und Zahlenfeld je Ziel, Summe mit Anzeige (es fehlen bzw. zu viel), Knopf "Auf 100 %
  bringen", Start erst bei 100 %. Kleiner Rand ist immer beweglich, ohne Randbereich steht ein Hinweis daneben. Gewichte sind
  jetzt Prozent, ältere Dateien werden beim Laden im gleichen Verhältnis umgerechnet
- Ergebnisbild. Stangen in der Textfarbe (im dunklen Modus gut sichtbar), engste Stellen als kleiner Punkt mit Tooltip statt
  Ring, Platte mit Lochbereich und Randbereich eingezeichnet, Blockgrenzen an der Platte abgeschnitten
- Neue Ergebnisseite "Muster kacheln". Der Block von Muster 2a wird nx x ny mal aneinandergesetzt, die Platte wird passend
  gerechnet. Übernehmen als Ergebnis, Block als Datei oder als eigene Kachel speichern. API `/api/tile`
- Klick auf einen Schritt mit ! springt zum ersten Feld mit Fehler
- Der Muster Modus füllt standardmäßig die ganze Platte

## 0.8.0
Geführter Ablauf mit Modi und Zielen
- Die Oberfläche führt in sieben Schritten von links nach rechts (Grundlagen, Motor, Modus, Platte und Rand, Löcher bzw.
  Muster, Ziele und Berechnen, Ergebnis), mit Zurück und Weiter, Schrittleiste mit ✓ und ! und freiem Springen. Motor Maße
  und Motor Skizze sind ein Schritt mit Umschalter
- Moduswahl als Karten. Löcher vorgeben (feste Löcher, direkt im Editor eingegeben), Muster wählen und eingeklappt Frei
  verteilen (die bisherigen freien Verfahren)
- Muster mit Bildkarten und der Frage "Was wiederholt sich?". 2a Löcher und Motoren als Block (wie bisher), 2b neu nur die
  Löcher mit einzeln gedrehten Motoren (`pattern_holes`)
- Aufgaben im Muster Modus statt Anordnungsziel und festem Abstand. So dicht wie möglich (Zielanzahl oder ganze Platte),
  feste Anzahl verteilt, fester Abstand prüfen
- Randbereich nur für Motoren in allen Modi. Die Löcher bleiben innen, die Motoren dürfen in den Streifen ragen, nichts ragt
  über die Platte. Vorschau von Lochbereich und Randbereich
- Ziele mit Prioritäten in Prozent für Löcher und Muster. Wenig Ebenen, Kleiner Rand, Saubere Ausrichtung, dazu
  Voreinstellungen. Jedes bediente Loch hat Vorrang vor den Zielen. Feste Löcher und Muster 2b verbessern die Ziele nach der
  ersten gültigen Lösung
- Ergebnis zeigt genutzte Ebenen und die Tiefe im Randbereich, eine Zusammenfassung steht vor dem Start
- Neue Beispiele `pattern_individual_motors.json` und `fixed_holes_edge_strip.json`

Änderungen
- Der Knopf "Für Optimierung verwenden" entfällt, Löcher und eigene Kachel gehen direkt in die Konfiguration
- Dateien mit `periodic_tile` bekommen beim Laden eine Aufgabe (`spread` wird verteilt, fester Abstand wird prüfen)
- Die Oberfläche startet im Muster Modus, der Kern behält die freie Verteilung als Standard

## 0.7.0
Oberfläche einfacher (Prüfung mit den Skills usability-psychologist und ui-ux-pro-max, die Motor Skizze bleibt wie Onshape)
- Selten geänderte Felder liegen eingeklappt unter "Weitere Einstellungen" (Geometrie und Optimierung). Die Zusammenfassung
  zeigt, wie viele davon geändert sind, ein Fehler in einem eingeklappten Feld klappt den Bereich auf
- Ebenen zeigen nur das Abstandsfeld des gewählten Abstandsmodus
- Reiter Ergebnisse ohne Lauf mit Knöpfen "Zur Optimierung" und "Ergebnis laden" (Laden war vorher erst nach einem Lauf
  erreichbar). Die Werkzeugleiste ist in eine Zeile Ansicht und eine Zeile Dateien geteilt
- Leere Tabellen (Hindernisse, Montagebereiche, Löcher) zeigen einen Hinweis statt einer leeren Kopfzeile
- Rückfrage vor Standardwerte, Skizze verwerfen und Alle Löcher löschen
- Barrierefreiheit. Sichtbarer Tastaturfokus, Dateiknöpfe mit Tab erreichbar, Reiter mit ARIA Rollen, Symbolknöpfe und
  Auswahllisten mit Beschriftung, Fehlerbanner wird vorgelesen

Fehler behoben
- Zurücksetzen einer Bearbeitung im Reiter Ergebnisse konnte von einer verzögerten Prüfung überschrieben werden, die beim
  Verlassen des bearbeiteten Feldes ausgelöst wurde (selten auch ein Fehler im Browser). Ausstehende Prüfungen werden jetzt
  beim Zurücksetzen und beim Laden eines neuen Ergebnisses verworfen

Code (ohne Änderung der Funktionen)
- Toter Code entfernt (unbenutzte Hilfsfunktionen, Konstanten, Altnamen und Importe), CSS ohne Reste der alten Skizzen Tabellen
- Lange Funktionen zerlegt. Skizzen Solver (Lösen und Auswerten getrennt), Prüfung der Ebenen, Typprüfung der
  Konfiguration als Tabelle, SVG Import (Maßstab und Form), Lochbild Parser, Regelprüfung im Layout, Bemaßungen und
  Zeichenwerkzeuge der Skizze
- Gemeinsame Bausteine in der Oberfläche für Dateiauswahl, JSON Download, leere Tabellen und Löschknöpfe

## 0.6.0
Neue Funktionen
- Motor Skizze neu nach dem Vorbild von Onshape. Elemente Linie (als Kette), Rechteck, Kreis, Bogen und Zahnrad,
  Konstruktionsgeometrie (Q). Beim Zeichnen rastet der Mauszeiger auf Punkte, Ursprung, Linien und Kreise ein und setzt
  Koinzident, fast waagerechte oder senkrechte Linien bekommen Horizontal oder Vertikal
- Beziehungen Koinzident, Horizontal, Vertikal, Parallel, Senkrecht, Gleich, Mittelpunkt, Konzentrisch und Fixieren. Erst
  auswählen und dann die Beziehung, oder erst die Beziehung (bleibt aktiv) und dann die Elemente. Symbole an den Elementen
- Ein Bemaßungswerkzeug für Länge, Abstand (auch waagerecht oder senkrecht), Winkel, Durchmesser und Radius. Maßzahl mit
  der Maus platzieren, Wert eintippen, Doppelklick ändert, Maßzahlen lassen sich verschieben
- Ziehen von Punkten, Linien und Kreisen hält alle Beziehungen ein. Farben wie in Onshape (blau frei, schwarz bestimmt,
  rot Widerspruch), Statuszeile mit Freiheitsgraden, einklappbare Liste der Beziehungen
- Das Zahnrad wird in der Skizze gezeichnet. Durchmesser, Breite und Achsabstand kommen aus der Skizze, der Achsabstand
  ist ein Maß vom Ursprung zur Zahnradmitte. Das Gehäuse ist die konvexe Hülle aller normalen Elemente

Änderungen
- Neues Skizzenformat `motor.sketch` mit `points`, `entities` und `constraints` (Referenzen `p3`, `e2`, `o`). Die alten
  Polygon Skizzen mit Seiten Constraints werden nicht mehr gelesen, die Beispiele sind umgestellt
- Mit Skizze sind auch `gear_diameter`, `gear_width` und `center_distance` gesperrt und kommen aus der Skizze
- Die Seiten und Punkte Tabellen und die Werkzeugleiste links entfallen. API nur noch `/api/sketch/solve` und
  `/api/sketch/from-motor`, `hull`, `insert` und `delete` entfallen
- SVG Import erzeugt eine Linienkette plus Zahnrad im neuen Format

## 0.5.0
Neue Funktionen
- Wiederholendes Muster (`periodic_tile`) neu. Regelmäßige Lochbilder Quadrat, Würfel Fünf, Hexagonal (auch 90 Grad gedreht),
  versetzte Reihen und Rechteck mit festem oder gesuchtem Lochabstand, dazu die frühere freie Kachel (Schrauben je Kachel) und
  eigene Kacheln aus dem Lochbild Generator (fest oder skalierbar). Die Motoranordnung wiederholt sich im kleinsten gültigen
  Block, die Zielanzahl wird genau erreicht (keine Rundung auf ganze Kacheln mehr)
- Feste Löcher (`fixed_holes`). Für vorgegebene G0 Löcher werden Ebene, Motorwinkel und Achsabstand bestimmt, exakt mit
  Nachweis der Unmöglichkeit oder als größte Teillösung mit Grund je nicht bedientem Loch
- Lochbild Dateien `blindsight.holes` und neuer Reiter Lochbild (Tabelle, Einfügen aus Text oder Excel, Muster füllen,
  Klicken in der Vorschau, Prüfung durch den Kern, Download, direkte Übernahme). CLI `--holes`, API `/api/holes/parse` und
  `/api/holes/check`
- Export der Schraubenpositionen je Ebene als JSON (G0 bis Gn, immer da, nur eingefahren da, nur ausgefahren da) mit
  Motorlage je Stange. CLI `--rods`
- i Knöpfe mit Erklärungen an allen komplexeren Feldern und Bereichen der Oberfläche, in allen drei Sprachen
- Sprachen Deutsch, Englisch, Französisch für Oberfläche und alle Meldungen des Kerns. Sprachwahl im Kopf, Server antwortet
  je Anfrage in der gewählten Sprache (auch für frühere Ergebnisse), CLI `--lang`

Änderungen
- Alles in mm, Ursprung (0, 0) unten links. Der Bauraum hat nur noch `width` und `height`, die Einheitenwahl der UI entfällt
- Code, Kommentare und Docstrings auf Englisch, sichtbare Texte nur noch in den Katalogen
- Der Optimierer Reiter zeigt nur die Felder, die zum gewählten Optimierer und Muster passen
- Konfigurationen älterer Versionen mit `bounds.xmin` usw. oder `search.tile_rods` ohne Muster müssen angepasst werden
  (`bounds.width`, `bounds.height`, `search.pattern: "free"`)

## 0.4.0
Überarbeitung für Lesbarkeit und Erweiterbarkeit, ohne neue Funktionen. Alle bisherigen Abläufe, Dateiformate, API Pfade und
öffentlichen Namen bleiben erhalten.

Aufbau
- Register statt verstreuter Fallunterscheidungen. Constraint Typen (`sketch/constraints.py`), Muster, Teilziele der Bewertung,
  Optimierer (`optimizers/registry.py`), Exportformate und Einheitenregeln (`layout.UNIT_RULES`). Tests prüfen, dass Register
  und Konfigurationsoptionen übereinstimmen
- Skizze als Paket `sketch/` (Register, Struktur, Polygon, Numerik, Solver, Motor), Optimierer mit Template Methode
  `Optimizer.run` und abstraktem `search`, lokale Suche als eigene Klasse
- Server mit Routentabelle, `Response` Objekt und einheitlicher Fehlerform, `analyze` in `analysis.py`
- Oberfläche in klassische Skripte unter `web/static/js` aufgeteilt (Kern, Reiter, Skizze), Schema gestützte Gewichte,
  Exportformate und Constraint Bezeichnungen
- Gemeinsame Bausteine. Geometrie Hilfen, Fehlerklassen, zentrale Toleranzen, benannte Konstanten
- Sichtbare Texte und Meldungen mit Umlauten
- `blindsight` startet die Web UI, `blindsight-cli` die Kommandozeile, Version an einer Stelle (`blindsight.__version__`)
- README mit Abschnitten Konventionen und Erweitern, Exitcodes der Kommandozeile

Behobene Fehler, Rechenkern
- Hexagonalraster war verzerrt (Nachbarn nur 0,9 x Teilung)
- Skizze. `ok=False` ohne Meldung nach der Konfliktdiagnose, Ziehen bei Punkten im Uhrzeigersinn bewegte den falschen Punkt,
  abgelehntes Ziehen lieferte eine verschobene Startlage, `diagnose=False` lieferte keinen Hinweis, Selbstschnitt über die
  Windungszahl blieb ohne Meldung, nicht iterierbare Eingaben stürzten ab, `insert_point` nahm t außerhalb 0 bis 1,
  `enabled` wurde nicht geprüft, die Motorskizze wurde je Lauf mehrfach gelöst (jetzt zwischengespeichert)
- Konfiguration. Bool Felder und `X | None` Typen wurden nicht geprüft, überlappende Ebenen und unbekannter Stapelmodus
  bestanden die Validierung, Achsabstand min ohne max und Nominalwert außerhalb des Bereichs wurden still hingenommen,
  Winkellisten konnten 0 und 360 doppelt enthalten
- Diagnose prüfte nur den nominalen Achsabstand und meldete fälschlich, dass keine einzelne Einheit passt
- Obergrenze der Anzahl war keine strenge Schranke (0, obwohl eine Stange passt). Jetzt Ungleichung von Oler
- Regelmäßigkeit sprang zwischen einer und zwei bis vier Einheiten
- "Nur n von Ziel" erschien, obwohl Anordnungen mit voller Anzahl gefunden wurden
- Lokale Suche. Abkühlung bezog sich auf das Gesamtzeitlimit, Zwischenstände fehlten, leeres Startlayout brach ab
- Exakte Suche erzeugte alle Fenster vorab, Rasterpunkte wurden erst nach der Erzeugung begrenzt
- Parallele Läufe. Signatur ohne Achsabstand, Seed Überlauf, Diagnosen mehrfach, Stagnationsstatus ging verloren,
  Kandidatenzähler blieb 0, Beenden über interne Attribute
- `free_height_above(0)` griff auf die letzte Ebene zu

Behobene Fehler, Server, Import, Export, Kommandozeile
- Abstürze statt 4xx (SVG Import mit Liste, Zahl oder Text als Maßstab, `t: null`, tief verschachteltes JSON), allgemeiner
  500 Fang, NaN in Anfragen wird abgewiesen, Antworten sind immer gültiges JSON
- Sicherheit. `Origin: null` wird abgewiesen, POST nur als `application/json`
- `Content-Disposition` kommt aus dem Exporter, unbekannte Läufe sind `JobNotFound` statt pauschal jedes `KeyError`,
  Platzierungslimit vor dem Einlesen, IPv6 Hosts, feste MIME Typen
- SVG Pfade mit Kurven werden abgewiesen statt falsch gelesen, `motor_from_svg` kopiert tief
- Dienst. Zugriffe unter Sperre, Abbruch endet immer als `cancelled`, Herunterfahren wartet auf die Threads
- Kommandozeile. `--time 0` wurde ignoriert, Kodierungs und Schreibfehler endeten als Traceback
- SVG Export zeichnete Nachbarabstände doppelt, Zahlen konnten als -0 erscheinen

Behobene Fehler, Oberfläche
- Skizze. Späte Antwort nach dem Loslassen warf einen TypeError, Änderungen konnten sich überholen, Verlauf wuchs
  unbegrenzt, Strg+Umschalt+Z machte rückgängig
- Ebenentabelle folgte der Ebenenzahl nicht, doppelte Editoren für erlaubte Ebenen und Dicken, Eingaben gingen bei einem
  zweiten change Ereignis verloren
- Bearbeiten. Klick ohne Bewegung markierte das Ergebnis als bearbeitet, Zurücksetzen bei geladenem Ergebnis ging nicht,
  x und y ohne Einheit
- Alte Ergebnisanzeigen blieben bei leerem Ergebnis, Tooltips gingen verloren, Abfragen überlappten
- Unmaskierte Werte in Tabellen, leere Pflichtfelder wurden zu null, Zone mit leerer Ebene wurde zum Schlüssel NaN,
  `zoneAdd` stürzte bei `null` ab, Gewichtsregler kappte Werte über 20, Export immer als Text, gleiche Datei lud nicht erneut

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
