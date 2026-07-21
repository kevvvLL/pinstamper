# PinStamp

A tiny local web tool for stamping numbered pins + direction arrows onto any
PDF — by hand, one click at a time. Built for annotating plan drawings
(site plans, floor plans, inspection photo-location diagrams, punch lists —
anything where you need to say "photo/item #7 is right here, facing that
way") without a heavyweight CAD or PDF-editing suite.

No auto-detection, no AI, no cloud — it's a precise, deliberate clicking
tool that runs entirely on your machine.

![PinStamp sample export: four colored pins with per-pin size, style, and arrows](docs/screenshot.png)

## Why

Most "add a comment to a PDF" tools either flatten your markup into the page
(so it can never be edited again) or require a full desktop PDF editor.
PinStamp does neither:

- **Non-destructive while you work.** The source PDF is never touched. Every
  pin lives in a sidecar `<name>.pinstamp.json` next to it, autosaved on every
  change — close the tab, reopen the same PDF later, and you're exactly
  where you left off, like a project file.
- **Real, editable PDF output.** "Export marked PDF" writes each pin as a
  genuine PDF annotation (Circle / Line / Polygon / FreeText) — not
  rasterized or flattened content. Anyone opening the exported file in Adobe
  Acrobat/Reader (no PinStamp install needed) can select, move, recolor, or
  delete a mark afterward, the same as any PDF comment.
- **Per-pin style.** Each pin has its own color (from a small built-in
  palette), size, and border style (solid/dashed/no circle at all), and an
  optional direction
  arrow whose angle and length can be re-aimed at any time after placement —
  no need to delete and redo it.

## Quick start

```bash
pip install -r requirements.txt
python -m pinstamp.core path/to/plan.pdf
```

This opens your default browser to a local page (`http://127.0.0.1:8766`)
with the PDF loaded. Try it immediately on the bundled sample:

```bash
python -m pinstamp.core sample/sample-plan.pdf
```

### Using it

- **Click** on the drawing to drop a numbered pin, then **move the mouse** to
  aim its arrow, then **click again** to fix the direction and advance to the
  next number.
- **Right-click** cancels a pin placement that's in progress.
- **Pin only** — toggle this to place a bare numbered pin with a single
  click, no arrow at all.
- **Stretch arrow** — toggle this to make the second click's distance set the
  arrow's length, instead of using the fixed default.
- **Color / Size / Solid–Dashed–None** — pick before placing new pins, or change
  any already-placed pin from the list below the canvas at any time.
- **↻ aim** (per pin, in the list) — re-aim or add an arrow to a pin you
  already placed: click it, move the mouse, click the canvas to confirm.
- **⊘** removes a pin's arrow; **✕** deletes the pin entirely.
- **Export marked PDF** writes `<name>_marked.pdf` next to your source file.
  Exporting never overwrites a previous export — repeated exports get
  `_marked_v2.pdf`, `_marked_v3.pdf`, and so on.

## Packaging as a standalone .exe (Windows)

No Python install needed for end users — just a double-click launcher with a
native "Open PDF" file picker.

```bash
build.bat
```

Produces `dist/PinStamp.exe` (via PyInstaller; onefile, ~50MB). First run may
be flagged by Windows SmartScreen since the exe isn't code-signed — click
"More info" → "Run anyway".

## How it works

- `pinstamp/core.py` — a stdlib `http.server` bound to `127.0.0.1` only, plus
  [PyMuPDF](https://pymupdf.readthedocs.io/) for page rendering and PDF
  annotation writing. The browser page is a single HTML/JS file served
  in-memory; a `<canvas>` overlay handles the live click-to-place interaction
  against a rendered PNG of the current page.
- `gui.py` — a minimal tkinter launcher (file-picker → starts the server →
  opens the browser) for the packaged exe.
- Nothing leaves your machine. There's no network call other than the local
  server your own browser talks to.

## Customizing the palette

Colors live in a single list near the top of `pinstamp/core.py`:

```python
PALETTE = [
    ("Maroon", "#800000"),
    ("Red", "#d32f2f"),
    ...
]
```

Edit, add, or remove entries to match your own house style — the browser UI
and the exported PDF colors both read from this one list.

## License

MIT — see [LICENSE](LICENSE).
