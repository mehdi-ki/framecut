# Framecut 3.25.0 — Smooth Workflow

Native Linux-Videoschnitt-App mit einer CapCut-ähnlichen Anordnung. Eigener Code,
keine CapCut-Kopie. Python/PySide6 mit lokalem FFmpeg-Export und optionaler lokaler
Whisper-Spracherkennung für automatische Untertitel.

## Neu: Smooth Workflow

32 Verbesserungen machen die vorhandenen Werkzeuge leichter bedienbar: gespeicherte
Arbeitsplätze, größere Trim-Griffe, Zoom am Mauszeiger, Clip-Schnellbearbeitung,
Hintergrundaufgaben, Bearbeitungsverlauf, bessere Wiederherstellung und vereinfachter
Export. Die vollständige Zuordnung und Bedienung stehen in [SMOOTH_WORKFLOW.md](SMOOTH_WORKFLOW.md).

Das **⋯-Menü oben** öffnet Verlauf und Projektstatus sowie UI-Größe und reduzierte
Bewegung. **Strg+Alt+Z** zeigt den Verlauf. In der Timeline: **Strg+Mausrad** zoomt,
**Mitteltaste** oder **Umschalt+Mausrad** verschiebt die Ansicht, **Esc** verwirft eine
laufende Mausgeste. **B gedrückt halten** vergleicht die Timeline ohne Bild-Effekte.

## Neu in 3.25: Vorschau-Performance und Preset-Bibliotheken

Die Mehrspur-Vorschau bleibt nach Schnitten sofort abspielbar: Der letzte
gültige Renderstand bleibt sichtbar, während die aktuelle Komposition im
Hintergrund aktualisiert wird. Große Videoquellen werden bereits nach dem
Import automatisch für die Proxy-Vorschau vorbereitet; die Originale bleiben
für den Export unverändert. Audio-Wellenformen werden unter einem
kanonischen Medienpfad gespeichert und erscheinen auch in älteren Projekten
zuverlässig in der Timeline.

Die Modusleiste öffnet jetzt eigene Offline-Bibliotheken für **Textdesigns**,
**Sticker**, **Effekte**, **Übergänge** und **Filter**. Bei Textdesigns werden
erst Preset und danach der Text gewählt; alle Stilwerte werden direkt auf den
neuen Clip übernommen.

## Neu in 3.24: Asset-Bibliothek

Der neue Tab **Bibliothek** links stellt 22 offline nutzbare Starter-Assets bereit:
sechs Sounds, sechs Videoeffekt-Presets, sechs Animationen und vier Übergänge.
Suche und Kategorien filtern die Liste sofort. Sounds können angehört, mit
**Verwenden** auf einer freien Audiospur eingefügt oder direkt auf die Timeline
gezogen werden. Effekte, Animationen und Übergänge werden auf den ausgewählten
Clip angewendet und verwenden dabei die vorhandene Framecut-Engine.

Die Starter-Sounds werden beim ersten Einsatz lokal als kleine WAV-Dateien im
Framecut-Benutzerordner erzeugt. Es gibt keinen Cloud-Upload und keinen Download
von Drittanbieter-Paketen. Details stehen in [ASSET_LIBRARY.md](ASSET_LIBRARY.md).

## Schneller Player für große Videodateien

Einfache, zusammenhängende Videospuren werden im **Direct-Schnittmodus** direkt
aus der Quelldatei abgespielt. Ein Schnitt löst dabei keinen neuen FFmpeg-Render
aus; Framecut wechselt beim Abspielkopf nur zwischen den geschnittenen Bereichen.
Sobald mehrere Spuren, Effekte, Übergänge oder Mischungen aktiv sind, bleibt der
gerenderte Mehrspurmodus erhalten.

Bei Videodateien ab 256 MB startet Framecut zusätzlich automatisch eine lokale
360p-Proxy-Erzeugung im Hintergrund. Währenddessen bleiben Schnitt und direkte
Wiedergabe verfügbar. Nach Fertigstellung wird der Proxy für die Vorschau
verwendet; beim Export bleibt die Originaldatei unverändert.

## Update und Start auf deinem Linux Mint

1. Framecut schließen und die bisherigen Projekte speichern.
2. Dieses ZIP in einen **neuen Ordner** entpacken. Die bisherige Version als Rückfall behalten.
3. Den Ordner `Framecut-3.25.0` öffnen, in dem `start.sh`, `install.sh` und `app.py` liegen.
4. Rechtsklick auf eine freie Stelle → „Im Terminal öffnen“.
5. Ausführen:

   ```bash
   bash start.sh
   ```

Für eine Desktop-Installation kannst du stattdessen `bash install.sh` ausführen.
Der Installer legt Framecut unter `~/.local/share/framecut/3.25.0` ab und erstellt
den Starter `~/.local/bin/framecut` sowie einen Eintrag im Anwendungsmenü.

## Linux-Auslieferung 3.25.0

Das Quellpaket enthält jetzt drei reproduzierbare Auslieferungswege:

- **Debian/Ubuntu/Mint:** `bash build_deb.sh` erzeugt ein echtes `framecut_3.25.0_amd64.deb`. Installation mit `sudo apt install ./framecut_3.25.0_amd64.deb`. Die Anwendung legt ihre Python-Umgebung pro Benutzer unter `~/.local/share/framecut/3.25.0/.venv` an; FFmpeg und Python bleiben systemweit.
- **AppImage:** `bash build_appimage.sh` erzeugt aus der vorbereiteten `Framecut.AppDir` ein echtes Type-2-AppImage, sobald das offizielle `appimagetool` über `PATH` oder `APPIMAGETOOL=/pfad/appimagetool` verfügbar ist. Der Builder bricht ohne dieses Werkzeug bewusst ab und erzeugt keine Datei, die nur fälschlich `.AppImage` heißt.
- **Komplettes Release:** `bash build_release.sh` erstellt das Linux-ZIP, das `.deb`, Prüfsummen und – falls `appimagetool` vorhanden ist – das AppImage. Ohne Tool bleibt eine kurze Build-Hinweisdatei neben den übrigen Artefakten.

`install.sh` und das `.deb` installieren `framecut.svg`, registrieren den MIME-Typ
`application/x-framecut` für `*.framecut` und legen zusätzlich `framecut-update` an.
Ein Doppelklick auf ein Framecut-Projekt übergibt die Datei direkt an die Anwendung.

### Automatische Updates

Framecut verwendet standardmäßig das stabile Manifest des öffentlichen GitHub-Releases:
`https://github.com/mehdi-ki/framecut/releases/latest/download/updates.json`. Beim
Start wird nach kurzer Verzögerung im Hintergrund geprüft; ein Update wird erst nach
deiner Bestätigung geladen. Du kannst die Quelle mit `FRAMECUT_UPDATE_MANIFEST_URL`
oder `~/.config/framecut/update-manifest.url` überschreiben. Das Manifest muss die
Version, die Download-URL und die SHA-256-Prüfsumme jedes Pakets enthalten;
`updates.example.json` zeigt das Format. Mit `FRAMECUT_DISABLE_UPDATE_CHECK=1` lässt
sich die Prüfung vollständig abschalten.

Der verifizierte Kommandozeilenweg ist:

```bash
framecut-update
framecut-update --install
```

Für einen eigenen Update-Server kannst du weiterhin explizit ein Manifest angeben:

```bash
framecut-update --manifest https://dein-server.example/framecut/updates.json
framecut-update --manifest https://dein-server.example/framecut/updates.json --install
```

Ein `.deb` wird zunächst in den Update-Cache geladen und mit `sudo dpkg -i` installiert.
Ein laufendes AppImage kann nach erfolgreicher Prüfsummenprüfung ersetzt und danach
neu gestartet werden. Die Manifest-Datei selbst wird nie automatisch verändert.

### GitHub-Release-Automation

`.github/workflows/release.yml` veröffentlicht bei einem Tag wie `v3.25.0` automatisch
die getesteten ZIP-, `.deb`- und AppImage-Dateien sowie `updates.json`. Die Version
kommt aus der Datei `VERSION`; Tag und Versionsdatei müssen übereinstimmen. Dadurch
werden Prüfsummen und Download-Adressen für den Update-Checker bei jedem Release
neu erzeugt.

Wenn 0.1 auf deinem Laptop schon läuft, brauchst du die Systempakete nicht erneut
zu installieren. Bei einer frischen Installation:

```bash
sudo apt update && sudo apt install python3-venv ffmpeg libxcb-cursor0
```

Der Starter erstellt eine lokale `.venv` und installiert beim ersten Start
PySide6 6.8.3, faster-whisper, OpenCV und rembg/onnxruntime. Dafür sind Internet und einige hundert MB Platz
nötig; beim ersten automatischen Untertitel-Lauf wird zusätzlich das gewählte
Whisper-Modell geladen. pip kann
bereits heruntergeladene Pakete aus seinem Cache verwenden. Nicht mit sudo starten.
Danach arbeitet die App lokal und lädt deine Videos nicht hoch.

## Was jetzt funktioniert

- Audiowellenformen werden automatisch erzeugt und direkt im Audioclip angezeigt.
- **Audio aus Video extrahieren** erstellt eine separate WAV-Datei, legt sie passend auf eine Audiospur und schaltet den Originalton des Videoclips stumm. Die Extraktion läuft im Hintergrund und kann abgebrochen werden.
- Der weiße Abspielkopf lässt sich am Griff oben in der Timeline mit der Maus an jede beliebige Stelle ziehen.
- **Textclips** lassen sich über **+ Text** anlegen, auf einer eigenen oberen Spur platzieren und im Inspector bearbeiten: Inhalt, Schriftart, Größe, Farbe, Fett/Kursiv, Kontur, Schatten, Hintergrund, Animation sowie X-/Y-Position.
- **Untertitel** können direkt aus **SRT** oder **VTT** importiert werden. Cue-Zeiten und Zeilen werden als editierbare Textclips auf automatisch angelegten Untertitelspuren übernommen; überlappende Cues werden auf getrennte Spuren verteilt.
- **Automatische Untertitel** öffnen sich über **+ Automatische Untertitel** links, im Timeline-Add-Menü, per Rechtsklick auf eine freie Timeline-Stelle oder über **Strg+K**. Wähle ein Projektmedium oder eine Datei, die Sprache (**Automatisch**, Deutsch, English, Türkçe, Azərbaycanca, Español oder Français) und das Modell **tiny**, **base** oder **small**. faster-whisper verarbeitet Video/Audio lokal im Hintergrund; das gewählte Modell wird nur beim ersten Einsatz heruntergeladen und danach im Framecut-Benutzerordner wiederverwendet. Die erzeugten Cues sind normale Textclips und können wie importierte Untertitel verschoben, gestaltet, geschnitten, per Undo/Redo bearbeitet und wieder als SRT/VTT exportiert werden.
- Die Anzahl der Video- und Audiospuren lässt sich oben in der Timeline frei zwischen 1 und 10 wählen. Belegte Spuren werden geschützt.
- Geschwindigkeit pro Clip von 0,25× bis 4× für Zeitlupe und Zeitraffer, inklusive synchron angepasstem Ton und Clipdauer.
- Rechtsklick auf einen Clip öffnet ein Kontextmenü mit passenden Bearbeitungsaktionen: Vorschau, Teilen, Geschwindigkeit, Lautstärke, Audioextraktion, Textbearbeitung und Löschen. Auf leerem Timeline-Bereich stehen Schnellaktionen bereit.
- Der Clip-Inspector besitzt einen eigenen Scrollbereich, sodass alle Felder auch bei kleiner Fensterhöhe erreichbar bleiben.
- Audiowellenformen zeigen die Amplitude als gut sichtbare gefüllte Pegelfläche statt als dünne Linien.
- Ein- und Ausblendungen für Bild und Ton können pro Video- oder Audioclip eingestellt werden.
- Textclips haben keine feste Quelldauer mehr und lassen sich über Inspector, Clipränder oder Kontextmenü frei verlängern und kürzen.
- Ausgewählte Clips erhalten eine deutlich sichtbare Markierung. Die Spurbezeichnungen sind an einer festen Trennlinie ausgerichtet.
- Mit **Strg + Linksklick halten und ziehen** lässt sich die Timeline horizontal verschieben.
- Inspector-Felder zeigen bei Hover und Fokus deutlich, welches Feld aktiv ist.
- Die Textfarbe kann über eine sichtbare Farbpalette ausgewählt werden.
- Die Live-Vorschau aktualisiert Änderungen nach einer kurzen Pause automatisch. **Schnellvorschau** rendert mit 640×360, 24 fps und schnellem Encoding; die Exportqualität bleibt unverändert.
- Die Mehrspurvorschau rendert jetzt im Hintergrund. Der letzte gültige Frame bleibt sichtbar, die Oberfläche bleibt bedienbar, und mehrere schnelle Änderungen werden zu einem Render zusammengefasst.
- Die Timeline verwendet zwischengespeicherte Poster- und Wellenformbilder und zeichnet beim Abspielkopf- oder Auswahlwechsel nur die betroffenen Bereiche neu.
- Das Auswählen eines Clips bewegt den weißen Abspielkopf nicht. Der Abspielkopf lässt sich weiterhin separat am Griff oder durch einen Klick auf eine leere Timeline-Stelle bewegen.
- Videoclips können im Inspector transformiert werden: Zoom, Position X/Y, Zuschneiden, Rotation und horizontales/vertikales Spiegeln.
- Bildtransformationen werden identisch in der Hintergrundvorschau und im MP4-Export angewendet.
- **Keyframes** animieren Zoom, Bildposition X/Y, Rotation, Deckkraft und Unschärfe innerhalb eines Videoclips. Die Marker erscheinen direkt im Clip der Timeline; Splitten, Trimmen, Undo/Redo, Autosave und Projekt-Speichern nehmen die Animation mit.
- **Farbkorrektur** lässt sich pro Videoclip einstellen: Helligkeit, Kontrast und Sättigung. Vorschau und MP4-Export verwenden dieselben Werte.
- **Filter und LUTs**: Vivid, Warm, Cool, Cinematic, Vintage und Noir stehen als native Presets bereit; zusätzlich können `.cube`- und `.3dl`-LUTs geladen werden. Der LUT-Pfad wird relativ im Projekt gespeichert.
- **Lautstärke-Keyframes** automatisieren die Lautstärke innerhalb von Audio- und Videoclips. Die Marker erscheinen unten im Clip; Splitten, Trimmen, Autosave und Export nehmen die Kurve mit.
- **Audio-Processing**: Rauschunterdrückung, parametrischer 3-Band-EQ (Tiefen, Mitten, Höhen), Kompressor mit Schwelle und Ratio sowie Panorama und Kanalmodus (Stereo, Mono, linker oder rechter Kanal) werden in Vorschau und Export identisch angewendet.
- **Audio-Ducking** senkt Musik- oder Atmo-Clips automatisch ab, sobald andere Tonspuren erklingen. Der Ducking-Wert bleibt pro Clip gespeichert und lässt sich mit Lautstärke-Keyframes kombinieren.
- **Export 2.8**: freie Bildrate von 1 bis 120 FPS inklusive 50/60 FPS, Videobitrate von 256 bis 200000 kbit/s, MP4/MKV/WebM/MOV, H.264/H.265/VP9/AV1, Hardware-Encoding über Auto/NVIDIA NVENC/VAAPI sowie HDR10 mit BT.2020/PQ.
- **Projektverwaltung 2.9**: Fehlende Medien werden beim Öffnen erkannt und lassen sich über **Medien neu verknüpfen…** automatisch nach Dateiname oder manuell neu zuordnen. **Archivieren…** bündelt Projekt, Videos, Audio, Bildsequenzen und LUT-Dateien in einem portablen ZIP; solche Archive lassen sich direkt wieder öffnen.
- **Proxy-Vorschau 2.9**: **Proxy-Vorschau** erzeugt kleinere lokale H.264-/AAC-Dateien für flüssigeres Arbeiten. Die Originalpfade bleiben im Projekt und werden beim Export immer verwendet.
- **Performance 3.0**: Proxy-Profile in 360p und 720p, automatisch begrenzter LRU-Cache für Poster, Wellenformen und Vorschauen, optionale GPU-Decodierung mit sicherem CPU-Fallback sowie eine Render-Queue für mehrere Exporte.
- **Professionelle Timeline 3.1**: Marker und Kapitel, J/K/L-Transportsteuerung, Insert- und Overwrite-Schnitt, Ripple-Einfügen/-Löschen, Mehrfachauswahl per Strg-Klick oder Auswahlrahmen und erweitertes Einrasten an Clips, Markern und Timeline-Ende.
- **Audio-Mixer 3.2**: Über **Audio-Mixer** werden Spurlautstärke bis 200 %, Panorama, Mute, Solo und sichtbare Vorschau-Pegel gesteuert. Der Master besitzt Fader, Panorama und optionale LUFS-Normalisierung (-30 bis -5 LUFS). Die Werte werden im Projekt gespeichert, sind undo-/redo-fähig und landen identisch in Vorschau und Export. **Voice-over aufnehmen…** erzeugt eine lokale WAV-Aufnahme und legt sie am Abspielkopf auf eine freie Audiospur.
- **Text/Untertitel 3.3**: Importierte Untertitel können über **Untertitel exportieren…** wieder als SRT oder WebVTT ausgegeben werden. Drei native Stilvorlagen (**Titel**, **Untertitel**, **Lower Third**) wenden Schrift, Kontur, Schatten, Hintergrund, Position und Animation als einen Undo-Schritt auf den ausgewählten Textclip an.
- **Medienverwaltung 3.4**: Die Medienablage besitzt eine Suche über Dateiname, Pfad und Typ, Filter für Video, Audio, Bilder, Bildsequenzen und Offline-Medien sowie Sortierung nach Import-Reihenfolge, Name, Typ oder Dauer. Die Anzeige zeigt den sichtbaren Trefferstand; Ziehen und **Am Spurende hinzufügen** verwenden auch nach Filterung immer das richtige Originalmedium.
- **Effekt- und Animationssystem 3.5**: Effekt-Presets (**Clean / Manuell**, **Cinematic**, **Dream**, **Noir**, **Vivid**, **Soft Focus**) wenden mehrere Bildparameter als einen Schritt an. **Stabilisierung** nutzt FFmpeg-Deshake mit einstellbarer Stärke.
- **Adjustment-Layer 3.5**: Über **+ Adjustment-Layer** wird eine leere Videospur über der Timeline angelegt. Farbkorrektur, Filter, Blur und Schärfe wirken damit gemeinsam auf die darunterliegende Komposition und bleiben unabhängig von den Quellclips.
- **Keyframe-Kurven 3.5**: Transform-, Deckkraft-, Blur- und Lautstärke-Keyframes unterstützen **Linear**, **Ease in**, **Ease out** und **Ease in/out**. Die Kurve wird mit dem Marker gespeichert und in Vorschau, Export, Split und Trim berücksichtigt.
- **Linux-Auslieferung 3.7**: echtes `.deb`, vorbereiteter Type-2-AppImage-Build, eigenes SVG-App-Symbol, MIME-/Dateiverknüpfung für `.framecut`, SHA-256-Prüfung und automatischer GitHub-Updatequelle.
- **Design & Workflow 3.8**: Cinema-Vollbildvorschau mit Esc/F11 und eine durchsuchbare Befehls-Palette mit den wichtigsten Schnitt-, Projekt- und Exportaktionen über Strg+K.
- **Timeline UX 3.9**: Rechtsklick-Kontextmenüs werden über Qt zuverlässig weitergereicht.
- **Timeline Design 3.10**: Die Werkzeugleiste über der Timeline ist in Verlauf, Bearbeiten, Einfügen, Marker, Add, Export, Mehr und Ausrichten gruppiert. Seltene Aktionen öffnen sich über Menüs; die sichtbare Leiste enthält nur eindeutige Symbole und behält Tooltips sowie Tastenkürzel.
- **Professionelle Trim-Werkzeuge 3.12**: Ripple-In (**Q**) und Ripple-Out (**W**) schneiden bis zum Abspielkopf und schließen die betroffene Spur. Der Roll-Schnitt (**R**) verschiebt eine direkte Schnittkante, ohne die Gesamtdauer zu ändern. Slide verschiebt einen Clip frameweise zwischen direkten Nachbarn; Slip verschiebt frameweise nur das Quellfenster. Alle Modi sind auch über das Trim-Menü, den Rechtsklick auf Clips und **Strg+K** verfügbar und lassen sich mit Undo/Redo zurücknehmen.
- **Source-Monitor 3.13**: **Clip ansehen** öffnet die ausgewählte Video- oder Audioquelle unabhängig vom Timeline-Mix. Mit **I** und **O** setzt du Quell-In und Quell-Out; der markierte Bereich lässt sich direkt als **Insert** einfügen oder als **Overwrite** verwenden. Die Marken sind temporär, werden beim Clipwechsel zurückgesetzt und alle Schnitte bleiben vollständig undo-/redo-fähig.
- **Lokale KI-Werkzeuge 3.17.1**: **Hintergrund entfernen** erzeugt mit rembg/ONNX eine transparente lokale Video- oder Bildableitung, **Motion-Tracking** verfolgt den Rechteckbereich per OpenCV, **Auto-Reframe** erkennt Gesichter lokal und folgt dem Fokus für Projektformat, 16:9, 9:16 oder 1:1, und **Objekt entfernen** füllt das getrackte Gebiet lokal per FFmpeg. **Sprachisolierung** hebt Dialoge mit einer portablen FFmpeg-Kette hervor und reduziert Hintergrundgeräusche. Kein Video muss dafür einen Cloud-Dienst verlassen; die optionalen Zusatzpakete werden beim Start automatisch nachinstalliert.
- **Feature-Batch 3.18.0**: **Bezier-/Freiformmasken** unterstützen polygonale Rotoskopie, Pfad-Keyframes und weiche Kanten. **3-Wege-Color-Grading** bietet Belichtung, Temperatur, Tönung, Vibrance sowie Lift-, Gamma- und Gain-Räder. Der **grafische Keyframe-Editor** zeigt Animationskurven direkt im Inspector und erlaubt Ziehen sowie Hinzufügen von Punkten. Die lokale **Beat-Erkennung** setzt Beat-Marker, an denen die Timeline einrastet und Musik-Schnitte synchronisiert werden können; alle Werte bleiben in Vorschau, Export und `.framecut`-Projekt erhalten.
- **Feature-Batch 3.19.0**: **Textbasierter Schnitt** transkribiert Video-/Audioclips lokal und entfernt lange Pausen sowie erkannte Füllwörter. **Objekt-Tracking für Bezier-Masken** überträgt den lokalen Motion-Track direkt auf Rotoskopie-Pfade. **Beat-/Szenen-Auto-Cut** setzt echte Schnitte an stabilen Musik- und Bildwechseln. **Compound-Clips** bündeln ausgewählte Timeline-Clips als benannten, gemeinsam verschiebbaren Container. **Multi-Kamera** synchronisiert mehrere Videowinkel über ihre Audiospuren, schaltet Winkel um und rendert nur die aktive Kamera; alle Werte bleiben in Vorschau, Export und `.framecut`-Projekt erhalten.
- **Feature-Batch 3.20.0**: **Export-Presets** wählen passende Codec-, FPS-, Qualitäts- und Zielgrößen für Master, YouTube, Shorts/TikTok/Reels, Instagram und Archiv. **Arbeitsbereich-In/Out** exportiert nur den markierten Timeline-Bereich. **Attribute-Clipboard** übernimmt Look, Audio und Übergänge; das **Keyframe-Clipboard** skaliert Animationen auf den Zielclip. **Audio-Sync** richtet beliebige Video-/Audioclips lokal über ihre Onsets aus. **Clip-Loudness** normalisiert einzelne Dialog- oder Musikclips. **Standbild am Abspielkopf**, **PNG-Frame-Capture**, **FFmpeg-Kapiteldateien** und **Spurlücken schließen** verkürzen den täglichen Schnittworkflow.
- **UX-Patch 3.20.1**: Die Timeline-Toolbar ist flach und symbolbasiert, Quell- und Arbeitsbereich-Aktionen nutzen ein einheitliches Icon-System, nicht funktionale Inspector-Tabs wurden entfernt, und doppelte Timeline-Kontextmenü-Events werden abgefangen.
- **Workspace-Redesign 3.21.0**: Die Oberfläche folgt jetzt einer klaren 3-Spalten-Struktur mit Medienablage links, größerer Vorschau in der Mitte und aufklappbaren Inspector-Bereichen rechts. Header-Aktionen, Vorschau-Steuerung, Abstände, Panels und Timeline-Farben wurden vereinheitlicht; die Timeline-Spurköpfe und Clipzustände sind deutlich lesbarer.
- **UX-Workbench 3.22.0**: Einfach-/Pro-Modus, fünf Aufgaben-Layouts, Fokusansicht, kontextabhängige Clip-Aktionen, Medienkarten oder Listenansicht mit Favoriten, klarere leere Zustände, kompaktere Timeline-Badges und eine ruhigere Inspector-Hierarchie. Bestehende Schnitt-, Audio-, Effekt-, KI- und Exportfunktionen bleiben unverändert erhalten.
- **Videoeffekte** stehen pro Videoclip zur Verfügung: Deckkraft für Overlays/Picture-in-Picture, Unschärfe, Schärfe, Stabilisierung, Greenscreen-Keying und weiche Rechteck-/Ellipsenmasken. Deckkraft und Unschärfe lassen sich zusätzlich per Keyframe animieren.
- **Speed-Ramping, Freeze-Frame und Reverse**: Mehrere lokale Geschwindigkeitspunkte werden interpoliert; ein Freeze-Frame hält das letzte Bild für eine einstellbare Dauer und Reverse dreht Bild und Originalton um.
- **Übergänge**: Überblenden, Slide, Smooth, Cover, Wipe, Zoom, Dip to Black, Fade to White, Blur In, Pixelize, Circle Open/Close und Radial können zwischen direkt angrenzenden Video- oder Audioclips derselben Spur gewählt werden. Bild und Ton werden passend zur eingestellten Dauer behandelt.
- **Spursteuerung**: Im Spurkopf schaltet **M** die komplette Spur stumm; **L** sperrt sie gegen Verschieben, Trimmen, Teilen, Löschen und Inspector-Änderungen. Die Zustände werden im Projekt und Autosave gespeichert.
- **Schnittworkflow**: Strg-Klick wählt mehrere Clips; Kopieren, Einfügen, Duplizieren, Gruppieren/Lösen und Ripple-Löschen sind per Toolbar, Kontextmenü und Tastenkürzel verfügbar. Ripple-Einfügen schiebt spätere Clips automatisch nach rechts.
- **Spuren**: Leere Spuren lassen sich über das Spurkopf-Kontextmenü löschen; eigene Spurnamen werden gespeichert und in der Timeline angezeigt.
- **Bilder**: PNG, JPG, BMP, WebP und TIFF können als 5-Sekunden-Standbilder importiert werden. Transparente PNGs bleiben beim Compositing als Overlays transparent.
- **Bildsequenzen**: Mehrere Bilder lassen sich als geordnete Sequenz mit frei wählbarer Bildrate importieren und wie ein Videoclip trimmen, verschieben und exportieren.

- Grafische Videoclips mit automatisch erzeugten Vorschaubildern in der Timeline.
- CapCut-ähnliche Tastenkürzel: Leertaste für Play/Pause, S/Strg+B zum Teilen, Entf zum Löschen, Pfeile zum Bewegen und Home/Ende für Anfang/Ende.

- Mehrere Video- und Audiospuren, deren Anzahl über die Zähler in der Timeline eingestellt wird.
- Videos und Audiodateien importieren; Analyse läuft im Hintergrund.
- Medien aus der Ablage direkt auf eine passende Timeline-Spur ziehen.
- Clipmitte ziehen: zeitlich verschieben und passende Spur wechseln.
- Linken/rechten Rand ziehen: Clip kürzen oder vorhandenes Quellmaterial wieder
  verlängern. Quellen werden dabei nicht verändert.
- Magnetisches Einrasten an Clipgrenzen, Zeit 0 und am Abspielkopf.
- **Umschalt** beim Ziehen deaktiviert Einrasten vorübergehend.
- Timeline-Zoom per Regler oder **Strg + Mausrad**; **Einpassen** zeigt den Schnitt.
- Clips teilen/löschen, genaue Zeitwerte und Lautstärke von 0 bis 100 %.
- **Originalton auslagern**: Ton auf freie Audiospur kopieren und den Videoclip
  stummschalten. Beides ist danach unabhängig und lässt sich gemeinsam rückgängig
  machen. Bei Bedarf wird eine neue Audiospur angelegt.
- 80 Undo-Schritte, Redo, Projektdateien samt Medienablage speichern/öffnen.
- Autosave nach etwa zwei Sekunden ohne Änderung und Wiederherstellungsfrage
  beim nächsten Start nach einem Abbruch.
- Export mit Bildüberlagerung, Lücken, Audio-Mix, frei wählbarer Bildrate/Bitrate, mehreren Containern/Codecs, HDR und Exportabbruch.
- Projekte aus Version 0.1 importieren. Die alte Reihenfolge wird zu einer Spur
  mit passenden Zeitpositionen. Speichern schlägt eine neue `-v02.framecut` vor;
  die ursprüngliche Projektdatei wird nicht automatisch überschrieben.

## Text und Titel

Klicke auf **+ Text**, gib deinen Titel oder Untertitel ein und bearbeite ihn anschließend rechts im Inspector. Textclips liegen automatisch auf einer oberen Videospur. **Text**, **Textgröße**, **Textfarbe**, **Schrift**, **Fett**, **Kursiv**, **Kontur**, **Schatten**, **Hintergrund**, **Animation**, **Text X** und **Text Y** ändern das Ergebnis direkt nach dem nächsten Vorschau-Render. X und Y sind Prozentwerte der Bildbreite bzw. Bildhöhe; 50 % / 50 % ist die Mitte. Die Dauer stellst du über die Clipränder oder die Zeitfelder frei ein; Textclips haben keine Begrenzung durch eine Quelldatei.

Unter **TEXTSTIL UND ANIMATION** stehen sechs native FFmpeg-Animationen zur Verfügung: Ein-/Ausblenden sowie Hereinschieben von links, rechts, oben oder unten. Die Animationsdauer wirkt am Anfang und Ende des Textclips. Kontur, Schatten und Texthintergrund werden mit Farbe, Deckkraft und Randabstand gespeichert und identisch in Vorschau und MP4-Export gerendert.

### Native Text-Stilvorlagen

Wähle einen Text- oder Untertitelclip aus und öffne im Inspector unter
**TEXTSTIL UND ANIMATION** die Stilvorlage. **Titel**, **Untertitel** und
**Lower Third** setzen Schriftgröße, Fettung, Kontur, Schatten, Hintergrund,
Position und Animation mit einem Klick. Die Vorlage ist vollständig lokal und
ändert nur die Werte des ausgewählten Clips; sie erzeugt keine externen Assets.
Die Anwendung zählt die Änderung als einen Undo-Schritt.

## Medienablage

Die linke Medienablage lässt sich direkt durchsuchen. Die Suche berücksichtigt
Dateiname, vollständigen Pfad und Medientyp. Über **Alle**, **Video**, **Audio**,
**Bilder**, **Sequenzen** und **Offline** werden Treffer eingegrenzt; die
Offline-Ansicht markiert fehlende Quelldateien mit ⚠. Die Sortierung kann auf
Import-Reihenfolge, Name, Typ oder Dauer gestellt werden. Ein gefiltertes oder
sortiertes Medium kann weiterhin direkt auf die Timeline gezogen oder mit
**Am Spurende hinzufügen +** eingesetzt werden.

## Untertitel und automatische Transkription

Über **+ Automatische Untertitel** links, im Add-Menü der Timeline, per Rechtsklick
auf eine freie Timeline-Stelle oder über **Strg+K** öffnest du die lokale
Spracherkennung. Wähle ein importiertes Video bzw. Audio oder eine Datei vom
Datenträger. **Automatisch erkennen** funktioniert für mehrsprachiges Material;
bei bekanntem Ton kannst du Deutsch, English, Türkçe, Azərbaycanca, Español oder
Français fest vorgeben. Das Modell **tiny** ist am schnellsten, **base** ist die
ausgewogene Standardwahl und **small** liefert meist die genaueren Zeitsegmente.

Die Verarbeitung läuft im Hintergrund. Video und Audio werden nicht hochgeladen;
faster-whisper decodiert sie lokal. Beim ersten Einsatz lädt Framecut das gewählte
Whisper-Modell einmalig in den Framecut-Benutzerordner. Danach kann es offline
wiederverwendet werden. Ein Abbruch stoppt die Verarbeitung, ohne das Projekt zu
verändern.

Die erkannten Segmente werden als normale, editierbare Textclips auf benannten
Untertitelspuren angelegt. Du kannst sie verschieben, trimmen, teilen, gestalten,
per Undo/Redo bearbeiten und anschließend über **Untertitel exportieren…** als SRT
oder VTT ausgeben.

Über **+ Untertitel importieren (SRT/VTT)** links oder **+ Untertitel** in der Timeline wählst du eine `.srt`- oder `.vtt`-Datei. Framecut erkennt Zeitstempel mit Komma oder Punkt, übernimmt mehrere Textzeilen und entfernt übliche SRT/VTT-Markup-Tags. Jeder Cue wird zu einem normalen Textclip: Du kannst ihn verschieben, teilen, trimmen, gestalten, animieren und per Undo/Redo bearbeiten. Die Untertitelspuren heißen automatisch **Untertitel**, **Untertitel 2** usw.; die importierte Datei bleibt unverändert.

Mit **Untertitel exportieren…** in der Timeline werden die benannten
Untertitelspuren wieder als `.srt` oder `.vtt` geschrieben. Start- und Endzeiten
werden aus der tatsächlichen Clipposition übernommen; mehrzeilige Texte bleiben
mehrzeilig. Dadurch kann ein importierter Untertitel-Workflow nach dem Schnitt
als editierbare Sidecar-Datei weitergegeben werden. Normale Titelclips werden
nicht exportiert, sobald im Projekt ausdrücklich Untertitelspuren existieren.

## Bildtransformationen

Videoclip auswählen und rechts im Inspector den Bereich **BILDTRANSFORMATION** öffnen. **Zoom** reicht von 0,1× bis 4×. **Bild X** und **Bild Y** bestimmen die Position des Clips: 50 % / 50 % ist die Mitte, 0 % liegt am linken bzw. oberen Rand und 100 % am rechten bzw. unteren Rand. Mit **Crop links/oben/rechts/unten** wird der jeweilige Rand prozentual abgeschnitten. **Rotation** dreht den Clip; **Horizontal** und **Vertikal** spiegeln ihn. **Bild zurücksetzen** setzt alle Werte des ausgewählten Videoclips auf die Standardwerte zurück.

## Keyframes

Wähle einen Videoclip aus. Setze im Inspector unter **BILDTRANSFORMATION** und
**VIDEO-EFFEKTE** zuerst Zoom, Bild X, Bild Y, Rotation, Deckkraft und Unschärfe.
Unter **KEYFRAMES · TRANSFORM + VIDEOEFFEKTE** wählst du die lokale Zeit im Clip
und klickst auf **Keyframe setzen / aktualisieren**. Danach stellst du eine zweite
Zeit und neue Transformations- oder Effektwerte ein und setzt den nächsten
Keyframe. Mit **Kurve** legst du fest, ob der Übergang zum nächsten Marker linear,
beschleunigt (**Ease in**), auslaufend (**Ease out**) oder weich in beide Richtungen
(**Ease in/out**) verläuft. Framecut interpoliert zwischen den Markern automatisch; vor dem ersten
Marker bleibt der normale Clipwert aktiv, nach dem letzten Marker der letzte
Keyframewert.

Ein Klick auf einen Eintrag lädt seine Werte wieder in den Inspector.
**Keyframe löschen** entfernt den ausgewählten Marker. Die kleinen goldenen
Rauten in der Timeline zeigen die Positionen der Keyframes. Crop, Spiegelung und
Schärfe bleiben pro Clip statisch; Zoom, Position, Rotation, Deckkraft und
Unschärfe sind animierbar.

## Farbkorrektur

Wähle einen Videoclip und öffne rechts im Inspector den Bereich
**FARBKORREKTUR**. **Helligkeit** reicht von -1 bis +1, **Kontrast** und
**Sättigung** von 0× bis 3×. Die Standardwerte sind 0 für Helligkeit und 1×
für Kontrast/Sättigung. Die Einstellung wird pro Clip gespeichert und wirkt
auch dann, wenn der Clip auf einer anderen Videospur liegt. **Bild zurücksetzen**
setzt neben den Transformationen und Keyframes auch die Farbkorrektur zurück.

## Videoeffekte

Wähle einen Videoclip und öffne im Inspector den Bereich **VIDEO-EFFEKTE**.
**Deckkraft** reicht von 0 bis 100 % und macht Overlays oder Picture-in-Picture
transparent. **Unschärfe** nutzt einen weichen Gauß-Blur, **Schärfe** erhöht
lokale Konturen. Deckkraft und Unschärfe lassen sich unabhängig voneinander
einsetzen und zusätzlich über die normalen Videokeyframes animieren.
**Bild zurücksetzen** stellt auch diese drei Effektwerte wieder her.

## Lautstärke-Keyframes

Wähle einen Audio- oder Videoclip mit Ton und öffne im Inspector den Bereich
**LAUTSTÄRKE-KURVE**. Setze die lokale Zeit im Clip, stelle oben den normalen
Lautstärke-Regler auf den gewünschten Wert und klicke auf **Lautstärke setzen /
aktualisieren**. Wiederhole das an weiteren Zeiten. Framecut interpoliert
zwischen den Markern automatisch; vor dem ersten Marker gilt der normale
Lautstärke-Wert.

Ein Klick auf einen Eintrag lädt dessen Wert. **Lautstärke-Keyframe löschen**
entfernt den ausgewählten Marker. Grüne Rauten in der Timeline zeigen die
Positionen der Lautstärke-Keyframes. Das funktioniert sowohl für Musikclips als
auch für den Originalton eines Videoclips.

## Audio-Mix und Verarbeitung

### Audio-Mixer 3.2

Oben auf **Audio-Mixer** klicken. Jede Video- und Audiospur erscheint als eigener
Kanalzug mit **Lautstärke**, **Panorama**, **M** (Mute), **S** (Solo) und einer
Vorschau-Pegelanzeige. Die Pegelanzeige folgt dem Abspielkopf und zeigt, welche
Spur im aktuellen Timeline-Bereich hörbar ist. Änderungen werden als ein
Undo-Schritt zusammengefasst, automatisch gesichert und bei Vorschau sowie
Export über denselben FFmpeg-Audiopfad angewendet.

Im Bereich **MASTER** stehen Gesamtlautstärke, Master-Panorama und
**Loudness-Normalisierung** zur Verfügung. Die Normalisierung verwendet einen
Zielwert von -30 bis -5 LUFS; -16 LUFS ist der neutrale Startwert. Unter
**Voice-over aufnehmen…** wählst du eine WAV-Zieldatei. Nach dem Stoppen wird die
Aufnahme automatisch importiert, am aktuellen Abspielkopf eingesetzt und bei
Bedarf auf eine neue Audiospur gelegt. Mikrofonzugriff und die WAV-Datei bleiben
lokal auf deinem Rechner.

Wähle einen Audio- oder Videoclip mit Ton und öffne rechts im Inspector den
Bereich **AUDIO · MIX UND KANÄLE**. **Rauschunterdrückung** arbeitet mit einem
lokalen FFmpeg-Filter und reicht von 0 bis 30 dB. Der 3-Band-EQ bearbeitet
Tiefen bei 120 Hz, Mitten bei 1 kHz und Höhen bei 8 kHz jeweils von -12 bis
12 dB. **Kompressor aktiv** bietet eine Schwelle von -60 bis 0 dB und ein Ratio
von 1× bis 20×.

Unter **Kanäle** kannst du Stereo, Mono, den linken oder den rechten Kanal auf
Stereo wählen. **Panorama** verschiebt die beiden Kanäle zwischen links und
rechts. **Audio-Ducking** wird bei Musik, Atmo oder Originalton eingestellt:
0 % lässt den Clip unverändert, 100 % ducked ihn stark, wenn andere hörbare
Clips gleichzeitig laufen. Die Verarbeitung läuft in der Hintergrundvorschau
und im MP4-Export über denselben Renderpfad.

## Export

Klicke oben auf **Exportieren ↗**. Im Exportdialog legst du vor der
Zieldatei das **Format** (MP4, MKV, WebM oder MOV), den **Videocodec**
(H.264, H.265/HEVC, VP9 oder AV1), die **Bildrate** von 1 bis 120 FPS und
die **Videobitrate** fest. 60 FPS sind damit direkt möglich; eine individuelle
FPS-Zahl wie 59,94 kann ebenfalls eingetragen werden.

Unter **Encoding** stehen CPU-Rendering, automatische Hardwarewahl, NVIDIA
NVENC und VAAPI für Intel/AMD zur Verfügung. Hardwareprofile funktionieren
nur, wenn FFmpeg und der Linux-Treiber das jeweilige Gerät bereitstellen;
**Auto** fällt andernfalls auf Software-Encoding zurück. Nicht unterstützte
Codec-/Container-Kombinationen werden vor dem Rendern abgefangen.

**HDR10** aktiviert 10-Bit-Ausgabe mit BT.2020/PQ-Farbmetadaten und ist für
H.265/HEVC oder AV1 verfügbar. Die Vorschau bleibt bewusst schnell und nutzt
weiterhin ihr eigenes 24-FPS-Preview-Profil; die Exportauswahl beeinflusst
den finalen Render.

## Live-Vorschau und Farbpalette

**Live-Vorschau** berechnet nach einer Änderung automatisch ein aktualisiertes Vorschaubild, sobald du kurz mit der Bearbeitung pausierst. **Schnellvorschau** ist standardmäßig aktiv und reduziert Auflösung, Bildrate und Renderaufwand nur für die Vorschau. Schalte die Option aus, wenn du eine größere Vorschau brauchst; der MP4-Export bleibt immer in der ausgewählten Zielauflösung.

Bei Textclips öffnet **Palette** einen Farbwähler mit sichtbaren Farbfeldern. Änderungen an Text, Stil, Farbe, Größe, Position, Animation, Geschwindigkeit, Lautstärke und Ein-/Ausblendung werden nach Bestätigung automatisch in die Live-Vorschau übernommen. Farbkorrekturen, Filter, Masken und Greenscreen werden ebenfalls nach kurzer Pause automatisch sichtbar.

## Timeline-Bedienung

Der ausgewählte Clip wird mit einer hellen Kontur und farbiger Innenmarkierung hervorgehoben. Die Labels **VIDEO 1**, **AUDIO 1** usw. sitzen in einer klar getrennten linken Spalte. **M** im Spurkopf schaltet die Spur stumm, **L** sperrt sie. Gesperrte Clips bleiben auswählbar, lassen sich aber nicht versehentlich bearbeiten. Halte **Strg** gedrückt, drücke die linke Maustaste und ziehe nach links oder rechts, um durch lange Timelines zu navigieren. Der weiße Abspielkopf bleibt unabhängig von der Clipauswahl frei ziehbar.

## Marker, Kapitel und professionelle Schnittmodi

Mit **Marker +** setzt du am aktuellen Abspielkopf einen benannten Marker; **Kapitel +** legt dort einen Kapitelmarker an. Marker werden als farbige Linien in der Timeline angezeigt, mit dem Projekt gespeichert und über Rechtsklick bearbeitet, angesprungen oder gelöscht. Ripple-Einfügen verschiebt Marker hinter der Einfügestelle mit.

**J** spielt rückwärts, **K** pausiert und **L** spielt vorwärts. Wiederholtes J oder L erhöht die Transportgeschwindigkeit bis 4×. Die Rückwärtswiedergabe nutzt einen sicheren Timeline-Transport und bleibt auch dann verfügbar, wenn der Multimedia-Backend keine negative Abspielrate unterstützt.

**Insert** fügt die kopierten Clips am Abspielkopf ein und verschiebt spätere Clips auf den betroffenen Spuren nach rechts. **Overwrite** legt die kopierten Clips am Abspielkopf ab und trimmt oder entfernt nur den überdeckten Bereich; die restliche Timeline bleibt an ihrer Position. Beide Modi prüfen gesperrte Spuren und lassen sich mit Undo/Redo zurücknehmen.

**Ripple-In** (**Q**) entfernt den Quellbereich vom Clipanfang bis zum Abspielkopf und zieht spätere Clips derselben Spur nach links. **Ripple-Out** (**W**) entfernt den Bereich vom Abspielkopf bis zum Clipende und schließt die Spur ebenfalls. Der **Roll-Schnitt** (**R**) setzt die Kante zwischen zwei direkt angrenzenden Clips auf die Position des Abspielkopfs und erhält die Gesamtdauer des Paars. **Slide** verschiebt den ausgewählten Clip mit **Alt + Pfeil**; die direkten Nachbarn werden an den neuen Kanten mitgetrimmt. **Slip** verschiebt mit **Umschalt + Alt + Pfeil** nur den Quellbereich, während Position und Länge des Clips unverändert bleiben. Nicht ausreichender Quellbereich, gesperrte Spuren und ungültige Nachbarschaften werden abgefangen.

## Spurstatus

Klicke links im Spurkopf auf **M**, um eine Video- oder Audiospur stummzuschalten.
Das Bild einer Videospur bleibt sichtbar; nur ihr Ton wird aus Mix, Vorschau und
MP4-Export entfernt. Klicke auf **L**, um die Spur zu sperren. Danach blockiert
Framecut Clipbewegungen, Randtrimmen, Teilen, Löschen, neue Medien auf dieser
Spur und Änderungen im Inspector. Ein erneuter Klick auf **L** entsperrt sie.
Beide Zustände lassen sich mit Undo/Redo zurücknehmen und werden mit dem Projekt
gespeichert.

## Mehrfachauswahl und Schnittworkflow

Halte **Strg** gedrückt und klicke Clips, oder ziehe mit der Maus einen Auswahlrahmen auf der leeren Timeline, um mehrere Clips auszuwählen. Ein normaler Klick auf einen Clip wählt ihn einzeln; Clips mit derselben Gruppe werden gemeinsam ausgewählt. **Kopieren**, **Einfügen**, **Duplizieren**, **Gruppieren**, **Gruppe lösen**, **Insert**, **Overwrite** und **Ripple löschen** stehen unten in der Timeline und im Rechtsklick-Menü zur Verfügung. **Ripple einfügen** ist zusätzlich über **Strg + Umschalt + V** verfügbar und schiebt vorhandene Clips auf den betroffenen Spuren nach rechts. Das Magnet-Einrasten berücksichtigt Clipgrenzen, Marker, Abspielkopf, Zeit 0 und das Timeline-Ende; **Umschalt** deaktiviert es vorübergehend. Der Inspector bleibt bei einer Mehrfachauswahl bewusst gesperrt, damit keine gemischten Werte versehentlich überschrieben werden.

## Bilder und Bildsequenzen

Über **+ Video / Audio / Bild importieren** werden einzelne Bilder als fünf Sekunden lange Videoclips angelegt. Ihre Dauer lässt sich wie bei einem Videoclip über Inspector oder Cliprand ändern. PNG-Alpha wird im Vorschau- und Export-Compositing berücksichtigt; die Transparenz wirkt also als Overlay auf darunterliegenden Videospuren.

Über **+ Bildsequenz importieren** wählst du mehrere Bilder und anschließend die Bildrate zwischen 1 und 120 FPS. Framecut speichert die Reihenfolge im Projekt, erzeugt daraus einen Videoclip und verarbeitet die Sequenz identisch zu anderem Videomaterial.

Leere Spurköpfe öffnen per Rechtsklick die Spurverwaltung. Dort lassen sich Spuren umbenennen oder löschen; belegte Spuren und die jeweils letzte Video-/Audiospur werden zum Schutz des Projekts nicht gelöscht.

## Übergänge und Effekte

Im Inspector stehen **Einblenden** und **Ausblenden** für den einzelnen Clip sowie **Übergang** für den direkt davorliegenden Clip derselben Spur. Unterstützt werden **Überblenden**, **Slide**, **Smooth**, **Cover**, **Wipe**, **Zoom**, **Dip to Black**, **Fade to White**, **Blur In**, **Pixelize**, **Circle Open/Close** und **Radial**. Die Dauer wird in Sekunden eingestellt; ein Übergang wird nur akzeptiert, wenn beide Clips direkt angrenzen und die Dauer in beide Clips passt. Rechtsklick bietet Schnellwerte für alle Typen mit 0,5 s.

### Filter, LUT und Greenscreen

Unter **FARBKORREKTUR** lassen sich ein Preset und optional eine `.cube`-/`.3dl`-LUT auswählen. Die LUT-Datei bleibt außerhalb des Projekts und wird beim Speichern relativ zur `.framecut`-Datei referenziert; beim Öffnen muss sie am selben relativen Ort vorhanden sein.

Unter **VIDEO-EFFEKTE** aktiviert **Greenscreen**, entfernt die angegebene Key-Farbe und bietet Regler für Ähnlichkeit und Weichheit. Die Werte werden in Vorschau und Export identisch verwendet. Unter **MASKEN** kann ein Rechteck oder eine Ellipse mit Position, Größe und weicher Kante gesetzt werden.

### Effekt-Presets und Adjustment-Layer

Im Inspector unter **FARBKORREKTUR** wählst du ein **Effekt-Preset** und klickst
auf **Preset anwenden**. Das Preset setzt Farbwerte, Filter, Blur und Schärfe
gemeinsam; weitere manuelle Änderungen werden als **custom** gespeichert.

Mit **+ Adjustment-Layer** erzeugst du eine leere obere Videospur über der
aktuellen Timeline. Die Layer hat keine Quelldatei und wird im Render direkt auf
die bis dahin zusammengesetzte Bildspur angewendet. So kann ein gemeinsamer Look
über mehrere Clips gelegt werden, ohne jeden Clip einzeln zu ändern. Adjustment-
Layer können verschoben, getrimmt, dupliziert und mit Presets bearbeitet werden.
Die Quelltransformation und Übergänge sind für diese Layer bewusst deaktiviert.

**Stabilisierung** liegt unter **VIDEO-EFFEKTE**. 0 % lässt das Bild unverändert;
höhere Werte erweitern die lokale Bewegungssuche. Die Funktion braucht keinen
externen Dienst und wird identisch in Vorschau und Export gerendert.

### Speed-Ramping, Freeze und Reverse

Unter **SPEED-RAMPING · VIDEO** setzt du mehrere Punkte aus Quellzeit und Geschwindigkeit. Zwischen den Punkten wird linear interpoliert; vor dem ersten Punkt gilt die normale Clipgeschwindigkeit, danach der letzte Punkt. Die Clipdauer und der Originalton werden an die Rampenzeit angepasst.

**Letztes Bild halten** verlängert einen Videoclip nach dem Quellende um die angegebene Dauer. **Rückwärts abspielen** dreht Bild und Originalton um. Beide Optionen können mit Filtern, Masken und Übergängen kombiniert werden.

## Inspector und Audiowellenformen

Der Bereich **CLIP-EINSTELLUNGEN** kann jetzt unabhängig gescrollt werden. Dadurch bleiben Spur, Zeitwerte, Geschwindigkeit, Lautstärke und Textfelder auch bei einer kleinen Vorschauhöhe erreichbar. Audioclips erhalten beim Import eine kontrastreiche, gefüllte Wellenform. Nach einem Schnitt wird nur der passende Quellbereich abgebildet, damit Sprachpausen und stille Stellen an ihrer richtigen Position bleiben; vorhandene Projekte erzeugen die neue Darstellung automatisch beim nächsten Laden.

## Kontextmenüs

Ein Rechtsklick auf einen Video-, Audio- oder Textclip öffnet die passenden Aktionen direkt an der Maus. Bei Video- und Audioclips stehen Vorschau, Teilen, Geschwindigkeit, Lautstärke und Löschen zur Verfügung. Bei Videoclips mit Ton kommt **Audio aus Video extrahieren** hinzu. Textclips bieten zusätzlich den direkten Fokus auf das Textfeld im Inspector. Ein Rechtsklick auf eine leere Stelle bietet **+ Text**, **+ Adjustment-Layer**, **+ Untertitel**, **+ Automatische Untertitel**, Medienimport und das Hinzufügen des ausgewählten Mediums am Spurende.

## Geschwindigkeit

Videoclip auswählen und rechts im Inspector **Geschwindigkeit** ändern. 1× ist normal, 0,5× ist halb so schnell und 2× doppelt so schnell. Die Änderung beeinflusst die Clipdauer sowie Bild und Ton im Export.

## Audio aus Video extrahieren

Videoclip auswählen und im Clip-Inspector auf **Audio aus Video extrahieren** klicken. Framecut erzeugt eine eigene WAV-Datei unter `~/.local/state/framecut/extracted-audio/`, übernimmt nur den ausgewählten Quellbereich in eine neue Audiospur und setzt die Lautstärke des ursprünglichen Videoclips auf 0. Die WAV-Datei wird als Projektmedium gespeichert und bleibt nach einem Neustart verfügbar.

## So funktioniert die Timeline

Die höchste Video-Spurnummer steht oben und liegt im Bild vorne. Ein Videoclip
wird unter Beibehaltung seines Seitenverhältnisses in die Ausgabefläche gesetzt.
Freie Bereiche zeigen den darunterliegenden Clip oder bleiben schwarz. Zoom,
Position, Crop, Rotation, Spiegelung, Farbkorrektur und Videoeffekte gelten pro Videoclip; die
Lautstärke-Kurve gilt lokal pro Medienclip; ohne aktiven
Videoclip ist das Bild schwarz.

Der Originalton **aller nicht stummgeschalteten** Videospuren und alle nicht
stummgeschalteten Audiospuren werden zusammengemischt, auch wenn ein Videoclip
von einer höheren Spur verdeckt wird. Unerwünschten Ton kannst du über **M** im
Spurkopf oder die Clip-Lautstärke auf 0 setzen. Ein Limiter fängt überlaute
Summen ab.

Clips auf derselben Spur dürfen sich nicht überlappen. Ein unzulässiger Mauszug
wird verworfen und in der Statusleiste erklärt. Nichts wird automatisch ersetzt
oder abgeschnitten. Auf unterschiedlichen Spuren sind Überlappungen erlaubt.
Leere Bereiche bleiben beim normalen Löschen erhalten. **Ripple löschen** und **Ripple einfügen** schließen bzw. verschieben die betroffenen Spuren gezielt.

Klicke auf die Zeitleiste, um den Abspielkopf zu setzen. Ziehe den weißen Griff oben am Abspielkopf, um ihn präzise an eine beliebige Stelle zu bewegen. **Teilen** schneidet nur
den ausgewählten Clip, sofern der Abspielkopf innerhalb dieses Clips liegt.
Zeitwerte im Inspector: **Position** ist die Lage im Projekt, **Quellstart** und
**Quellende** sind Zeiten in der ursprünglichen Mediendatei.

## Vorschau — wichtige Änderung gegenüber 0.1

**▶ Timeline** spielt eine einfache, zusammenhängende Videospur direkt aus den
Quelldateien ab. Schnitte wechseln nur das Quellfenster; ein neuer FFmpeg-
Kompositionsrender ist dafür nicht nötig. Bei großen Quellen wird zusätzlich
automatisch ein 360p-Proxy im Hintergrund vorbereitet. Mehrspur-Timelines mit
Audio-Mix, Effekten, Übergängen oder anderen Kompositionen berechnen weiterhin
eine kleine Vorschau der **gesamten** Timeline. Diese Berechnung läuft im
Hintergrund; währenddessen bleibt die Oberfläche bedienbar und der letzte
gültige Vorschauframe sichtbar. Nach einer kurzen Bearbeitungspause werden
mehrere Änderungen gemeinsam verarbeitet.

Das ist noch **keine Live-Mehrspur-Engine**: Bei komplexen langen Timelines kann
die Berechnung spürbar dauern. Reine Schnittprojekte bleiben dagegen direkt
abspielbar, auch während der Proxy im Hintergrund entsteht.
Die Vorschau ist höchstens 480 Pixel hoch; Hochformat ist entsprechend schmal.
Das Exportvideo verwendet die oben ausgewählte Auflösung, nicht die Vorschau.

**Clip ansehen** spielt die ausgewählte Quelle sofort ab, inklusive ihrer
Schnittgrenzen und Lautstärke. Dieser Modus zeigt **nicht** den gesamten Mix.
Die Source-Leiste zeigt die temporären In/Out-Marken. Mit **Insert** wird der
markierte Bereich am aktuellen Abspielkopf eingesetzt und spätere Clips werden
verschoben; **Overwrite** ersetzt nur den überdeckten Bereich. Zum Wechsel zurück
die Wiedergabe pausieren und **▶ Timeline** drücken.

## Autosave und Projekte

Unter Linux standardmäßig:
`~/.local/state/framecut/recovery.framecut`
(bei gesetztem `XDG_STATE_HOME` entsprechend dort).

Die Wiederherstellung wird nach einem Absturz/unerwarteten Abbruch angeboten.
Normales Speichern oder bewusstes Verwerfen beim Schließen entfernt die
Wiederherstellungsdatei. Autosave ersetzt keine reguläre Projektdatei und
sichert keine Videos. Quellvideos nicht löschen oder verschieben.

Nur eine Framecut-3.7-Instanz kann gleichzeitig dieselbe Autosave-Ablage benutzen.
Version 0.1 kann die neuen 0.2-Projekte **nicht** öffnen. Beim Übernehmen alter
Projekte wird ein neuer Projektname vorgeschlagen.

Fehlende Quelldateien werden beim Öffnen gelistet. Über **Medien neu verknüpfen…**
wählst du einen Medienordner; eindeutige Dateinamen werden automatisch gefunden,
mehrdeutige Treffer können einzeln ausgewählt werden. **Archivieren…** erzeugt ein
ZIP mit einer relativen `media/`-Ablage, sodass das Projekt auf einen anderen
Rechner kopiert werden kann. Ein geöffnetes Archiv wird in der lokalen
Framecut-Zustandsablage entpackt und kann direkt weiterbearbeitet werden.

Die **Proxy-Vorschau** liegt neben einer gespeicherten `.framecut`-Datei im Ordner
`<projektname>.proxies`; bei ungespeicherten Projekten wird der lokale Zustandsordner
verwendet. Im Profil-Menü stehen **360p · schnell** und **720p · sauber** zur Auswahl.
Proxy-Dateien sind nur für die Vorschau und werden nicht exportiert. **GPU-Decoding**
nutzt VAAPI oder CUDA, wenn Linux und FFmpeg ein passendes Gerät melden; bei
Treiberproblemen fällt die Vorschau automatisch auf CPU-Decoding zurück.

Der Cache für Poster, Wellenformen und Timeline-Vorschauen liegt unter
`~/.local/state/framecut/cache/` und wird automatisch auf 768 MB begrenzt. **Cache
leeren** entfernt nur erzeugte Vorschaudateien. Über die **Render-Queue** kannst du
im Exportdialog mehrere Ausgaben einreihen und anschließend nacheinander rendern.
Ein abgebrochener Export pausiert die Queue, die übrigen Jobs bleiben erhalten.
Eine nicht lesbare Wiederherstellungsdatei wird vor weiteren Änderungen gesichert.

## Tastenkürzel

| Taste | Funktion |
|---|---|
| Strg + I | Medien importieren |
| Strg + O | Projekt öffnen |
| Strg + S | Speichern |
| Strg + Umschalt + S | Speichern unter |
| Strg + N | Neues Projekt |
| Strg + B / S | Ausgewählten Clip am Abspielkopf teilen |
| Strg + Klick | Mehrere Clips auswählen |
| Strg + C | Auswahl kopieren |
| Strg + V | Auswahl einfügen |
| Strg + Umschalt + V | Auswahl mit Ripple einfügen |
| Strg + D | Auswahl duplizieren |
| Strg + G | Auswahl gruppieren |
| Strg + Umschalt + G | Gruppe lösen |
| Strg + Umschalt + Entf | Ripple löschen |
| Q / W | Ripple-In / Ripple-Out zum Abspielkopf |
| R | Roll-Schnitt zum Abspielkopf |
| Alt + Pfeile | Slide-Schnitt frameweise links / rechts |
| Umschalt + Alt + Pfeile | Slip-Schnitt frameweise links / rechts |
| Strg + Z | Rückgängig |
| Strg + Umschalt + Z | Wiederholen |
| Entf / Rücktaste | Clip entfernen |
| Leertaste | Play/Pause der Timeline |
| Pfeile | Abspielkopf 1 Sekunde bewegen |
| Umschalt + Pfeile | Abspielkopf 5 Sekunden bewegen |
| Home / Ende | Zum Anfang / Ende springen |
| Esc während Ziehen | Mausänderung verwerfen |
| Strg + Mausrad | Timeline zoomen |
| Umschalt beim Ziehen | Einrasten vorübergehend aus |

## Grenzen dieser Version

- Übergänge sind bewusst native FFmpeg-Kompositionen; externe Übergangspakete und proprietäre Effektbibliotheken werden nicht benötigt.
- Automatische Untertitel laufen lokal über faster-whisper; das Modell wird nur beim ersten Einsatz geladen.
- Keine Mehrspur-Ripple-Bearbeitung über unterschiedliche Spurtypen hinweg, wenn die Zielspuren gesperrt sind.
- Der Export hängt bei Hardwareprofilen von den installierten FFmpeg-Encodern
  und Linux-Treibern ab; **Auto** verwendet bei fehlender Hardware CPU-Encoding.
- Viele gleichzeitige Quellen, hohe Bitraten, 60/120 FPS, AV1 oder HDR können
  CPU, Speicher und Renderzeit deutlich stärker beanspruchen.
- Die numerischen Inspector-Felder arbeiten weiterhin sekundengenau; die professionellen Trim-Modi verschieben Quellen und Schnittkanten zusätzlich frameweise anhand der Clip-Bildrate.
- Vorschau-, Poster- und Wellenform-Cache werden automatisch begrenzt; Projektmedien
  werden nicht kopiert. Ein harter Prozessabbruch kann einzelne Cachedateien hinterlassen,
  die beim nächsten Start nach dem Größenlimit bereinigt werden.
- Für die AppImage-Erzeugung wird das externe offizielle `appimagetool` benötigt;
  der Builder erstellt ohne dieses Werkzeug kein unechtes Schein-AppImage. Das
  `.deb`, der ZIP-Installer und die Dateiverknüpfung funktionieren unabhängig davon.

## Tests und Teststatus

Erfolgreich in der Entwicklungsumgebung geprüft:

- Übernahme von 0.1, 0.2-Speichern/Laden samt Medien und Autosave-Daten.
- Grenzen beim Trimmen, Teilen, Einrasten und Überlappungsprüfung.
- Export: obere Videospur überdeckt untere nur während ihrer Laufzeit;
  darunterliegendes Video erscheint danach wieder; Lücken sind schwarz.
- Zeitversetzte Musik, gleichzeitiger Audio-Mix und Stummschaltung durch
  dekodierte Audiosamples geprüft.
- MP4 dekodierbar; Vorschau- und Exportdauer stimmen überein.
- Farbkorrektur mit Helligkeit, Kontrast und Sättigung wird im MP4-Render und im Projekt-Roundtrip geprüft.
- Videoeffekte mit Deckkraft, Unschärfe und Schärfe werden im MP4-Render und im Projekt-Roundtrip geprüft.
- Schritt-4-Effekte werden im MP4-Render geprüft: Slide/Wipe/Zoom/Dip-to-Black, Filter/LUT, Greenscreen, Ellipsenmaske, Speed-Ramping, Freeze-Frame und Reverse.
- Spur-Stummschaltung wird im Audio-Render geprüft; Stumm-/Sperrzustände werden im Projekt-Roundtrip geprüft.
- Linux-Auslieferung: Update-Manifest und SHA-256-Download, `.deb`-Inhalt, AppDir-Shellsyntax, Desktop-Symbol, MIME-Typ und isolierter `install.sh`-Smoke-Test.
- Keyframe-Interpolation für Transformationen, Deckkraft und Unschärfe, Timeline-Marker, Split/Trim-Mitnahme und Inspector-Bedienung werden geprüft.
- Lautstärke-Keyframe-Interpolation, Audio-Render, Split/Trim-Mitnahme und Projekt-Roundtrip werden geprüft.
- Schritt-5-Audio wird mit echtem FFmpeg-Render geprüft: Rauschunterdrückung, 3-Band-EQ, Kompressor, Kanal-/Panorama-Steuerung und Ducking; die Werte werden zusätzlich im GUI-Inspector und Projekt-Roundtrip geprüft.
- Schritt-6-Export wird mit echten Dateien geprüft: 60 FPS und Bitrate, MKV/HEVC/HDR10, WebM/VP9/Opus, Codec-/Container-Validierung und Exportdialog.
- Schritt-7-Projektverwaltung wird mit echten Medien geprüft: Offline-Erkennung und Relink, ZIP-Archiv-Roundtrip mit relativer Medienablage sowie erzeugte Video-/Audio-Proxies.
- Schritt-1-Performance wird mit echten Medien geprüft: 360p-/720p-Proxyprofile, Cache-LRU-Limit, GPU-Erkennungsfallback und ein echter Queue-Export.
- Schritt-2-Timeline wird geprüft: Marker-/Kapitel-Roundtrip, Insert/Overwrite, Ripple-Marker-Verschiebung, Auswahlrahmen, erweitertes Snapping und J/K/L-Transport.
- Medienablage wird mit echtem GUI-Workflow geprüft: Suche, Typfilter, Sortierung, Trefferzähler und korrektes Einfügen aus einer gefilterten Ansicht.
- Standbilder, transparente PNG-Overlays, Bildsequenzen und relative Bildsequenz-Pfade werden im Render und Projekt-Roundtrip geprüft.
- SRT-/VTT-Zeitstempel, mehrzeilige Cue-Texte, Textstilwerte, Animationen, Text-Render und Projekt-Roundtrip werden geprüft.
- Schritt-4-Textworkflow wird geprüft: lokale automatische Untertitel, SRT-/VTT-Export, Filterung benannter Untertitelspuren und native Stilvorlagen für Titel, Untertitel und Lower Third.
- Schritt-5-Effektworkflow wird geprüft: Preset-Roundtrip, Adjustment-Layer ohne Quelldatei, Ease-in/out-Keyframes, Stabilisierung sowie Fade-to-White-, Blur-, Circle-, Radial-, Pixelize-, Smooth- und Cover-Übergänge im echten FFmpeg-Render.
- Mehrfachauswahl, Auswahlrahmen, Kopieren/Einfügen, Duplizieren, Gruppen, Ripple-Löschen, Insert/Overwrite, benannte Spuren und das Löschen leerer Spuren werden im GUI-Workflow geprüft.
- Abbruch während FFmpeg arbeitet schützt vorhandene Zieldateien; Quelldateien
  können weder als Export noch als Projektdatei überschrieben werden.
- UI-Test mit Qt-Mausereignissen und grafischer Timeline: Verschieben, Randtrimmen, Undo/Redo, Teilen,
  Ton auslagern, Autosave schreiben, Clip-Auswahl ohne Abspielkopf-Sprung und echte Videoframes in der Vorschau dekodieren.

```bash
python3 -m unittest -v test_core
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest -v test_gui
```

Noch auf deinem Laptop zu prüfen: Wayland-Fensterverhalten, tatsächliche
Lautsprecherausgabe und Bedienbarkeit mit deinen OBS-Dateien. Hier gibt es keine
reale Soundkarte; Tonmix wurde als exportierte Audiosamples geprüft.

## Fehler melden

Bei Fehlern die Terminalausgabe und die letzten Schritte schicken. Bei einem
Startproblem unter Wayland testweise:

```bash
QT_QPA_PLATFORM=xcb bash start.sh
```

## Dateien

- `app.py`: Oberfläche, Hintergrundaufgaben, Autosave und Vorschauverwaltung.
- `timeline.py`: Mausbedienung, Spurenzeichnung und Einrasten.
- `core.py`: Projektformat, Schnittmodell und FFmpeg-Komposition.
- `preview.py`: Videoframes in einem normalen Qt-Widget zeichnen.
- `style.py`: dunkles Oberflächendesign.
- `test_core.py`, `test_gui.py`: reproduzierbare Tests mit temporären Testmedien.

Eigener Code: MIT, siehe LICENSE. PySide6/Qt und FFmpeg haben eigene Lizenzen und
werden nicht als Binärdateien im ZIP mitgeliefert. Framecut ist ein vorläufiger
Projektname, kein CapCut-Produkt.
