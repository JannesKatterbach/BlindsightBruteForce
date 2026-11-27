# Motormatrix Platine

Plan für den Prototyp der Lippenstift Ebene. Jeder N20 Motor (12 V, 140 U/min, Hall Encoder) sitzt unter seinem Pin und wird mit sechs Kabeln auf diese Platine gelötet.

- `index.html` interaktive Seite mit Verkabelungsdiagramm, Stückliste, ESP32 Grundgerüst und ZIP Download. Im Browser öffnen, Reihen und Spalten einstellen (1 bis 40)
- `kicad-matrix.js` erzeugt den KiCad Schaltplan, läuft im Browser und in Node
- `kicad/` fertiger Schaltplan für 14 x 14 (KiCad 7 Format, KiCad 8 und 9 lesen es ein)

Aufbau
- Je Motor ein Treiber DRV8220DRL und sechs Lötpads
- Ausgangskette aus 74HC595 setzt IN1 und IN2 aller Treiber, Eingangskette aus 74HC165 liest A und B aller Encoder
- Je Reihe ein 74HC244 als Puffer für die Takte
- ESP32 braucht 7 Signale und GND

Geprüft mit `kicad-cli sch export netlist` für 1 x 1, 2 x 3, 3 x 5, 14 x 14 und 40 x 40. Jede Verbindung von Treiber, Lötpads, Schieberegistern, Ketten und Takten stimmt mit dem Plan überein.
