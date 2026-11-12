# Variante Rohrantrieb (Rohr mit Innengewinde)

Stand. Technische Untersuchung, Plan und erste CAD Umsetzung in Onshape (Abschnitt 14). Alle Maße in mm.

Diese Datei untersucht den Vorschlag, die Gewindestange nicht mehr seitlich über ein Zahnrad anzutreiben, sondern über ein
drehendes Rohr mit Innengewinde und einem Motor darunter. Grundlage sind das Repository (README, `docs/ERKLAERUNG.md`) und
die Antworten des Teams. Werte, die nirgends festgelegt sind, sind als **Annahme** gekennzeichnet.

![Bild 9. Variante Rohrantrieb im Schnitt](images/09_rohrantrieb_schnitt.svg)

*Bild 9. Schnitt durch eine Einheit mit den vorläufigen Konstruktionsannahmen aus Abschnitt 6.*

## Kurzfassung

- Das Prinzip funktioniert. Es ist eine bekannte Bauform (rotierende Mutter, hebende Spindel), wie in Linearschrittmotoren
  ohne Verdrehsicherung und in Spindelhubgetrieben mit hebender Spindel
- Die Stange hält Last ohne Strom (selbsthemmendes Gewinde). Mit einem schnellen N20 schafft sie bei 2 cm/s etwa 10 bis 15 N.
  Das reicht für eine aufgelegte Hand mit Unterarm deutlich (Abschnitt 5)
- Der Motor sitzt koaxial unter der Stange. Damit braucht eine Einheit nur etwa 12 x 12 mm Grundfläche, das Raster wird
  etwa 15 mm statt bisher 20 mm, und die Ebenen G1 bis Gn entfallen. Alle Motoren sitzen auf einer Motorplatte
- Verdrehsicherung über zwei Abflachungen an der Stange (Doppel D) in einer feststehenden Führungsbuchse in G0. Ein Pin
  über dem Rohr würde mindestens einen ganzen Hub an Bauhöhe kosten
- Das Gewinde sitzt nur als kurze Mutter oben im Rohr, nicht über die ganze Länge

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

- Hub 40 mm über G0, eingefahren bündig mit G0. Im CAD ein Parameter, damit andere Hübe ohne Umbau möglich sind
- Etwa 2 cm/s, also 2 s für den ganzen Hub
- Last einer aufgelegten Hand mit Unterarm halten und anheben
- Eine Motorplatte statt mehrerer Ebenen
- Möglichst dichtes, regelmäßiges Raster

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
- Bei 15 mm Raster liegen unter einer Hand grob 40 bis 60 Stangen. Im Mittel trägt eine Stange deutlich unter 1 N, auch unter
  Fingerspitzen nur wenige N
- Halten ist durch die Selbsthemmung unkritisch. Anheben mit 10 bis 15 N je Stange hat großen Spielraum
- Ergebnis. Für diese Last reicht der Rohrantrieb mit N20 aus

## 6. Aufbau einer Einheit (vorläufige Konstruktionsannahmen)

Von oben nach unten, z = 0 ist die Oberseite von G0. Alle Werte hier sind **Annahmen** für den ersten CAD Stand und im CAD Parameter.

| Teil | Maße und Lage | Aufgabe |
|---|---|---|
| G0 | Dicke 6, z 0 bis -6 | Deckplatte, hält die Führungsbuchsen |
| Führungsbuchse | POM, außen Ø 8, Länge 10 (z 0 bis -10), Doppel D Bohrung 3,45 x Ø 4,05 | Führt die Stange, verhindert das Drehen, steht fest |
| Gewindestange | M4, Länge 62, Doppel D Schlüsselweite 3,4 auf den oberen 52 mm | Abtrieb, eingefahren bündig mit G0, ausgefahren 40 über G0 |
| Rohrkopf | Ø 10, z -11 bis -18,5, Sechskanttasche SW 7 für zwei Muttern M4 (2 x 3,2) | Die Mutter, dreht mit dem Rohr |
| Flanschlager | MF128ZZ (8 x 12 x 3,5) in der Lagerplatte, z -18,5 bis -22 | Nimmt die Axialkraft nach unten und das Kippen auf |
| Sicherungsring | Wellenring 8 mm unter dem Lager | Hält das Rohr nach oben |
| Lagerplatte | Dicke 4, z -18,5 bis -22,5 | Trägt die Lager |
| Rohrkörper | außen Ø 8, innen Ø 5 frei, bis z -72 | Raum für die eingefahrene Stange |
| Rohrboden | D Bohrung 3 mm, 6 tief, Schiebesitz | Nimmt das Drehmoment der Motorwelle, keine Axialkraft |
| Motorplatte | Dicke 8, z -76 bis -84, Tasche 12 x 10 | Hält den Motor gegen sein Drehmoment |
| Motor | N20 12 V mit Encoder, schnelle Variante um 3000 U/min, Getriebeseite oben | Antrieb |
| Distanzbolzen | zwischen G0, Lagerplatte und Motorplatte | Verbindung und Befestigung an der übergeordneten Konstruktion |

- Bauhöhe unter G0 etwa 112 mm, ähnlich wie die längste Stange der bisherigen Variante (117 mm)
- Die Stange bleibt auch ganz ausgefahren mit beiden Muttern im Eingriff (2 mm Reserve plus 2 mm Längenzuschlag)
- Lastpfad bei Druck von oben. Stange, Gewinde, Muttern, Rohrkopf, Lagerinnenring, Kugeln, Flansch, Lagerplatte, Distanzbolzen.
  Der Motor bekommt nur das Drehmoment

## 7. Verdrehsicherung

![Bild 10. Doppel D Abflachung](images/10_doppel_d.svg)

*Bild 10. Doppel D heißt zwei parallele Flächen an der Stange, wie bei einem Schraubenschlüssel. Die Führungsbuchse hat die
gleiche Form und steht fest.*

Die Verdrehsicherung muss das volle Antriebsmoment aufnehmen (bis etwa 13 Nmm beim schnellen N20) und den ganzen Hub mitgehen.

| Variante | zusätzliche Bauhöhe | Bewertung |
|---|---|---|
| Pin quer durch die Stange, läuft in einem feststehenden Schlitz über dem Rohr (Vorschlag Lehrer) | mindestens Hub + Pin | Funktioniert. Die Querbohrung schwächt eine M4 Stange (Kern 3,1 mm) stark, der Schlitz muss genau achsparallel stehen |
| Unrundes Kopfstück oben an der Stange in einer unrunden Bohrung | Hub | Das Kopfstück müsste beim Ausfahren durch die Mutter, geht nur mit einer um einen Hub tieferen Mutter |
| Längsnut in der Stange, Stift in der Buchse | 0 | Bewährt bei Spindelhubgetrieben, in M4 schwer zu fräsen und schwächend |
| **Doppel D Abflachung, Führungsbuchse in G0** | **0** | **Empfehlung.** Einfach herzustellen, das Moment wird direkt neben der Mutter abgestützt |

- Warum nur Abflachung oder Nut ohne Bauhöhe auskommen. Derselbe Stangenabschnitt läuft während des Hubs durch G0 und durch die
  Mutter. Alles Unrunde, das nicht durch die Mutter darf, kostet einen Hub an Höhe
- Auflage im Gewinde. Bei Schlüsselweite 3,4 bleiben etwa 65 Prozent der Gewindeauflage (mit nur einer Fläche etwa 80 Prozent).
  Bei der geringen Last ist das unkritisch
- Herstellung der Flächen. Die Stange in eine einfache Feilvorrichtung legen (Block mit Rille, gehärtete Anschlagfläche auf
  Sollhöhe), bis zur Anschlagfläche feilen, um 180 Grad drehen, wiederholen, mit der Schieblehre auf 3,4 mm prüfen. Mit
  einer Fräse geht es schneller
- Buchse aus POM oder Messing, nicht die Leiterplatte selbst. FR4 Kanten verschleißen als Gleitfläche
- Die Reibung an den Flächen kostet bei etwa 5 bis 9 N Anlagekraft nur etwa 1 bis 2 N Längskraft

## 8. Herstellung des Rohres

- Ein PVC Rohr ganz mit dem Gewindebohrer durchzuschneiden, ist nicht zu empfehlen
  - PVC ist weich und kriecht unter Last, das Gewinde verschleißt
  - Billige Gewindestangen haben Steigungsfehler. Über eine lange Gewindestrecke klemmt die Stange dann
  - Nötig ist das Gewinde nur auf etwa 6 bis 8 mm
- Prototyp. Rohr im 3D Druck (PETG), oben eine Sechskanttasche für zwei eingepresste oder eingeklebte M4 Muttern (Messing läuft
  auf Stahl besser als Stahl auf Stahl), Lagersitz auf Ø 8 nachreiben, unten die D Bohrung für die Motorwelle
- Bessere Version. Rohr aus Messing gedreht, oben M4 mit dem Gewindebohrer 8 mm tief, darunter Ø 5 aufgebohrt, unten ein
  eingepresster Stopfen mit D Bohrung
- Der Hub lässt sich später ändern, indem nur Stangen- und Rohrlänge angepasst werden. Im CAD sind beide aus dem Parameter Hub
  abgeleitet

## 9. Lagerung, Seitenkräfte, Spiel

- Die Axialkraft (Heben und Druck von oben) zeigt nach unten und geht über das Flanschlager in die Lagerplatte. Die Motorwelle
  steckt axial frei im Rohrboden, ein N20 Getriebe ist für Axialkraft nicht ausgelegt
- Eine Gleitscheibe statt Kugellager würde etwa so viel Reibmoment kosten wie das Gewinde selbst. Deshalb ein Kugellager
- Seitenkraft an der ausgefahrenen Spitze. Sie wird in Buchse und Mutter etwa 4 bis 7 fach größer, weil die beiden Stützstellen
  nur 8 bis 14 mm auseinander liegen und die Spitze 40 mm übersteht. Gegenmittel sind eine lange Buchse (10 mm) und eine enge
  Passung
- Knicken ist kein Thema, eine M4 Stange knickt erst bei mehreren hundert N
- Gewindespiel (axial etwa 0,05 bis 0,1 mm) zeigt sich nur beim Richtungswechsel

## 10. Raster und Bauhöhe

- Breitestes Teil sind das Flanschlager (Ø 12, Flansch etwas mehr) und der Motor (12 x 10)
- Mit allen Lagern in einer Platte ist ein **Raster von etwa 15 mm** sinnvoll, damit zwischen den Lagersitzen etwa 3 mm Steg bleiben
- Enger (etwa 13 x 11 mm) ginge mit zwei versetzten Lagerplatten, eine für jede zweite Reihe. Das ist eine spätere Optimierung
- Auf 120 x 120 mm wären das bei 15 mm etwa 8 x 8 = 64 Stangen statt 20 im bisherigen Konzept mit den Standardwerten
- Bauhöhe unter G0 etwa 112 mm

## 11. Vergleich der Varianten

| | Seitliches Zahnrad an Gewindestange | Zahnstange + Stirnrad | Rohrantrieb |
|---|---|---|---|
| Hält ohne Strom | nein | nein | **ja** |
| Kraft bei 2 cm/s mit N20, grob | 20 bis 35 N | 30 bis 45 N | 10 bis 15 N (reicht für die Hand) |
| Raster, grob | 20 mm, mehrere Ebenen | etwa 20 mm, mehrere Ebenen | **etwa 15 mm, eine Motorplatte** |
| Sonderteile | gefrästes Schneckenrad | keine | Rohr, Abflachung, Führungsbuchse, Lager |
| Bauhöhe unter G0 | bis etwa 117 mm | ähnlich | etwa 112 mm |

Ergebnis. Für die festgelegte Last ist der Rohrantrieb die beste der drei Varianten.

## 12. Stückliste je Einheit (Annahmen)

| Anzahl | Teil |
|---|---|
| 1 | Gewindestange M4 DIN 976, 62 mm, Doppel D 3,4 auf 52 mm |
| 2 | Sechskantmutter M4 DIN 934, besser Messing |
| 1 | Rohr (3D Druck PETG oder Messing gedreht) |
| 1 | Flanschlager MF128ZZ 8 x 12 x 3,5 |
| 1 | Sicherungsring für Welle 8 mm (DIN 471) |
| 1 | Führungsbuchse POM mit Doppel D Bohrung |
| 1 | N20 Getriebemotor 12 V, um 3000 U/min, mit Hall Encoder |
| gemeinsam | G0, Lagerplatte, Motorplatte, Distanzbolzen, Schrauben |

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
   Abschnitt 6 als einzelne, benannte Teile erzeugt (Stange, Rohr, Muttern, Lager, Sicherungsring, Buchse, Motor, drei Platten,
   Distanzbolzen). Parameter sind unter anderem Hub, Ausfahrstellung für die Ansicht, Raster, Anzahl in x und y, Plattendicken,
   Gewinde, Schlüsselweite, Rohr- und Lagermaße. Gewinde werden vereinfacht dargestellt
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

**Neu. Feature Studio "Rohrantrieb"** mit dem Feature "Rohrantrieb". Der Code liegt auch im Repository unter
`cad/onshape/rohrantrieb.fs` und ist dort die Vorlage. Änderungen gehen immer zuerst in diese Datei und dann ins Feature Studio.

Parameter im Feature

| Parameter | Vorgabe | Bedeutung |
|---|---|---|
| Hub über G0 | 40 mm | höchste Stellung der Stangenspitze, bestimmt Stangenlänge und Bauhöhe |
| Ausfahrstellung zur Ansicht | 20 mm | wie weit die Stangen im Modell gerade herausstehen (0 bis Hub) |
| Raster | 15 mm | Abstand der Einheiten in x und y |
| Einheiten in x und y | 3 und 3 | Größe des Feldes |
| Abstände prüfen und melden | an | misst die Abstände und zeigt sie als Hinweis am Feature, gelb bei zu kleinem Abstand |

Alle übrigen Maße stehen oben im Code in `RB_DIMS` (Abschnitt 6, vorläufige Annahmen). Gewinde sind als glatte Zylinder
dargestellt.

Erzeugte Teile, jedes einzeln benannt und eingefärbt. G0 Deckplatte, Lagerplatte, Motorplatte, vier Distanzbolzen und je
Einheit Führungsbuchse, Gewindestange M4 mit Doppel D, Rohr mit Sechskanttasche, Querbohrung frei und D Bohrung unten,
zwei Muttern M4, Distanzscheibe, Flanschlager MF128ZZ, Sicherungsring 8 und N20 Motor mit Encoder.

Höhen bei Hub 40 mm (z = 0 ist die Oberseite von G0). Rohrkopf oben −11,2, Lagerplatte −20 bis −24, Stangenlänge 61,8,
Rohrunterkante −71,8, Motorstirn −75,8, Motorende −107,8.

Geprüfte Abstände (Test mit 2 x 2 Einheiten, Ausfahrstellung 20 mm, alle eingehalten)

| Prüfung | gemessen | mindestens |
|---|---|---|
| Rohr zu Führungsbuchse | 1,2 | 1,0 |
| Rohr zu Platten und Bolzen | 1,487 | 1,0 |
| Muttern zu Führungsbuchse | 1,4 | 1,0 |
| Sicherungsring zu Lagerplatte | 0,8 | 0,5 |
| Stange zu Rohr | 0,5 | 0,3 |
| Motorwelle zu Rohr (Schiebesitz) | 0,05 | 0,03 |
| Motor zu Nachbarmotor | 3 | 1,05 |
| Lager zu Nachbarlager | 1,4 | 1,05 |
| Rohr zu Nachbarrohr | 5 | 1,05 |

Die Motorwelle steckt 6 mm tief in einer 6,5 mm tiefen D Bohrung. So überträgt sie nur Drehmoment, die Axialkraft geht über
Rohrkopf und Distanzscheibe in das Flanschlager.

**Vom Team einmalig von Hand** (mit den Werkzeugen des Assistenten nicht möglich)
1. Im Branch das alte Part Studio leeren (alle Features markieren und löschen) oder den Tab löschen und ein neues Part Studio
   anlegen
2. Dort "Benutzerdefiniertes Feature hinzufügen", Feature Studio "Rohrantrieb" dieses Dokuments wählen und das Feature
   "Rohrantrieb" einfügen. Spätere Codeänderungen im Feature Studio wirken danach ohne weiteren Schritt im Part Studio

Stand dieser Punkte. Offen, bis das Team sie erledigt hat.

## 15. Offene Punkte

- Genaue Maße des bestellten N20 (Länge mit Encoder, Wellenlänge, Befestigungsgewinde) nach Lieferung messen
- Reibwert und tatsächliche Kraft an einem ersten Muster messen
- Ob 15 mm Raster reichen oder versetzte Lagerplatten für etwa 13 x 11 mm nötig sind

## Quellen

- Rotierende Mutter, Verdrehsicherung von außen [Nanotec non captive Linearaktuatoren](https://nanotec.com/eu/en/knowledge-base-article/non-captive-linear-actuators), [Patent US8978497B2](https://patents.google.com/patent/US8978497)
- Spindelhubgetriebe mit hebender Spindel und Verdrehsicherung [NEFF Datenblatt Bauart N](https://neff-gewindetriebe.de/fileadmin/PDF-Datenblaetter/spindelhubgetriebe/datenblatt_spindelhubgetriebe_N.pdf), [NEFF M J Serie](https://www.morskatedrivetechnology.com/wp-content/uploads/sites/3/2024/12/NEFF-Screw-jakcs-M-J-series.pdf.pdf), [Patent AT412643B](https://patents.google.com/patent/AT412643B/de)
- Wirkungsgrad und Selbsthemmung [Wikipedia Leadscrew](https://en.wikipedia.org/wiki/Leadscrew), [Roton Backdriving](https://roton.com/screw-university/screw-actions/screw-backdriving-efficiency)
- Motordaten [Pololu 12V HPCB 30:1](https://pololu.com/product/5210/specs)
- Lager [MF128ZZ Datenblatt](https://www.smbbearings.com/firebrick/ckeditor/plugins/upload/Uploads/Documents/bearingpdfs/MF128ZZ-flanged-miniature-bearing-8x12x3.5mm.pdf), [MR128ZZ](https://wychbearings.co.uk/mr128zz_miniature_bearing_shielded.html)
- Körpersegmente [Segmenttabelle nach Winter, Ergänzungsdatei](https://brieflands.com/articles/ans-129929/supplementary-materials/ans-129929-Supplementary%20File.pdf)
