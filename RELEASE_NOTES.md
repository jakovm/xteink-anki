# v2.5.8 — Xteink X4 Pro firmware support

## Firmware

- Added an X4 Pro build using CrossPoint 1.6.5's ESP32-S3 `x4pro-gh_release` target.
- Keep using the CrossPoint 1.4.1 binary for the X4 Classic. The two binaries are
  model-specific and must not be cross-flashed.
- Build with `./firmware/build.sh x4pro`; add-on/API behavior is unchanged.

# v2.5.7 — flag gesture works on X4 hardware

## Firmware

- **Fix: Flag toggle broken** — Up+Down cannot be detected together (one ADC ladder).
- **New gestures:**
  - **Confirm + Up/Down** (chord), or
  - **Long-press Up or Down ~0.55 s** (short press pages on release)
- Flash required.

# v2.5.6 — firmware version in Anki menu

## Firmware

- **Version visible in Anki:** header subtitle on **Anki menu** and **Anki settings**
  (same pattern as CrossPoint Settings). Boot still shows it too.
- Release string: **`1.4.1-anki-2.5.7`** (`CROSSPOINT_VERSION` / `XTEINK_ANKI_FW_VERSION`).
- Flash required to see the label.

# v2.5.5 — flag placement landscape/portrait

## Firmware

- **Flag layout** (approved mocks):
  - **Landscape:** right of progress bar; flag top on bar bottom edge; above grades
  - **Portrait:** right column; bar + deck name shift left; flag bottom-aligned with status
- Flash required.

# v2.5.4 — flag chord Up+Down + progress without Again/Hard requeues

## Firmware

- **Flag-Chord:** **Hoch + Runter** gleichzeitig (statt Page+Down) → Rotflag 0↔1
- **Progress-Bar / Zähler:** nur Karten, die die Session verlassen (kein Requeue).
  **Nochmal** und **Schwer** auf Lernkarten werden **nicht** als Fortschritt gezählt.
- Flash required.

# v2.5.3 — accept pull protocol v3

## Firmware

- Fix: **Unsupported or invalid Anki batch** when add-on sends `protocol_version: 3`
  (flags release). Device now accepts pull meta **v2 and v3**.
- Flash required if you already installed add-on 2.5.x.

# v2.5.2 — offer mDNS search when Anki unreachable

## Firmware

- After **pull/push network failure**: dialog  
  **„Anki nicht erreichbar“** —  
  **Bestätigen** = Mac-Server per mDNS suchen und erneut versuchen;  
  **Abbrechen** = Anki läuft (URL/Token prüfen, Netzwerk-Hinweis).
- Shared helper `AnkiMdns::discoverServerUrl` (Settings + error path).
- Flash required.

# v2.5.1 — LAN mDNS discovery

## Add-on + Firmware

- Mac add-on advertises **`_xteink-anki._tcp`** on the configured **port** (default 5050)
  - macOS: `dns-sd -R`; optional `zeroconf` package elsewhere
  - Config: `mdns_enabled`, `mdns_name`, `port` — **token not published**
- X4 **Anki → Anki-Einstellungen → Mac-Server suchen**: mDNS browse → writes `http://IP:port`
- Token still entered manually (Auth)
- Flash firmware + reload add-on 2.5.1

# v2.5.0 — card flag toggle (Page + Down) + sync

## Firmware + Mac add-on (**breaks old CSV-only push clients**)

- **Chord:** side **Page** + **Down** together toggles Anki **red flag** (0 ↔ 1) on the current card
- **UI:** solid mini flag **right of the progress bar** (bar shortens; no white inner line)
- **Pull:** each card includes `"flag": 0–7` from Anki `card.flags`
- **Push:** JSON only — `{"batch_id","reviews":[…],"flags":[{"card_id","flag"}]}`
  - Flags-only upload allowed (empty `reviews`)
  - Menu **Upload** shows when reviews **or** dirty flags are pending
- Local dirty flags: `/.crosspoint/anki-flags.csv` (cleared on successful push / new pull)
- Protocol version **3**; add-on **2.5.0**
- Flash firmware + reinstall/reload add-on + re-pull cards

# v2.4.11 — vector figures (stem / stress / timeline)

## Firmware + Mac converter

- New **vector figures** next to tables (same `\x04…` family, 1px lines, stack-only):
  - **stem** — `[stem] + [ending]` → `[result]`
  - **stress** — syllable boxes with stress mark (`s=N`)
  - **timeline** — horizontal ticks + diamond marker (`m=N`) + optional event label
- Authoring (converted on pull):
  - `[fig:stem|λυ-|-ω|λύω]`
  - `[fig:stress:2|κα|λη|μέ|ρα]`
  - `[fig:timeline:1|Verg.|Jetzt|Zukunft|Aorist?]`
  - or fenced ` ```fig stem ` … ` ``` `
- API: `emit_fig_stem` / `emit_fig_stress` / `emit_fig_timeline` in `textutil.py`
- Flash firmware + reload add-on + re-pull cards.
- Binary: `dist/crosspoint-1.4.1-xteink-anki.bin`.

# v2.4.10 — 25px gap between card areas

## Firmware

- **Between new areas** (blank lines in card text: lemma↔memory, memory↔paradigm, …):
  fixed **25 px** advance on every font size (front & back).
- Text line pitch: at least 25 px, but never below font advance (no glyph overlap).
- Flash required. Re-pull cards after helper push so section blanks match layout.

# v2.4.9 — tight EN/DE front spacing

## Firmware + Helper

- Front no longer inserts a **blank row** between English and 2nd language — consecutive lines only.
- Medium/large: remaining empty lines (section gaps) use **~¼ line height**; text pad slightly tighter.
- Flash firmware + re-push cards (or re-export) so Front fields lose the old blank line.
- Preview: `dist/line-spacing-en-de-before-after.png`

# v2.4.8 — tighter blank lines for medium/large

## Firmware

- **Medium & large:** empty lines / section gaps use **0.5× line height** (not a full
  line slot that felt like ~1.5× / 2× of air). Small keeps full blank-line height.
- Text lines still use the font’s advance + a small pad (no glyph overlap).
- Binary: `dist/crosspoint-1.4.1-xteink-anki.bin` (flash required).

# v2.4.7 — vector line tables (low RAM)

## Firmware + Mac converter

- Compact tables (2–4 cols, ≤12 single-line rows) ship as a **vector table block**
  (`\x04table …` / cell sep `\x06`) instead of ASCII `+---+` boxes.
- X4 measures cells in **pixels** (proportional fonts / Greek) and draws **1 px**
  grid lines via existing `drawLine` — **no heap**, only `colW[4]` on the stack.
- Styles: **C** conjugation (internal verticals only), **H** header underline + box,
  **B** simple box. Wide tables still **stack** / compact on the Mac.
- Paging: mid-table row continue; whole table deferred to next page when it would
  leave a lonely strip at the bottom.
- **Flash** firmware + **reload add-on** + **re-pull** cards so new blocks are on device.
- Binary: `dist/crosspoint-1.4.1-xteink-anki.bin`.

# v2.4.6 — native medium font (UI_18) with Greek

## Firmware

- **Mittel** uses a new built-in **UI_18** (Ubuntu 18 px) with the same Greek +
  romanization coverage as UI_12 — drawn **native 1×**, not soft 1.5× upscale.
- Sizes (unchanged product intent):
  | Setting | Rendering |
  | --- | --- |
  | Klein | UI_12 @ **1×** |
  | Mittel | UI_18 @ **1×** (native ~1.5× of 12, sharp) |
  | Groß | UI_12 @ **2×** |
- Binary: `dist/crosspoint-1.4.1-xteink-anki.bin` (flash required).

# v2.4.5 — status strip joins multi-line Front as EN / DE (view only)

## Firmware

- Answer-side status strip: multi-line Front (`EN` + blank + `DE`) is shown as a
  **compact view** `EN / DE` (truncated). Display only — card **Back** data stays free of EN/DE.
- Binary: `dist/crosspoint-1.4.1-xteink-anki.bin` (flash required for the join).

# v2.4.4 — front prompt in status row (between progress and deck)

## Firmware

- Answer side: EN/L2 **front** is no longer a line *above* the bar.
- It sits **in the status row**: progress left · front (truncated, centered in middle) · deck name right.
- Same **UI_10** font as progress/deck. Simulated portrait + landscape before build.
- Binary: `dist/crosspoint-1.4.1-xteink-anki.bin` (flash required).

# v2.4.3 — ASCII box tables on pull (Mac converter)

## Add-on / `textutil` (no firmware flash required)

- Markdown/HTML tables convert to a clear **ASCII box** layout (`+`, `-`, `|`) so paradigms read as tables on the X4.
- Wide tables still **stack** as `Header: value` lines when they exceed the width budget.
- UI_12 has **no Unicode box-drawing** glyphs; ASCII is intentional and portable.
- Rebuild/reinstall the Anki add-on (or restart Anki so `textutil.py` reloads), then **pull** cards again.

# v2.4.2 — answer-side front preview in status strip

## Firmware

- **Answer side:** English / second-language **front** text is shown **centered** in the status band (above the progress bar), same **UI_10** font as the progress stats.
- Long fronts are **truncated** to the full status width (especially useful in **landscape**).
- Landscape uses **tighter top gaps** so the wide top area is used for the prompt while body lines stay usable.
- Layout simulated for portrait + landscape before rebuild (`scripts/simulate_anki_layout.py`).

## Markdown / XFD on the X4

Mac add-on converts XFD/Markdown → plain lines (+ bold markers, **vector table blocks** or stacked fallback) on `/pull`. The X4 does **not** parse Markdown; it draws converted text, bold runs (STX/ETX or `**` fallback), and 1 px table grids.


# v2.4.1 — softer Anki menu refresh + font sizes 1× / 1.5× / 2×

## Assets

| File | Purpose |
| --- | --- |
| `xteink_sync.ankiaddon` | Anki Desktop add-on **2.4.0** (unchanged) |
| `crosspoint-1.4.1-xteink-anki.bin` | Xteink X4 firmware (rebuild required) |
| `SHA256SUMS` | Checksums |

## Firmware changes

### Menu e-ink flash (DE: „Flashen“)
- **Before:** every Anki menu selection used `HALF_REFRESH` (heavy full-ish flash).
- **Now:** menu uses the same cadence as cards — mostly **FAST**, `HALF` only every *N* paints (CrossPoint refresh setting).

### Card font sizes
| Setting | Old | New |
| --- | --- | --- |
| **Klein / Small** | 1× | **1×** (unchanged) |
| **Mittel / Medium** | 2× | **1.5×** (new step between old small & medium) |
| **Groß / Large** | 3× | **2×** (= old medium) |

Legacy configs migrate: old medium/large → new large (2×). Saved as `font_scale_scheme: 2`.

### Greek / romanization glyphs
- UI_12 font now includes **Latin Extended Additional** `U+1E00–U+1E9F` (e.g. **ṓ** U+1E53 used in Greek pronunciation), on top of modern Greek `U+0370–U+03FF` and polytonic `U+1F00–U+1FFF`.

## Highlights (EN) — still from v2.4.0

- **XFD** dialect, bold on device, multi-deck pull, Greek UI font

## Highlights (DE) — weiterhin aus v2.4.0

- XFD, Fett auf dem Gerät, Multi-Stapel, griechische UI-Schrift

## Install

1. Firmware neu bauen/flashen (`firmware/build.sh` → Bin auf X4)  
2. Add-on nur bei Bedarf aktualisieren (2.4.0 reicht für diese Änderung)  
3. Schriftgröße in Anki-Settings am Gerät einmal durchschalten (Klein → Mittel → Groß)
