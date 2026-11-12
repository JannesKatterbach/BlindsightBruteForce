# Variante Rohrantrieb (Rohr mit Innengewinde)

Stand. Technische Untersuchung und CAD Umsetzung als druckbare Kachel in Onshape (Abschnitte 6 und 14). Alle Maße in mm.

Diese Datei untersucht den Vorschlag, die Gewindestange nicht mehr seitlich über ein Zahnrad anzutreiben, sondern über ein
drehendes Rohr mit Innengewinde und einem Motor darunter. Grundlage sind das Repository (README, `docs/ERKLAERUNG.md`) und
die Antworten des Teams. Werte, die nirgends festgelegt sind, sind als **Annahme** gekennzeichnet.

![Bild 9. Variante Rohrantrieb im Schnitt](images/09_rohrantrieb_schnitt.svg)

*Bild 9. Schnitt durch eine Kachel, maßstäblich nach dem Onshape Feature (Abschnitt 6).*

## Kurzfassung

- Das Prinzip funktioniert. Es ist eine bekannte Bauform (rotierende Mutter, hebende Spindel), wie in Linearschrittmotoren
  ohne Verdrehsicherung und in Spindelhubgetrieben mit hebender Spindel
- Die Stange hält Last ohne Strom (selbsthemmendes Gewinde). Mit einem schnellen N20 schafft sie bei 2 cm/s etwa 10 bis 15 N.
  Das reicht für eine aufgelegte Hand mit Unterarm deutlich (Abschnitt 5)
- Jede Stange ist eine eigene, gedruckte **Kachel** mit Motor, Lager, Rohr und Führung. Die Kacheln stehen ohne Lücke
  nebeneinander, Raster **14 x 12 mm**, in beliebiger Anzahl. Ein Grundrahmen und ein Abdeckrahmen halten das Feld
- Verdrehsicherung über zwei Abflachungen an der Stange (Doppel D) im Schlitz des gedruckten Deckels. Der Motor treibt das Rohr
  über seine D Welle in einer D Bohrung an (Formschluss wie ein Key)
- Das Gewinde sitzt nur als zwei Muttern oben im Rohr. Im CAD sind Stange und Muttern mit echtem, ineinandergreifendem Gewinde
  modelliert

## 1. Ausgangslage und Quellen

| Angabe | Wert | Quelle |
|---|---|---|
| Ziel | Viele senkrechte Gewindestangen, jede mit eigenem Motor, möglichst dicht | README, `docs/ERKLAERUNG.md` |
| Bisheriger Antrieb | Zahnrad am seitlichen Motor schiebt die Stange wie eine Zahnstange, Motoren auf mehreren Ebenen | `docs/ERKLAERUNG.md` Abschnitt 3.6 |
| Stange | M4 (4 mm) | Standardwert der App |
| G0 Dicke | 6 mm | Standardwert der App |
| Sicherheitsabstand | 1 mm + 0,05 mm Toleranz | Standardwert der App |
| Motor | N20 mit Encoder, 12 x 10 mm, ohne Welle 32 mm lang, Welle Ø 3 mm D | Standard seit 0.11.0, Händlerangaben |
| Hub | 40 mm reichen, im Design als Parameter | Team |
| Geschwindigkeit | etwa 2 cm/s (1 cm in einer halben Sekunde) | Team |
| Last | Gewicht von Hand und Unterarm, aufgelegt ohne Drücken | Team |
| Ebenen | Die neue Variante verzichtet auf das Mehrebenen Konzept | Team |
| Motor neu bestellen | erlaubt | Team |

## 2. Korrektur zum bisherigen Zahnrad (mit dem Team abgestimmt)

- Selbsthemmend ist das seitliche Zahnrad nur, wenn es die Stange **drehen** soll (Schneckenrad treibt Schnecke)
- Im dokumentierten Konzept wird die Stange aber geschoben wie eine Zahnstange. Diese Längsbewegung ist nicht selbsthemmend
  und physikalisch möglich
- Die echten Schwächen sind das selbst gefräste Schneckenrad, sehr kleine Zähne (Modul etwa 0,22 bei M4), die 60 Grad Flanken,
  die Rad und Stange auseinanderdrücken, und dass die Stange Last ohne Strom nicht hält

## 3. Funktionsprinzip

- Das Rohr dreht sich, die Mutter oben im Rohr dreht mit. Die Stange kann sich nicht drehen (Verdrehsicherung) und fährt je
  Rohrumdrehung um eine Gewindesteigung, v = n · P
- Pflicht sind zwei Dinge. Die Stange ist gegen Drehung gesichert, und das Rohr ist axial fest gelagert
- Bekannte Mechanismen nach diesem Prinzip
  - Linearschrittmotoren "non captive". Eine Mutter im Hohlwellen Rotor, die Spindel muss von außen gegen Drehung gesichert werden
  - Spindelhubgetriebe mit hebender Spindel. Das Schneckenrad ist die Mutter, die Spindel taucht unten in ein Schutzrohr.
    Verdrehsicherung dort per Passfeder in einer Nut oder per Vierkantschutzrohr
  - Im Alltag Lippenstift und Klebestift
- Gegenüber der klassischen Spindel Mutter Bauart (Spindel dreht, Mutter fährt) ist hier die Stange selbst der Abtrieb. Für
  ein Stangenfeld ist das die passendere Bauart, es braucht keinen Schlitten neben der Stange

## 4. Anforderungen der Variante

- Hub 40 mm über der Oberfläche, eingefahren bündig mit dem Deckel. Im CAD ein Parameter, damit andere Hübe ohne Umbau möglich sind
- Etwa 2 cm/s, also 2 s für den ganzen Hub
- Last einer aufgelegten Hand mit Unterarm halten und anheben
- Keine Ebenen mehr, alle Motoren koaxial unter ihrer Stange
- Möglichst dichtes, regelmäßiges Raster, das sich beliebig erweitern lässt
- Alle Sonderteile im 3D Druck herstellbar, nur Norm- und Kaufteile dazu

## 5. Kräfte, Drehmomente, Reibung, Selbsthemmung

Gerechnet mit dem Flankenwinkel des metrischen Gewindes und einem Reibwert μ von 0,10 bis 0,20 (**Annahme**, Stahl auf Messing
geschmiert).

```
Steigungswinkel        λ = arctan(P / (π · d2))
Reibwinkel             ρ' = arctan(μ / cos 30°)
Drehmoment am Rohr     T = F · d2/2 · tan(λ + ρ')
Wirkungsgrad           η = tan λ / tan(λ + ρ')
selbsthemmend, wenn    λ < ρ'
```

| Gewinde | λ | T je N Last (μ 0,15) | η (μ 0,10 bis 0,20) | selbsthemmend | Rohrdrehzahl für 2 cm/s |
|---|---|---|---|---|---|
| M4 x 0,7 | 3,6° | 0,42 Nmm | 35 bis 21 % | ja | 1714 U/min |
| M5 x 0,8 | 3,3° | 0,52 Nmm | 33 bis 19 % | ja | 1500 U/min |
| M6 x 1 | 3,4° | 0,63 Nmm | 34 bis 20 % | ja | 1200 U/min |

- **Selbsthemmung.** λ liegt deutlich unter ρ' (6,6 bis 13°). Druck von oben dreht das Rohr nicht zurück, die Stange hält
  ohne Strom
- **Kraft bei 2 cm/s.** Ein N20 liefert höchstens etwa 1 W mechanisch. Grob bleibt F ≈ η · P / v ≈ 0,25 · 1 W / 0,02 m/s ≈
  10 bis 15 N je Stange, fast unabhängig vom Gewinde. Die Steigung ändert nur die nötige Drehzahl. Abgeschätzt aus Pololu Daten
  (12 V, 30:1) umgerechnet auf etwa 10:1
- **Langsamer heißt stärker.** Mit 30:1 wären es grob 40 N bei etwa 6 mm/s
- **Encoder.** Eine Motorumdrehung bewegt die Stange bei 10:1 um 0,07 mm. Die Auflösung liegt im Bereich von Tausendstel mm

**Prüfung mit der Hand.** Hand und Unterarm wiegen zusammen etwa 2,2 Prozent der Körpermasse (Segmenttabelle nach Winter).
- Bei 60 bis 90 kg Körpermasse sind das etwa 1,3 bis 2,0 kg, also 13 bis 20 N
- Liegt der Ellbogen auf, tragen die Stangen nur einen Teil davon
- Bei 14 x 12 mm Raster liegen unter einer Hand grob 55 bis 80 Stangen. Im Mittel trägt eine Stange deutlich unter 1 N, auch unter
  Fingerspitzen nur wenige N
- Halten ist durch die Selbsthemmung unkritisch. Anheben mit 10 bis 15 N je Stange hat großen Spielraum
- Ergebnis. Für diese Last reicht der Rohrantrieb mit N20 aus

## 6. Aufbau einer Kachel

Von oben nach unten, z = 0 ist die Oberseite der Deckel, Hub 40 mm. Die Werte stehen im Feature in `RB` und folgen aus den
Kaufteilen und den Druckregeln (Wand 0,8 mm, Spalt zwischen Kacheln 0,2 mm, Taschen 0,1 mm Luft).

| Teil | Herkunft | Maße und Lage | Aufgabe |
|---|---|---|---|
| Deckel mit Führung | Druck | 13,8 x 11,8 x 6, z 0 bis -6, Doppel D Schlitz 3,5 x Ø 4,2, zwei Passstifte Ø 1,6 | Oberfläche, Verdrehsicherung der Stange |
| Gewindestange | Kauf, M4 DIN 976 | Länge 56,6, oben Doppel D 3,4 über 46,5, darunter volles Gewinde | Abtrieb, eingefahren bündig, ausgefahren 40 über der Oberfläche |
| 2 Muttern M4 | Kauf, DIN 934 | z -7,2 bis -13,6 in der Sechskanttasche SW 7,1 | Die eigentliche Mutter, drehen mit dem Rohr |
| Rohr | Druck | Kopf Ø 9,6 (z -7 bis -14,7), Körper Ø 7 mit Bohrung Ø 4,6, Bund Ø 5,8, Zapfen Ø 5 im Lager, D Bohrung unten 9,3 tief | Dreht, trägt die Muttern, nimmt die Motorwelle auf |
| Kugellager | Kauf, MR85ZZ 5 x 8 x 2,5 | z -65,9 bis -68,4 im Lagersitz des Zwischenbodens | Nimmt die Axialkraft auf, zentriert das Rohr unten |
| Gehäuse | Druck | 13,8 x 11,8, z -6 bis -102, Rohrraum Ø 10,2, Zwischenboden mit Lagersitz, Motortasche 12,2 x 10,2 | Ist die Kachel. Hält Lager und Motor, trägt den Deckel |
| N20 Motor | Kauf, 12 V mit Encoder | Getriebe 12 x 10 x 9 oben am Zwischenboden (z -69,6), Länge 32, D Welle Ø 3 mit Fläche auf 2,5, 10 lang | Antrieb |
| Grundrahmen | Druck | Boden 2 mm unter allen Kacheln, Wand 4 mm bis z 0, Kabelschlitz 8 x 4 je Kachel | Hält das Feld, trägt die Last nach unten |
| Abdeckrahmen | Druck | 1,2 mm auf dem Grundrahmen, greift 1 mm über die äußeren Deckel, 4 Schrauben M2 | Hält die Kacheln von oben |

- Bautiefe 104 mm unter der Oberfläche, Raster 14 x 12 mm
- Lastpfad bei Druck von oben. Stange, Gewinde, Muttern, Rohrkopf, Rohr, Bund, Lagerinnenring, Kugeln, Außenring, Zwischenboden,
  Gehäuse, Boden des Grundrahmens. Der Motor bekommt nur das Drehmoment
- Zentrierung des Rohres. Unten durch das Lager, oben durch die Stange in der Führung über die Muttern. Darum braucht der Kopf
  kein zweites Lager, zum Gehäuse bleiben 0,3 mm Luft
- Die Stange bleibt auch ganz ausgefahren mit beiden Muttern im Eingriff (3 mm Reserve). Die Abflachung endet auch ganz
  ausgefahren noch 0,7 mm über der oberen Mutter
- Nach oben hält den Rohrkopf der Deckel mit 1 mm Luft. Ein Sicherungsring ist nicht nötig

**Zusammenbau einer Kachel**
1. Motor von unten in die Tasche schieben, bis das Getriebe am Zwischenboden anliegt
2. Lager von oben in den Lagersitz drücken
3. Zwei Muttern in die Sechskanttasche des Rohres drücken, Stange einschrauben
4. Rohr mit Stange von oben einsetzen. Der Zapfen geht ins Lager, die D Bohrung auf die Motorwelle (Fläche ausrichten)
5. Deckel über die Stange fädeln (Flächen ausrichten) und mit den Passstiften aufsetzen, Stifte einkleben
6. Kachel in den Grundrahmen stellen, Kabel durch den Schlitz. Wenn das Feld voll ist, Abdeckrahmen aufschrauben

**Druck**
- Gehäuse stehend, die Motortasche liegt unten offen, der Zwischenboden wird als Brücke gedruckt. Mehrere Gehäuse auf einmal
  mit Rand (Brim), weil sie schlank sind
- Rohr stehend, alle Übergänge sind 45 Grad, keine Stützen. Lagerzapfen und D Bohrung nach dem Druck prüfen und bei Bedarf
  nachreiben
- Deckel kopfüber, die Oberfläche liegt auf dem Druckbett und wird glatt

## 7. Verdrehsicherung

![Bild 10. Doppel D Abflachung](images/10_doppel_d.svg)

*Bild 10. Doppel D heißt zwei parallele Flächen an der Stange, wie bei einem Schraubenschlüssel. Der Schlitz im Deckel hat die
gleiche Form und steht fest.*

Die Verdrehsicherung muss das volle Antriebsmoment aufnehmen (bis etwa 13 Nmm beim schnellen N20) und den ganzen Hub mitgehen.

| Variante | zusätzliche Bauhöhe | Bewertung |
|---|---|---|
| Pin quer durch die Stange, läuft in einem feststehenden Schlitz über dem Rohr (Vorschlag Lehrer) | mindestens Hub + Pin | Funktioniert. Die Querbohrung schwächt eine M4 Stange (Kern 3,1 mm) stark, der Schlitz muss genau achsparallel stehen |
| Unrundes Kopfstück oben an der Stange in einer unrunden Bohrung | Hub | Das Kopfstück müsste beim Ausfahren durch die Mutter, geht nur mit einer um einen Hub tieferen Mutter |
| Längsnut in der Stange, Stift in der Buchse | 0 | Bewährt bei Spindelhubgetrieben, in M4 schwer zu fräsen und schwächend |
| **Doppel D Abflachung, Schlitz im Deckel** | **0** | **Gewählt.** Einfach herzustellen, das Moment wird direkt über der Mutter abgestützt |

- Warum nur Abflachung oder Nut ohne Bauhöhe auskommen. Derselbe Stangenabschnitt läuft während des Hubs durch den Deckel und
  durch die Mutter. Alles Unrunde, das nicht durch die Mutter darf, kostet einen Hub an Höhe
- Auflage im Gewinde. Bei Schlüsselweite 3,4 bleiben etwa 65 Prozent der Gewindeauflage (mit nur einer Fläche etwa 80 Prozent).
  Bei der geringen Last ist das unkritisch
- Herstellung der Flächen. Die Stange in eine einfache Feilvorrichtung legen (Block mit Rille, gehärtete Anschlagfläche auf
  Sollhöhe), bis zur Anschlagfläche feilen, um 180 Grad drehen, wiederholen, mit der Schieblehre auf 3,4 mm prüfen. Mit
  einer Fräse geht es schneller
- Der Schlitz ist 6 mm lang und hat 0,05 mm Luft an den Flächen. PETG reicht für den Anfang. Verschleißt er, bekommt der
  Deckel eine eingepresste Buchse aus POM oder Messing
- Die Reibung an den Flächen kostet bei etwa 5 bis 9 N Anlagekraft nur etwa 1 bis 2 N Längskraft

## 8. Herstellung des Rohres

- Ein PVC Rohr ganz mit dem Gewindebohrer durchzuschneiden, ist nicht zu empfehlen
  - PVC ist weich und kriecht unter Last, das Gewinde verschleißt
  - Billige Gewindestangen haben Steigungsfehler. Über eine lange Gewindestrecke klemmt die Stange dann
  - Nötig ist das Gewinde nur auf etwa 6 bis 8 mm
- Gewählt. Rohr im 3D Druck (PETG), oben eine Sechskanttasche für zwei eingepresste M4 Muttern (Messing läuft auf Stahl besser
  als Stahl auf Stahl), unten der Zapfen für das Lager und die D Bohrung für die Motorwelle
- Spätere Version. Rohr aus Messing gedreht, oben M4 mit dem Gewindebohrer 8 mm tief, darunter Ø 4,6 aufgebohrt, unten Zapfen
  und D Bohrung
- Der Hub lässt sich später ändern, indem nur Stangen-, Rohr- und Gehäuselänge angepasst werden. Im CAD sind alle drei aus dem
  Parameter Hub abgeleitet

## 9. Lagerung, Seitenkräfte, Spiel

- Die Axialkraft (Heben und Druck von oben) zeigt nach unten und geht über den Bund des Rohres in das Kugellager MR85ZZ und den
  Zwischenboden. Die Motorwelle steckt axial frei in der D Bohrung (0,5 mm Luft über dem Wellenende), ein N20 Getriebe ist für
  Axialkraft nicht ausgelegt
- Eine Gleitscheibe statt Kugellager würde etwa so viel Reibmoment kosten wie das Gewinde selbst. Deshalb ein Kugellager
- Das Lager sitzt unten, weil dort die Stange nie hinkommt. So bleibt der Zapfen voll (Ø 5 um die D Bohrung Ø 3) und das
  Lager klein genug für die 11,8 mm breite Kachel
- Seitenkraft an der ausgefahrenen Spitze. Sie wird in Führung und Mutter etwa 4 bis 7 fach größer, weil die beiden Stützstellen
  nur etwa 7 mm auseinander liegen und die Spitze 40 mm übersteht. Gegenmittel sind die enge Passung im Schlitz und der
  steife Deckel
- Knicken ist kein Thema, eine M4 Stange knickt erst bei mehreren hundert N
- Gewindespiel (axial etwa 0,05 bis 0,1 mm) zeigt sich nur beim Richtungswechsel

## 10. Raster und Bauhöhe

- Die Kachel ist so groß wie der Motor plus zwei Wände. 12 + 2 x 0,1 Luft + 2 x 0,8 Wand + 0,2 Spalt = **14 mm** in x,
  10 + 0,2 + 1,6 + 0,2 = **12 mm** in y
- Alles andere passt in diesen Querschnitt. Das Lager (Ø 8) und der Rohrkopf (Ø 9,6) liegen innerhalb der 10,2 mm Bohrung
- Das Raster ist rechteckig. Stangenabstand 14 mm in x und 12 mm in y
- Auf 120 x 120 mm wären das 8 x 10 = 80 Stangen statt 20 im bisherigen Konzept mit den Standardwerten
- Bautiefe 104 mm unter der Oberfläche (bei Hub 40), etwas weniger als die längste Stange der bisherigen Variante (117 mm)

## 11. Vergleich der Varianten

| | Seitliches Zahnrad an Gewindestange | Zahnstange + Stirnrad | Rohrantrieb |
|---|---|---|---|
| Hält ohne Strom | nein | nein | **ja** |
| Kraft bei 2 cm/s mit N20, grob | 20 bis 35 N | 30 bis 45 N | 10 bis 15 N (reicht für die Hand) |
| Raster, grob | 20 mm, mehrere Ebenen | etwa 20 mm, mehrere Ebenen | **14 x 12 mm, eine Kachel je Stange** |
| Sonderteile | gefrästes Schneckenrad | keine | gedrucktes Gehäuse, Deckel und Rohr, Abflachung an der Stange |
| Bauhöhe unter der Oberfläche | bis etwa 117 mm | ähnlich | 104 mm |

Ergebnis. Für die festgelegte Last ist der Rohrantrieb die beste der drei Varianten.

## 12. Stückliste je Kachel

| Anzahl | Teil | Herkunft |
|---|---|---|
| 1 | Gehäuse | Druck PETG |
| 1 | Deckel mit Führung | Druck PETG |
| 1 | Rohr | Druck PETG |
| 1 | Gewindestange M4 DIN 976, 56,6 mm, Doppel D 3,4 auf 46,5 mm | Kauf, Flächen gefeilt |
| 2 | Sechskantmutter M4 DIN 934, besser Messing | Kauf |
| 1 | Kugellager MR85ZZ 5 x 8 x 2,5 | Kauf |
| 1 | N20 Getriebemotor 12 V, um 3000 U/min, mit Hall Encoder, D Welle 10 mm | Kauf |

Für das ganze Feld dazu ein Grundrahmen und ein Abdeckrahmen (Druck) und 4 Schrauben M2 x 6.

## 13. Plan für Onshape

Dokument "Ingenieurswettbewerb Motorvariante" (nicht "Ingenieurswettbewerb 2027 Paris").

Was die Onshape Werkzeuge des Assistenten können. Feature Studios lesen, anlegen und beschreiben, FeatureScript testen und
Geometrie per FeatureScript erzeugen. Sie können Dokumente nicht nach Namen suchen, keine Branches auflisten oder anlegen und
keine vorhandenen Features löschen. Daraus folgt der Ablauf.

1. **Team.** Im Dokument einen Branch von Main anlegen, Name "Rohrantrieb". Main bleibt dabei unverändert
2. **Team.** Den Link zu genau diesem Branch aus der Adresszeile des Browsers schicken und bestätigen, dass der Verbrauch von
   Onshape API Aufrufen in Ordnung ist
3. **Assistent, nur lesen.** Anmeldung prüfen, Feature Studios im Branch auflisten, vorhandenen Code lesen und den alten Stand
   zusammenfassen
4. **Assistent.** Im Branch ein Feature Studio "Rohrantrieb" anlegen. Darin ein parametrisches Feature, das alle Teile aus
   Abschnitt 6 als einzelne, benannte Teile erzeugt
5. **Assistent.** Das Feature testen, bis es fehlerfrei läuft, und im Feature die Abstände zwischen drehenden und feststehenden
   Teilen prüfen (mindestens Sicherheitsabstand)
6. **Team.** Im Branch ein neues Part Studio anlegen, das Feature einfügen und die alten Part Studios dieses Branches löschen.
   Das Löschen geht mit den Werkzeugen des Assistenten nicht, und Main ist davon nicht betroffen
7. **Assistent.** Die Änderungen im Branch hier in Abschnitt 14 dokumentieren und ins Repository schreiben
8. Später möglich. Die App um koaxiale Einheiten erweitern, damit sie Raster und Platte für diese Variante rechnet

## 14. Änderungen im Onshape Branch

Dokument "Ingenieurswettbewerb Motorvariante", nur im Branch des Teams
(`documents/7b861d28eaa305bc44dbf56d/w/e4a92442a8a34a2d035e8c98`). Main und alle anderen Stände sind unverändert, der
Assistent hat dort nichts gelesen oder geschrieben.

**Feature Studio "Rohrantrieb"** mit dem Feature "Rohrantrieb". Der Code liegt auch im Repository unter
`cad/onshape/rohrantrieb.fs` und ist dort die Vorlage. Änderungen gehen immer zuerst in diese Datei und dann ins Feature Studio.

Verlauf
1. Erster Stand mit Platten, Distanzbolzen, Führungsbuchse in G0, MF128ZZ und glatten Stangen, Raster 15 mm
2. Parameternamen nur in ASCII. Onshape lehnt Umlaute in den Namen der Eingabefelder ab, das Feature erschien sonst nicht
3. Neu konstruiert als druckbare Kachel nach der Rückmeldung des Teams. Echtes Gewinde an Stange und Muttern, Führung im
   gedruckten Deckel, D Welle als Key in der D Bohrung des Rohres, Lager unten im Zwischenboden, keine Distanzbolzen mehr,
   Raster 14 x 12 mm, Grund- und Abdeckrahmen

Parameter im Feature

| Parameter | Vorgabe | Bedeutung |
|---|---|---|
| Hub der Stange | 40 mm | höchste Stellung der Stangenspitze über der Oberfläche, bestimmt Stangen-, Rohr- und Gehäuselänge |
| Ausfahrstellung zur Ansicht | 20 mm | wie weit die Stangen im Modell gerade herausstehen (0 bis Hub) |
| Kacheln in x und y | 3 und 3 | Größe des Feldes, das Raster ergibt sich aus dem Motor |
| Gewinde darstellen | an | echtes Gewinde an Stange und Muttern. Aus rechnet das Modell schneller |
| Rahmen erzeugen | an | Grundrahmen und Abdeckrahmen um das Feld |
| Abstand messen und melden | an | misst die Abstände und zeigt sie als Hinweis am Feature, gelb bei zu kleinem Abstand |

Erzeugte Teile, jedes einzeln benannt und eingefärbt, mit der Nummer der Kachel. Gehäuse (durchscheinend), Deckel mit
Führung, Rohr, Mutter M4 (zwei), Gewindestange M4, Kugellager MR85ZZ, N20 Motor mit Encoder, dazu Grundrahmen und
Abdeckrahmen. Die erste Kachel wird gebaut, alle anderen sind Kopien davon.

Gewinde. Rechtsgewinde M4 x 0,7 als Trapez auf einer Schraubenlinie. Stange und Muttern starten im gleichen Winkel und eine
ganze Zahl von Steigungen auseinander, deshalb greifen sie in jeder Ausfahrstellung ineinander, mit 0,05 mm Luft.

Geprüfte Abstände (Test mit den Vorgaben, 3 x 3 Kacheln, Ausfahrstellung 20 mm, alle eingehalten)

| Prüfung | gemessen | mindestens |
|---|---|---|
| Rohr zu Gehäuse | 0,3 | 0,25 |
| Rohr zu Deckel | 1 | 0,5 |
| Muttern zu Deckel | 1,2 | 0,5 |
| Stange zu Rohr | 0,3 | 0,2 |
| Stange zu Muttern (Gewindespiel) | 0,05 | 0,03 |
| Stange zu Deckel (Führungsspiel) | 0,05 | 0,03 |
| Motor zu Rohr (D Welle) | 0,05 | 0,03 |
| Gehäuse zu Nachbarkachel | 0,2 | 0,15 |
| Motor zu Nachbarmotor | 2 | 1,05 |

Gewollte Berührungen, darum nicht geprüft. Rohrzapfen im Lager, Bund auf dem Lagerinnenring, Lager im Sitz, Getriebe am
Zwischenboden, Gehäuse auf dem Boden des Grundrahmens, Abdeckrahmen auf den Deckeln.

**Vom Team einmalig von Hand** (mit den Werkzeugen des Assistenten nicht möglich). Erledigt
1. Im Branch das alte Part Studio geleert
2. Feature "Rohrantrieb" eingefügt. Spätere Codeänderungen im Feature Studio wirken ohne weiteren Schritt im Part Studio

## 15. Offene Punkte

- Genaue Maße des bestellten N20 (Länge mit Encoder, Wellenlänge, Lage der Fläche) nach Lieferung messen und in `RB` eintragen
- Reibwert und tatsächliche Kraft an einem ersten Muster messen
- Passungen nach einem Probedruck anpassen (Lagersitz, D Bohrung, Doppel D Schlitz, Passstifte)
- Innere Kacheln hält nach oben nur die Reibung. Reicht das nicht, bekommen die Gehäuse seitliche Rastnasen
- Ob 0,8 mm Wand an der schmalen Seite stabil genug ist

## Quellen

- Rotierende Mutter, Verdrehsicherung von außen [Nanotec non captive Linearaktuatoren](https://nanotec.com/eu/en/knowledge-base-article/non-captive-linear-actuators), [Patent US8978497B2](https://patents.google.com/patent/US8978497)
- Spindelhubgetriebe mit hebender Spindel und Verdrehsicherung [NEFF Datenblatt Bauart N](https://neff-gewindetriebe.de/fileadmin/PDF-Datenblaetter/spindelhubgetriebe/datenblatt_spindelhubgetriebe_N.pdf), [NEFF M J Serie](https://www.morskatedrivetechnology.com/wp-content/uploads/sites/3/2024/12/NEFF-Screw-jakcs-M-J-series.pdf.pdf), [Patent AT412643B](https://patents.google.com/patent/AT412643B/de)
- Wirkungsgrad und Selbsthemmung [Wikipedia Leadscrew](https://en.wikipedia.org/wiki/Leadscrew), [Roton Backdriving](https://roton.com/screw-university/screw-actions/screw-backdriving-efficiency)
- Motordaten [Pololu 12V HPCB 30:1](https://pololu.com/product/5210/specs)
- Lager MR85ZZ 5 x 8 x 2,5 (Miniatur Rillenkugellager, Normmaß). Für den ersten Stand [MF128ZZ Datenblatt](https://www.smbbearings.com/firebrick/ckeditor/plugins/upload/Uploads/Documents/bearingpdfs/MF128ZZ-flanged-miniature-bearing-8x12x3.5mm.pdf), [MR128ZZ](https://wychbearings.co.uk/mr128zz_miniature_bearing_shielded.html)
- Körpersegmente [Segmenttabelle nach Winter, Ergänzungsdatei](https://brieflands.com/articles/ans-129929/supplementary-materials/ans-129929-Supplementary%20File.pdf)
