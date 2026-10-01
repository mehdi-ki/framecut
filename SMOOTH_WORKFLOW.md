# Framecut 3.24.0 — Smooth Workflow

Dieses Update verbessert den vorhandenen Schnittworkflow in 30 Punkten.
Projekte bleiben kompatibel; neue Clip-Metadaten werden mit neutralen Vorgaben geladen.

| Nr. | Verbesserung | Bedienung und Verhalten |
| --- | --- | --- |
| 1 | Autosave und Wiederherstellung | Zusätzlich zur verzögerten Sicherung prüft ein 30-Sekunden-Takt offene Änderungen. Die letzte lesbare Sicherung bleibt als Rückfall erhalten. |
| 2 | Vorschau-Leistung | Einfache, zusammenhängende Videospuren werden direkt aus der Quelle geschnitten und abgespielt. Große Quellen erhalten automatisch 360p-Proxys im Hintergrund; komplexe Timelines nutzen den gerenderten Mehrspurpfad. Export nutzt Originale. |
| 3 | Hintergrundaufgaben | Import, Proxy-Erstellung und Export zeigen abbrechbare Fortschrittszeilen. Thumbnails und Wellenformen entstehen im Hintergrund. Export verwendet einen unveränderlichen Projektstand. Exklusive Analysen sperren Bearbeitungen, lassen Navigation zu. |
| 4 | Einrast-Vorschau | Beim Verschieben zeigt eine Führungslinie das Einrastziel; ungültige Positionen sind rot markiert. |
| 5 | Bearbeitungsverlauf | Strg+Alt+Z oder ⋯ → Verlauf. Benannte Schritte, Doppelklick zum Zurück-/Vorwärtsspringen. |
| 6 | Schnitt-Tastatur | J/K/L, I/O und Ripple-Kürzel bleiben erhalten; Pfeil hoch/runter springt zu Schnittkanten. |
| 7 | Einfügeziel vorab sehen | Drag-and-drop zeigt eine Clip-Vorschau auf der Zielspur und weist ungültige Überlappungen zurück. |
| 8 | Clip direkt bearbeiten | Die Zeile über der Timeline bietet Name, Farbe, Lautstärke und Aktiv-Schalter. Deaktivierte Clips bleiben zeitlich erhalten, liefern aber kein Bild und keinen Ton. |
| 9 | Ruhige Übergänge | Inspector-Abschnitte blenden beim Öffnen kurz ein. „Bewegung reduzieren“ schaltet das aus. |
| 10 | Projekt-Statuszentrale | ⋯ → Projektstatus zeigt Autosave, fehlende Medien, Proxys, Cache, Aufgaben und Exportwarteschlange mit passenden Aktionen. |
| 11 | Arbeitsplatz merken | Fenster, Panelgrößen, Layout, Einfach-/Pro-Modus, Zoom, Inspector-Bereiche, Medienansicht, Favoriten und Vorschauprofil werden gespeichert. |
| 12 | Zoom am Mauszeiger | Strg+Mausrad hält die Zeitposition unter dem Zeiger stabil, soweit die Scrollgrenzen es zulassen. |
| 13 | Größere Trim-Griffe | Schnittkanten haben eine größere Trefferfläche, auch wenige Pixel außerhalb des Clips. |
| 14 | Stabiler Inspector | Auswahl- und Werteänderungen erhalten die Scrollposition; geöffnete Abschnitte bleiben erhalten. |
| 15 | Einheitliche Symbole | Header-, Quell- und Timeline-Werkzeuge nutzen eine lokale Vektorfamilie mit Fokus-, Aktiv- und Deaktiviert-Zuständen. |
| 16 | Zahlen fein einstellen | Direkte Eingabe, Umschalt für kleinere Schritte bei geeigneter Dezimalgenauigkeit, Doppelklick auf Standardwert. Esc verwirft die noch nicht übernommene Eingabe. |
| 17 | Sicher tippen | Eingabefelder behalten lokale Textkürzel. Leertaste, Buchstaben und Text-Undo lösen dort keinen Schnittbefehl aus. |
| 18 | Deaktivierte Aktionen erklären | Tooltips nennen beispielsweise fehlende Auswahl oder gesperrte Spur; der Inspector bleibt dabei lesbar. |
| 19 | Lesbare Oberfläche | ⋯ → UI-Größe mit 100, 115, 130 und 150 Prozent; Schrift, Timeline-Zeilen und wichtige Symbolflächen skalieren mit. |
| 20 | Einfacher exportieren | Preset, Format, FPS und Ergebnisübersicht sind sofort sichtbar; Codec-/Bitrate-/Hardware-/HDR-Details liegen unter „Erweitert“. Quell-FPS und letzte Exportwerte liefern Vorgaben. |
| 21 | Timeline verschieben | Mitteltaste ziehen, Umschalt+Mausrad oder horizontale Trackpad-Geste verschieben den sichtbaren Bereich. |
| 22 | Abspielkopf folgen | „Folgen“ hält den Abspielkopf im sichtbaren Bereich. Manuelle Navigation pausiert das Nachführen bis zum erneuten Abspielen oder Einschalten. |
| 23 | Vorhersehbare Auswahl | Nach Löschen wird ein benachbarter Clip derselben Spur gewählt; Teilen und Undo erhalten sinnvolle Auswahlzustände. |
| 24 | Ein Schritt pro Geste | Verschieben, Trimmen, Fade- und Vorschau-Griffe erzeugen erst bei Übernahme einen Undo-Schritt. No-op-Eingaben erzeugen keine zusätzlichen Schritte; Mixer-Fader gruppieren einen Drag. |
| 25 | Abbrechen mit Esc | Laufende Trim-, Verschiebe-, Fade-, Abspielkopf- und Vorschau-Gesten lassen sich verwerfen. |
| 26 | Vorher/Nachher halten | B oder die Vergleichstaste gedrückt halten: Timeline ohne Bild-Looks. Loslassen stellt die bearbeitete Ansicht und den vorherigen Wiedergabezustand wieder her. |
| 27 | In der Vorschau ausrichten | Einzelnen Text oder ein statisch transformiertes Video im Vorschaubild ziehen. Mitte, Kanten und Sicherheitsabstände helfen beim Ausrichten; Umschalt löst das Einrasten. |
| 28 | Trim-Frame sehen | Beim Trimmen von Video-/Bildquellen erscheint ein asynchron geladenes Quellbild mit Zeit-/Längenänderung. Reverse und Bildsequenzen berücksichtigen die passende Quellposition. |
| 29 | Audio-Fades greifen | Bei ausgewähltem Audioclip die oberen Eckgriffe ziehen; Fade-Kurven und Undo sind direkt verfügbar. |
| 30 | Fehler mit nächstem Schritt | Nicht blockierende Fehlermeldungen bieten technische Details und je nach Ursache Medien-Verknüpfung, neues Exportziel oder Projektstatus an. |

## Hinweise

- Der Vergleich muss beim ersten Halten gerendert werden. Er entfernt Bild-Looks,
  Masken und Adjustment-Layer; Schnitt, Timing, Ton und räumliche Transformationen bleiben erhalten.
- Direktes Ausrichten unterstützt einzelne Texte und Videos ohne Transform-Keyframes
  oder Rotation. Animierte und rotierte Videos werden weiterhin im Inspector bearbeitet.
- Proxys benötigen beim ersten Erstellen Rechenzeit und Speicherplatz. Bei Fehlern
  kann wieder mit Originaldateien gearbeitet werden.
- AppImage und Debian-Paket enthalten die Anwendung. Python, FFmpeg und die beim
  ersten Start eingerichtete Python-Umgebung bleiben wie bisher erforderlich.
  Hinweise zu Systempaketen und Updates stehen in README.md.

## Prüfung und Auslieferung

Die Release-Pipeline prüft Kernfunktionen, FFmpeg-Ausgaben, GUI-Interaktionen,
Transkription und Update-Metadaten. Dazu kommen Paketprüfung, SHA-256-Abgleich
und ein Starttest der aus AppImage und Debian-Paket entpackten Anwendung.
GUI-Tests laufen mit Qt offscreen; ein Test auf echter Audio-/GPU-Hardware wird dadurch
nicht ersetzt.

Veröffentlicht werden AppImage, Debian-Paket, Quell-ZIP, SHA256SUMS und updates.json.
