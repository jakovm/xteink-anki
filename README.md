# Xteink X4 / X4 Pro ↔ Anki offline sync

**Offline Anki reviews on the [Xteink X4 or X4 Pro](https://xteink.com) e-ink reader**, with scheduling and AnkiWeb sync still handled by Anki Desktop on your computer.

| Piece | Role |
| --- | --- |
| **Anki add-on** (`xteink_sync`) | Local LAN server: due cards out, reviews in, then normal AnkiWeb sync |
| **X4 / X4 Pro firmware** (CrossPoint patches) | Offline study UI: multi-deck, grades; DE/Greek UI font or reader/SD fonts |

> Community project — not an official Xteink or Anki product. Firmware is a **patch** on [CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader), not a full fork. The X4 Classic and X4 Pro require different firmware binaries.

## Status (v2.5.8)

Working for daily use on X4 / X4 Pro + Anki Desktop (macOS tested). X4 Pro
firmware is built separately from the X4 Classic firmware:

- X4 Classic: CrossPoint 1.4.1, `gh_release` target
- X4 Pro: CrossPoint 1.6.5, ESP32-S3 `x4pro-gh_release` target

### What this branch adds

This branch adds full Xteink X4 Pro firmware support to the existing Anki
offline-sync project. It ports the Anki menus, settings, card review and sync
flows to the Pro-capable CrossPoint base, with dedicated Greek-capable UI
fonts and firmware build artifacts. The existing X4 Classic support remains
available and is built from its original CrossPoint 1.4.1 base. The two board
profiles use separate patches and binaries; never flash one model's binary to
the other.

The Anki add-on and its sync protocol are unchanged by this firmware port.

The current model-specific firmware files are:

- `dist/crosspoint-1.4.1-xteink-anki.bin` — X4 Classic only
- `dist/crosspoint-1.6.5-xteink-anki-x4pro.bin` — X4 Pro only
- `dist/SHA256SUMS` — checksums for both firmware images

Build either image from the repository root with `./firmware/build.sh x4` or
`./firmware/build.sh x4pro`. The pinned CrossPoint source and corresponding
patch details are documented in [`firmware/README.md`](firmware/README.md).

- Pull **all top-level decks with due cards** (not only the open deck)
- **Max cards per deck / total** on X4 web UI **and** device Anki settings (defaults 250 / 1000)
- Deck select/switch on device, progress strip, landscape/portrait, handedness
- Grades: **Again · Hard · Good · Easy** (physical L→R)
- **Card font:** default UI font (German + modern/polytonic Greek); optional reader/SD font for other languages (**Fonts** page)
- Push reviews with batch id (safe retries); scheduler runs on the Mac
- **XFD converter** on pull: HTML/Markdown tables, lists, headings → e-ink plain text
- **Bold on e-ink (Phase B):** `**…**` / `<b>` → mixed bold/regular runs on the X4

Known limits of the offline model: learning steps after Again/Hard are re-queued **locally** on the X4; final intervals always come from Anki’s scheduler after push.

## Quick start

### 1. Anki Desktop (Mac/Windows/Linux)

1. Download `xteink_sync.ankiaddon` from the [latest Release](https://github.com/jakovm/xteink-anki/releases/latest) (add-on **2.4.0+** recommended).
2. Anki → **Tools → Add-ons → Install from file…**
3. Restart Anki.
4. **Tools → Xteink Status** → note **LAN URL** and **API token**.
5. Allow Anki through the OS firewall for local network connections.

Optional config: **Tools → Add-ons → Xteink X4 E-Ink Offline Sync → Config** (`max_cards`, port, …).

### 2. Xteink X4 or X4 Pro

1. Download the firmware for your exact model from the same Release (check `SHA256SUMS`):
   - X4 Classic: `crosspoint-1.4.1-xteink-anki.bin`
   - X4 Pro: `crosspoint-1.6.5-xteink-anki-x4pro.bin`
2. Flash only the matching binary: the X4 Classic build requires CrossPoint **1.4.1**; the X4 Pro build requires the **X4 Pro** board and CrossPoint **1.6.5** layout. Use the CrossPoint web flasher (“Custom .bin”) or **Settings → Firmware from SD**. **Do not cross-flash between models.**
3. On the device: **Data transfer → Join network**.
4. In a browser: `http://crosspoint.local/settings` → **Anki Offline Sync**
   - Mac server URL, e.g. `http://192.168.1.23:5050` — **or** on device:
     **Anki → Anki-Einstellungen → Mac-Server suchen** (mDNS `_xteink-anki._tcp`)
   - API token from Anki (**Tools → Xteink Status**; not auto-discovered)
   - Max cards per deck / total (sent on each pull)
   - Card font: leave **Use reader / SD font** off for Greek; turn on after uploading a font under **Fonts**
5. Home → **Anki** → load today’s cards, study, push reviews when back on Wi‑Fi.

With Anki open, the add-on advertises the LAN service on the configured `port`
(default 5050). Ensure Anki is allowed through the OS firewall.

Reserve a DHCP lease for the computer so the server IP stays stable.

Full firmware build/flash notes: [`firmware/README.md`](firmware/README.md).

## Data flow

```text
AnkiWeb ←→ Anki Desktop (scheduler) ←LAN→ Xteink X4 (offline reviews)
                 │
                 ├─ GET  /pull   → due cards (JSON or NDJSON)
                 └─ POST /push   → review log (batch_id = pull_id)
```

The add-on does **not** write Anki’s SQLite directly. Collection access goes through Anki’s serialized ops; after a successful push it can trigger the normal AnkiWeb sync.

## E-ink flashcard dialect (XFD)

Anki cards are HTML on the desktop. The X4 has **no browser** and only draws **plain text lines** (plus optional bold for UI chrome). Full CommonMark or GFM would be wasted complexity and bad for short review sessions.

**XFD** (*Xteink Flashcard Dialect*) is a **small Markdown-inspired subset** aimed at grammar overviews and other structured cards—especially **tables**—that still fit a monochrome e-ink screen.

The **Mac-side converter** lives in `xteink_sync/textutil.py` (`to_device_text` / `plain_text`) and runs on every `/pull`. Write cards in this subset (or Anki HTML that maps to it); the device still only receives plain `front` / `back` strings—no Markdown parser on the X4.

### Goals

| Goal | Implication |
| --- | --- |
| Readable paradigms | Small tables, short cells |
| Fast reviews | One idea per card; 1–2 screen pages max |
| Stable on ESP32 | No nested HTML, no images, no CSS |
| Grammar-first | Tables, lists, bold lemmas/endings beat prose |

### Supported syntax (authoring)

**Tier 1 — use freely**

| Construct | Markdown | On device (target) |
| --- | --- | --- |
| Paragraphs / line breaks | blank line, hard break | blank line / new line |
| **Bold** | `**lemma**` or `__lemma__` / `<b>` | STX/ETX markers in pull payload; X4 draws bold runs (also accepts raw `**…**`) |
| Unordered list | `- item` / `* item` | `• item` |
| Ordered list | `1. item` | `1. item` |
| Table | GFM pipe table, **2–4 columns** | **Vector grid** (`\x04table…`, 1px lines); wide → stacked |
| Figure | `[fig:stem|…]` / stress / timeline | **Vector fig** (`\x04fig t=…`, boxes + lines) |

**Tier 2 — optional**

| Construct | Markdown | On device (target) |
| --- | --- | --- |
| One title | `#` or `##` once at top | first line, slightly stronger |
| Inline code | `` `-ω, -εις` `` | monospaced if available, else `` `…` `` kept or plain |
| Block quote | `> tip` | `│ tip` or indented line |
| Separator | `---` | thin rule or blank + `────` |

**Not in XFD** (ignored or stripped): images, links as navigation, nested lists beyond one level, task lists, footnotes, HTML/CSS blocks, wide tables (>4 columns), long fenced code, YAML front matter.

### Tables (grammar)

Tables are the main reason XFD exists. Prefer **atomic paradigms**, not chapter dumps.

| Guideline | Recommendation |
| --- | --- |
| Columns | **2–4** (e.g. person × number, case × gender) |
| Cell length | ~1–2 words / ≤ ~12–20 characters |
| Header | first row = labels; first column may be row labels |
| Size that works | **2×3** ideal; **3×3** OK with short forms; **4×4** only with tiny cells |
| Card split | Sg on one card, Pl on another if it no longer fits one screen |
| Cloze-in-table | use `?` or Anki cloze in **one** cell; rest filled |

**Authoring example (Markdown → intended device layout):**

```markdown
## λύω — Present Active

|    | Sg     | Pl        |
| -- | ------ | --------- |
| 1  | λύω    | λύομεν    |
| 2  | λύεις  | λύετε     |
| 3  | λύει   | λύουσι(ν) |
```

**Figures (vector, no images):**

```text
[fig:stem|λυ-|-ω|λύω]
[fig:stress:2|κα|λη|μέ|ρα]
[fig:timeline:1|Verg.|Jetzt|Zukunft|Aorist?]
```

Or fenced: ` ```fig stem ` / `stress N` / `timeline N` with `|`-separated cells.

Target plain layout after conversion (ASCII box — UI_12 has no Unicode box glyphs):

```text
λύω — Present Active

+---+-------+----------+
|   | Sg    | Pl       |
+---+-------+----------+
| 1 | λύω   | λύομεν   |
| 2 | λύεις | λύετε    |
| 3 | λύει  | λύουσι(ν)|
+---+-------+----------+
```

**Card patterns that work well**

| Pattern | Front | Back |
| --- | --- | --- |
| Full paradigm | lemma + tense/voice label | small table |
| One form | “2 pl. pres. act. of λύω” | λύετε |
| Rule list | “Aorist passive marker?” | short `-` list |
| Contrast | “Imperfect vs aorist (aspect)” | 2-column mini table |
| Gap table | grid with one `?` | full cell + one-line hint |

### Converter (design)

The converter is the **Mac-side** step on pull (Anki add-on), not a second app on the X4. Firmware stays a dumb line renderer until optional bold spans exist.

```text
Anki note / template
        │
        ▼
  render HTML (or raw field text)
        │
        ▼
  XFD converter  ──  xteink_sync (textutil + helpers)
        │
        ├─ strip scripts/styles/media noise
        ├─ map HTML structure → XFD constructs
        ├─ parse pipe tables / list-ish HTML
        ├─ layout tables to fixed columns
        ├─ bold/code → markers or plain
        └─ clamp length (max_text_chars)
        │
        ▼
  front / back strings in /pull JSON|NDJSON
        │
        ▼
  X4 draws wrapped lines
```

**Inputs the converter should accept**

1. **Normal Anki HTML** from `render_output` / templates (`<table>`, `<ul>`, `<b>`, `<p>`, …).  
2. **XFD-ish Markdown in fields** if the note stores Markdown (or a Markdown add-on left raw source)—detect pipe tables and `**bold**` when tags are absent.  
3. **Already plain text** with manual spacing—pass through with light cleanup.

**HTML → XFD mapping (core)**

| HTML | XFD / device text |
| --- | --- |
| `<p>`, `<div>`, `<br>` | paragraph / newline |
| `<b>`, `<strong>`, `<h1>`–`<h2>` | bold / title line |
| `<ul><li>` | `• …` |
| `<ol><li>` | `1. …` |
| `<table>` | column-aligned block + header rule |
| `<blockquote>` | `│ …` |
| `<code>`, `<tt>` | inline code treatment |
| `<img>` | `[alt]` or `[Bild]` (unchanged policy) |
| `<a href>` | link text only |
| nested junk | flatten one level; drop deeper chrome |

**Table layout algorithm (planned)**

1. Read header + body rows; drop empty trailing columns.  
2. If **>4 columns**, either split logically (if row labels suggest it) or fall back to **stacked lines** `Col: value` so nothing is silently cropped.  
3. Measure display width budget (portrait/landscape safe area, card font metrics later; v1: character budget, e.g. ~32–42 cols portrait).  
4. Pad cells; insert header underline (`────` / spaces).  
5. Prefer **row labels in column 0**; align numeric/short form columns to the left for mixed scripts (Greek + Latin).  
6. If the block still exceeds vertical budget, keep the table intact and let the existing **card pager** scroll—do not reflow mid-row.

**Bold and emphasis (Phase B — implemented)**

- Converter turns `**…**`, `__…__`, `<b>`, `<strong>` into zero-width markers **STX** (`U+0002`) / **ETX** (`U+0003`) inside `front`/`back`.  
- X4 `drawTextPage` measures and paints **mixed regular/bold runs** (word-wrap aware).  
- Fallback on device: unpaired visible `**` toggles bold (for raw Markdown that skipped conversion).  
- Older firmware may show nothing or odd glyphs for STX/ETX — flash a bin that includes Phase B. Add-on-only update still keeps tables/lists readable.

**Where it lives in the repo**

| Piece | Role |
| --- | --- |
| `xteink_sync/textutil.py` | pure conversion (unit-tested, no `aqt`) |
| `xteink_sync/__init__.py` | call converter after Anki render on `/pull` |
| `tests/test_textutil.py` | dialect fixtures: tables, lists, Greek, overflow |
| Firmware | optional later: bold spans only; **no** full Markdown parser on device |

**Non-goals of the converter**

- Pixel-perfect CSS or Anki card themes  
- Shipping images or audio to the X4  
- Round-trip editing of Markdown on the device  
- Guaranteeing huge “cheat sheet” notes—authors should split cards  

**Status:** dialect + converter **implemented** in `textutil` (tables, lists, headings, quotes, bold markers). Phase B bold drawing **implemented** in the X4 firmware patch (`AnkiActivity::drawTextPage`).

### Author checklist

- [ ] One paradigm or rule per card  
- [ ] Table ≤ 4 columns, short cells  
- [ ] Fits roughly 1–2 e-ink pages  
- [ ] Front asks something; back is the table/list—not a textbook  
- [ ] No essential info only in images  

## HTTP API (summary)

Base URL: `http://<PC-IP>:5050`

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /health` | no | Liveness |
| `GET /pull` | token | Due cards (`Accept: application/x-ndjson` for streaming) |
| `POST /push` | token | Reviews JSON or CSV |

Auth header: `Authorization: Bearer <token>` or `X-Xteink-Token: <token>`.

Ease values: `1=Again`, `2=Hard`, `3=Good`, `4=Easy`. Details and examples: see the German long-form API section below or the release notes.

## Repository layout

```text
xteink_sync/     Anki add-on source (pull/push; textutil = XFD converter)
firmware/        Anki patches and build scripts for X4 Classic / X4 Pro
dist/            Prebuilt .ankiaddon + .bin + SHA256SUMS
tests/           Protocol / textutil (XFD) unit tests
scripts/         Layout helpers
```

Card content contract for grammar-style notes: **[E-ink flashcard dialect (XFD)](#e-ink-flashcard-dialect-xfd)**.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile xteink_sync/*.py

# Rebuild add-on package
rm -f dist/xteink_sync.ankiaddon
( cd xteink_sync && zip -r ../dist/xteink_sync.ankiaddon \
    __init__.py config.json config.md manifest.json \
    protocol.py textutil.py user_files )

# Rebuild firmware (needs PlatformIO / pioarduino)
./firmware/build.sh x4
./firmware/build.sh x4pro
```

## Sharing with Anki & Xteink communities

- **Anki users:** install the add-on only; any compatible client could use the HTTP API.
- **Xteink / CrossPoint:** use the release binary or rebuild from the patch; please report issues against *this* repo first, not upstream CrossPoint, unless the bug is in base CrossPoint.

Upstream merge into official CrossPoint is **not** assumed — this stays a community patch unless maintainers want it.

## License

MIT — see [`LICENSE`](LICENSE). CrossPoint upstream is MIT; Anki itself is AGPL-3.0 (runtime dependency of the add-on).

## Security

LAN-only, token-protected. See [`SECURITY.md`](SECURITY.md).

---

## Kurzanleitung (Deutsch)

### Anki am Rechner

1. `xteink_sync.ankiaddon` aus dem [Release](https://github.com/jakovm/xteink-anki/releases/latest) installieren (**2.4.0+** empfohlen).
2. Anki neu starten → **Werkzeuge → Xteink Status** → LAN-Adresse und API-Token notieren.
3. Optional unter **Werkzeuge → Erweiterungen → Config**: `max_cards`, `max_total_cards`, Port, …

### Xteink X4 / X4 Pro

1. Das zum Modell passende Firmware-Bin flashen:
   - X4 Classic: `crosspoint-1.4.1-xteink-anki.bin` (CrossPoint **1.4.1**)
   - X4 Pro: `crosspoint-1.6.5-xteink-anki-x4pro.bin` (X4 Pro / CrossPoint **1.6.5**)
   - **Binaries nicht zwischen X4 Classic und X4 Pro austauschen.**
2. **Datentransfer → Netzwerk beitreten** → im Browser `http://crosspoint.local/settings`.
3. Unter **Anki Offline Sync**:
   - Mac-Server-URL und API-Token
   - **Max. Karten pro Stapel** / **gesamt**
   - Kartenschrift: für Griechisch den Reader-Schalter **aus** lassen
4. Für andere Sprachen: **Fonts** hochladen → Schrift wählen → **Use reader / SD font** an.
5. Am Gerät: **Anki** → heutige Karten laden → lernen → Bewertungen übertragen.

Am Gerät unter **Anki → Anki-Einstellungen** ebenfalls: Server, Token, Max-Karten, **Kartenschrift** (UI DE/Griechisch oder Reader/SD).

Details zum Bauen/Flashen: [`firmware/README.md`](firmware/README.md) (Deutsch).

### Flashcard-Dialekt (XFD) — Deutsch

**XFD** (*Xteink Flashcard Dialect*) ist ein kleines, Markdown-ähnliches Subset für **strukturierte Karten** auf dem X4 — vor allem **Grammatik-Tabellen**. Kein volles CommonMark: das Gerät zeichnet Zeilen, keinen HTML-Browser.

**Heute:** Converter beim `/pull` (`to_device_text`): Tabellen, Listen, Überschriften, Zitate, Trenner; **Fett** als STX/ETX-Marker. Die X4-Firmware zeichnet gemischte Bold/Regular-Läufe (plus Fallback `**…**`). Inline-Code-Backticks entfallen (Inhalt bleibt).

#### Was du schreiben solltest

| Stufe | Konstrukt | Schreibweise | Ziel auf dem Gerät |
| --- | --- | --- | --- |
| 1 | Absätze | Leerzeile | Zeilenumbruch |
| 1 | **Fett** | `**Lemma**` / `<b>` | Bold auf dem X4 (STX/ETX bzw. `**`) |
| 1 | Listen | `- …` / `1. …` | `• …` / `1. …` |
| 1 | Tabelle | Pipe-Tabelle, **2–4 Spalten** | fest ausgerichtete Spalten + Kopfzeile |
| 2 | eine Überschrift | `#` / `##` oben | erste Zeile hervorgehoben |
| 2 | Inline-Code | `` `-ω, -εις` `` | Muster/Endungen |
| 2 | Merksatz | `> …` | `│ …` |
| 2 | Trenner | `---` | `────` oder Leerzeile |

**Nicht XFD:** Bilder als Inhalt, Links zum Navigieren, verschachtelte Listen, Task-Listen, Footnotes, CSS/HTML-Ballast, Tabellen mit mehr als 4 Spalten, lange Code-Blöcke.

#### Tabellen für Grammatik

- **2×3** (Person × Numerus) ideal; **3×3** ok bei kurzen Formen; ab **4×4** splitten  
- Zellen kurz (1–2 Wörter); eine Karte = ein Paradigma oder eine Regel  
- Bei Platznot: Singular und Plural auf **zwei Karten**  
- Lücke: eine Zelle `?` oder Cloze, Rest ausgefüllt  

Beispiel Ziel-Layout:

```text
λύω — Präsens Aktiv

        Sg          Pl
1.      λύω         λύομεν
2.      λύεις       λύετε
3.      λύει        λύουσι(ν)
```

Gute Muster: volles Paradigma · eine Form abfragen · Regelliste · Kontrast-Zweispaltig · Raster mit einer Lücke.

#### Converter (Konzeption)

Läuft **auf dem Mac im Add-on** beim `/pull`, nicht auf dem X4.

```text
Anki (HTML oder Feldtext)
    → XFD-Converter (textutil)
    → front/back im Pull
    → X4 zeichnet Zeilen
```

**Aufgaben des Converters**

1. Scripts/Styles/Media-Rauschen entfernen (wie bisher Bilder → `[alt]` / `[Bild]`)  
2. HTML-Struktur mappen: `<table>`, `<ul>`/`<ol>`, `<b>`/`<strong>`, `<p>`/`<br>`, `<blockquote>`, `<code>`  
3. Rohes Markdown in Feldern erkennen, wenn keine Tags da sind (Pipe-Tabellen, `**fett**`)  
4. Tabellen layouten: max. 4 Spalten, Zeichenbudget, Kopf + Linie; bei zu vielen Spalten stapeln (`Spalte: Wert`) statt still abschneiden  
5. Länge begrenzen (`max_text_chars`); pager auf dem Gerät übernimmt den Rest  

**Bold (Phase B):** Converter setzt Marker; Firmware rendert Runs. **Kein** voller Markdown-Parser auf dem ESP32.

**Tests:** Fixtures in `tests/test_textutil.py` (Tabellen, Listen, Griechisch, Überbreite). Details und englische Spezifikation: Abschnitt **E-ink flashcard dialect (XFD)** oben.

---

## API details (DE / long form)

### Status

```http
GET /health
```

### Tageskarten laden

Optional Query: `?max_cards=250&max_total=1000` (vom X4 gesetzt; Grenzen 1–1000).

```http
GET /pull
Authorization: Bearer <API-TOKEN>
```

JSON-Beispiel:

```json
{
  "status": "success",
  "protocol_version": 2,
  "pull_id": "e6b4f2c58b954f77956792816ca17db3",
  "server_time": 1785349777,
  "decks": [
    {"id": "1512345678901", "name": "Greek", "card_count": 1}
  ],
  "cards": [
    {
      "id": "1700000000000",
      "front": "Question",
      "back": "Answer",
      "card_type": "review",
      "is_learning": false,
      "queue": 2,
      "reps": 12,
      "mod": 1785300000,
      "deck_id": "1512345678901",
      "deck_name": "Greek"
    }
  ]
}
```

Mit `Accept: application/x-ndjson` streamt der Server Kopfzeile, eine JSON-Zeile pro Karte und eine Abschlusszeile (ESP32-C3-freundlich).

### Bewertungen zurücksenden

```http
POST /push
Authorization: Bearer <API-TOKEN>
Content-Type: application/json

{
  "batch_id": "<pull_id>",
  "reviews": [
    {
      "card_id": "1700000000000",
      "ease": 3,
      "answered_at_ms": 1785391200123,
      "duration_ms": 4200
    }
  ]
}
```

`batch_id` macht Retries sicher (`duplicate` wenn schon verarbeitet). CSV bleibt kompatibel; optional `X-Xteink-Batch-ID`.

### Offline-Grenze

Ein morgendlicher Snapshot kennt Lernschritte nach Again/Hard nicht vollständig. Der X4 plant lokal nach und protokolliert mehrfach; die endgültige Terminierung macht immer Anki auf dem Rechner.
