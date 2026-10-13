# X4- und X4-Pro-Firmware für CrossPoint

Die Firmware wird aus zwei festgelegten CrossPoint-Versionen gebaut: 1.4.1 für
den X4 Classic und 1.6.5 für den X4 Pro. Für jede Version gibt es einen
separaten Anki-Patch; das große Upstream-Repository wird nicht in dieses
Projekt kopiert.

## X4 Classic

- CrossPoint-Tag: `1.4.1`
- CrossPoint-Commit: `970b2c6ca13d663eff1bcee9778dc48359d2ab70`
- Patch: `patches/crosspoint-1.4.1-anki.patch`

## X4 Pro

- CrossPoint-Tag: `1.6.5`
- CrossPoint-Commit: `93e98bb78702e29868a16a13b80c40e6b36ccdff`
- PlatformIO-Umgebung: `x4pro-gh_release`
- Binary: `dist/crosspoint-1.6.5-xteink-anki-x4pro.bin`
- Patch: `patches/crosspoint-1.6.5-anki.patch`

Die Anki-Integration ergänzt:

- einen eigenen **Anki**-Eintrag im CrossPoint-Hauptmenü,
- Download aller fälligen Stapel als speicherschonendes NDJSON,
- Auswahl und Wechsel zwischen geladenen Stapeln am Gerät,
- persistente Karten, pro-Stapel-Warteschlangen und Bewertungen auf der SD-Karte,
- Offline-Anzeige von Frage und Antwort mit mehrseitigem Text,
- **Kartenschrift:** Standard UI-Schrift mit Deutsch + modernem/polytonischem
  Griechisch; optional Reader-/SD-Schrift für weitere Sprachen,
- **Max. Karten pro Stapel** und **gesamt** in Geräte- und Web-Einstellungen
  (werden beim Pull an das Add-on gesendet),
- Schriftgröße (Klein/Mittel/Groß), Ausrichtung (Hochkant/Quer), Händigkeit,
- Blättern über die Seitentasten (Page Up/Down),
- **Flag:** X4-Seitentasten teilen sich **einen** ADC → Hoch+Runter gleichzeitig
  geht hardwareseitig **nicht**. Stattdessen:
  - **Bestätigen + Hoch/Runter** (Chord über zwei ADCs), oder
  - **Hoch oder Runter ~0,55 s halten** (Kurzdruck blättert beim Loslassen)
  → Rotflag 0↔1; Icon rechts der Progress-Bar; Sync Pull/Push,
- **Progress:** zählt nur abgeschlossene Karten (Gut/Einfach bzw. Hard ohne
  Requeue); **Nochmal** und **Schwer** auf Lernkarten füllen den Balken nicht,
- **Version:** Anki-Menü + Anki-Einstellungen zeigen Firmware-Version im Header
  (CrossPoint-Version plus `anki-2.5.8`; auch Boot/System-Einstellungen),
- Platzhalter bei leeren Kartenseiten; Mac-Add-on mit Feld-Fallback,
- Bewertungen `Nochmal`, `Schwer`, `Gut` und `Einfach`,
- erneute lokale Einplanung von Lernkarten nach `Nochmal`/`Schwer`,
- fehlertoleranten Upload mit Batch-ID (JSON: Reviews + Flags) sowie
- Eingabe von Mac-Serveradresse und API-Token am X4 oder im CrossPoint-Webzugang.

## Bauen

Benötigt werden Git, Python 3.10 oder neuer sowie pioarduino/PlatformIO
(`pio` im PATH oder `~/.platformio/penv/bin/pio`).

**Release-Regel:** Nach jeder Firmware-Änderung (Patch, UI, Sync-Protokoll)
beide Firmware-Varianten bauen und die Binaries sowie `dist/SHA256SUMS`
aktualisieren — nicht nur den Patch.

```bash
./firmware/build.sh x4
./firmware/build.sh x4pro
```

Die Skripte klonen ausschließlich die festgelegten CrossPoint-Versionen in
`.firmware-build/`, prüfen den exakten Commit, wenden den Patch an und erzeugen:

```text
dist/crosspoint-1.4.1-xteink-anki.bin
dist/crosspoint-1.6.5-xteink-anki-x4pro.bin
```

Die Ausgabe des X4-Pro-Builds verwendet PlatformIOs `x4pro-gh_release`-Target
für den ESP32-S3. Der Checkout-Pfad enthält einen kurzen Hash des Patches. Dadurch bleiben
aufeinanderfolgende Firmware-Stände getrennt und ein älterer Build-Ordner kann
keine Konflikte beim Anwenden eines neueren Patches verursachen.

## Flashen (Modell beachten)

- `crosspoint-1.4.1-xteink-anki.bin` ist ausschließlich für den X4 Classic mit
  CrossPoint-1.4.1-Partitionslayout bestimmt.
- `crosspoint-1.6.5-xteink-anki-x4pro.bin` ist ausschließlich für den X4 Pro
  und dessen ESP32-S3-Boardprofil bestimmt.
- Die Binaries nicht zwischen den Modellen austauschen und nicht auf einen X3
  oder ein anderes Board flashen.

Am einfachsten wird die zum Modell passende Datei im offiziellen
CrossPoint-Web-Flasher als **Custom .bin** gewählt. Alternativ lässt sie sich
über **Einstellungen → Firmware von SD** installieren. Während des Updates
müssen Stromversorgung und SD-Karte verbunden bleiben.

## X4 Classic / X4 Pro über den Webzugang einrichten

1. Am X4 **Datentransfer → Netzwerk beitreten** öffnen.
2. Am Mac die auf dem X4 angezeigte Adresse oder
   `http://crosspoint.local/settings` öffnen.
3. Unter **Anki Offline Sync** eintragen:
   - **Mac-Server-URL**, z. B. `http://192.168.1.23:5050`
   - **API-Token** aus **Werkzeuge → Xteink Status** in Anki
   - **Max. Karten pro Stapel** und **Max. Karten gesamt** (1–1000; werden
     beim Pull mitgeschickt)
   - **Kartenschrift / Use reader / SD font:** aus = UI-Schrift mit
     Deutsch/Griechisch; an = Reader- oder SD-Schrift
4. **Save Anki settings** wählen.

**Kartenschrift (Sprachen):**

- **Standard (empfohlen für Griechisch):** UI-Schrift mit Deutsch sowie
  modernem und polytonischem Griechisch. Am Gerät:
  **Anki → Anki-Einstellungen → Kartenschrift → UI (DE/Griechisch)**.
- **Andere Schriften/Sprachen:** Unter **Fonts** eine Schriftfamilie
  hochladen, in **Einstellungen → Schrift** wählen, dann in Anki
  **Kartenschrift → Reader / SD-Schrift** bzw. im Web den Schalter
  **Use reader / SD font** einschalten.

Das Token ist im Webzugang nur beschreibbar: Ein gespeichertes Token wird
nicht an den Browser zurückgesendet. Ein leeres Tokenfeld behält den bisherigen
Wert. Die Daten bleiben auf der SD-Karte über Neustarts hinweg gespeichert.

Die Serveradresse bleibt ebenfalls gespeichert, die IP-Adresse des Macs kann
sich durch DHCP jedoch ändern. Für eine dauerhaft gleiche Adresse empfiehlt
sich eine DHCP-Reservierung für den Mac im Router.

## Alternative Eingabe am Gerät

In **Anki → Anki-Einstellungen** werden eingetragen:

- `Mac-Serveradresse`: zum Beispiel `http://192.168.1.23:5050`
- `API-Token`: aus **Werkzeuge → Xteink Status** in Anki
- `Max. Karten / Stapel` und `Max. Karten gesamt` (per Bestätigen durchschalten)
- `Kartenschrift`: UI (DE/Griechisch) oder Reader / SD-Schrift

Danach:

1. **Heutige Karten laden** – lädt alle fälligen Top-Level-Stapel
2. Bei mehreren Stapeln den gewünschten **Stapel wählen**; während des
   Lernens mit Zurück ins Menü und einen anderen Stapel wählen
3. **Karten lernen** (bei nur einem Stapel) – ohne WLAN
4. **Bewertungen übertragen**, sobald alle Stapel fertig sind und Anki auf
   dem Mac geöffnet ist

Die lokalen Dateien liegen unter `/.crosspoint/anki-*`. Offene Bewertungen
werden erst gelöscht, wenn der Mac den Batch eindeutig bestätigt hat.
