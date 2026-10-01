# Framecut Asset-Bibliothek

Framecut 3.26 bringt offline nutzbare Starter-Assets direkt im
Editor mit. Die Modusleiste öffnet getrennte Sammlungen für Sound, Textdesign,
Animationen, Sticker, Effekte, Übergänge und Filter. Alles benötigt
keinen Account und keinen Download von Drittanbieter-Paketen.

## Inhalt

- **Sounds:** Whoosh, Pop, Click, Impact, Riser und Tick. Die WAV-Dateien
  werden beim ersten Verwenden deterministisch im Framecut-Benutzerordner
  erzeugt und danach wiederverwendet.
- **Videoeffekte:** Cinematic, Dream, Noir, Vivid, Soft Focus und Stabilize.
  Sie setzen die vorhandenen Clip- und Adjustment-Layer-Parameter.
- **Animationen:** Zoom In, Zoom Out, Slide Left, Slide Up, Text Fade und
  Text Slide. Videoanimationen werden als normale Transform-Keyframes angelegt;
  Textanimationen nutzen das bestehende Textanimationssystem.
- **Übergänge:** Dissolve, Slide, Zoom und Dip to Black. Ein Übergang wird auf
  den ausgewählten eingehenden Clip angewendet und braucht wie jeder andere
  Framecut-Übergang einen direkt angrenzenden Clip derselben Spur.
- **Textdesigns:** Titel, Untertitel und Lower Third. Das Design wird vor der
  Texteingabe ausgewählt und vollständig auf den neuen Textclip übernommen.
- **Sticker:** Stern, Herz, Sparkle, Blitz, Check und Pfeil. Die Sticker sind
  editierbare lokale Textobjekte und benötigen keine externen Downloads.
- **Filter:** Vivid, Warm, Cool, Cinematic, Vintage und Noir. Sie werden auf
  den ausgewählten Videoclip angewendet und bleiben mit dem Projekt erhalten.

## Bedienung

Suche und Kategorie-Filter wirken sofort. **Vorschau** steht für Sounds zur
Verfügung. **Verwenden** fügt einen Sound auf einer freien Audiospur ein oder
wendet ein Preset auf den ausgewählten Clip an. Sounds können zusätzlich aus
der Liste direkt auf eine Audiospur der Timeline gezogen werden. Die sieben
dedizierten Modusleisten zeigen jeweils nur ihre eigene Sammlung und erklären
im Detailfeld, ob ein Element eingefügt oder auf die Auswahl angewendet wird.

## Eigene Assets importieren

In jedem Bereich gibt es **＋ Eigenen Import**. Sounds können als WAV, MP3,
FLAC, OGG, M4A oder AAC importiert werden. Eigene Effekte, Animationen,
Übergänge, Textdesigns und Sticker werden als JSON-Preset eingelesen. Filter
akzeptieren zusätzlich `.cube`- und `.3dl`-LUT-Dateien. Die Dateien werden in
den lokalen Framecut-Benutzerordner kopiert; die Originale bleiben unverändert.

Ein JSON-Preset verwendet dieses Format:

```json
{
  "title": "Mein Effekt",
  "category": "effects",
  "description": "Kurze Beschreibung",
  "tags": ["custom", "look"],
  "parameters": {"effect_preset": "cinematic"}
}
```

Die Kategorie muss zum geöffneten Bereich passen. Unterstützt werden
`effects`, `animations`, `transitions`, `text_styles`, `stickers` und
`filters`.
