# PinStamper

**Click → aim → click.** Numbered pin placed, arrow set, next number ready.

A tiny local web tool for stamping numbered pins and direction arrows onto
any PDF — built for annotating plan drawings (site plans, floor plans,
inspection photo-location diagrams, punch lists) without a heavyweight CAD
or PDF-editing suite.

No cloud, no account, no license. Runs entirely on your machine.

![PinStamper toolbar and canvas: five pins across solid/dashed/no-border styles, per-pin color and size, and direction arrows, over a sample site plan](docs/screenshot.png)

## Quick start

```bash
pip install -r requirements.txt
python -m pinstamp.core path/to/plan.pdf
```

Your browser opens to `http://127.0.0.1:8766` with the PDF loaded. Try the
bundled sample first:

```bash
python -m pinstamp.core sample/sample-plan.pdf
```

**Requirements:** Python 3.9+ · PyMuPDF (installed via `requirements.txt`) ·
any modern browser

Useful flags:

```bash
python -m pinstamp.core plan.pdf --port 9000     # use a different port
python -m pinstamp.core plan.pdf --no-browser    # don't auto-open a browser tab
```

Windows users who don't want Python at all: see
[Standalone .exe](#standalone-exe-windows).

## Why PinStamper

Marking up a plan usually isn't slow because of the marking — it's the
repetition. In most PDF tools, every point means: select the circle tool,
draw a circle, switch to the text tool, type a number, switch to the arrow
tool, drag a line — then repeat for the next point. Even Bluebeam Revu's
"Sequences" auto-increments the number but still treats the shape and arrow
as separate steps; punch-list apps (Punchly, OpenSpace, etc.) drop numbered
pins but are cloud/mobile products where pin and arrow remain two
disconnected actions.

PinStamper collapses the whole thing into one loop:

> Click to drop the pin → move the mouse to aim its arrow → click to
> confirm. The next number is already active.

A page of dozens of points becomes one continuous motion instead of a
string of tool switches.

## What makes it different

| | PinStamper |
|---|---|
| **Non-destructive** | The source PDF is never touched. Every pin lives in a sidecar `<name>.pinstamp.json`, autosaved on every change — close the tab, reopen the PDF later, and you're exactly where you left off. |
| **Real PDF annotations on export** | "Export marked PDF" writes genuine PDF annotations (Circle / Line / Polygon / FreeText), not flattened raster. Anyone with Acrobat/Reader can select, move, recolor, or delete a mark afterward — no PinStamper needed. |
| **Per-pin style, editable anytime** | Each pin has its own color, size, and border style (solid / dashed / none), plus an optional arrow whose angle and length can be re-aimed after placement — no delete-and-redo. |
| **Fully local** | A stdlib HTTP server bound to `127.0.0.1`. Nothing leaves your machine. |

## Using it

**Placing pins**

- Click the drawing to drop a numbered pin → move the mouse to aim its
  arrow → click again to confirm and advance to the next number.
- Right-click cancels a placement in progress.
- **Pin only** — place a bare numbered pin with a single click, no arrow.
- **Stretch arrow** — let the second click's distance set the arrow's
  length instead of the fixed default.

**Styling**

- Pick Color / Size / Solid–Dashed–None before placing, or change any
  already-placed pin from the list below the canvas.

**Editing placed pins** (from the pin list)

- **↻ aim** — re-aim or add an arrow to an existing pin: click it, move,
  click the canvas to confirm.
- **⊘** removes a pin's arrow · **✕** deletes the pin.

**Files**

- **📤 Upload PDF to edit** (top-right) — open another PDF and mark it up in
  place, without restarting the tool.
- **Export marked PDF** — writes `<name>_marked.pdf` next to the source.
  Repeat exports never overwrite: you get `_marked_v2.pdf`,
  `_marked_v3.pdf`, and so on.
- **⏻ Quit** — shuts down the local server from the page (handy for the
  packaged exe, which has no console).

### Autosave and closing

Every change is written to the sidecar `.pinstamp.json` within a fraction of
a second — there is no "save" button. If the server doesn't hear from the
browser tab for ~15 seconds (e.g. you closed it), it shuts itself down so no
orphaned process is left behind. Run the command again (or double-click the
exe) to resume where you left off.

## Standalone .exe (Windows)

No Python needed for end users — a double-click launcher with a native
"Open PDF" picker.

```bat
build.bat
```

Produces `dist/PinStamper.exe` (PyInstaller, onefile, ~50 MB). First run may
trigger Windows SmartScreen since the exe isn't code-signed — click
**More info** → **Run anyway**.

## How it works

- `pinstamp/core.py` — a stdlib `http.server` bound to `127.0.0.1` only,
  plus [PyMuPDF](https://pymupdf.readthedocs.io/) for page rendering and
  annotation writing. The UI is a single HTML/JS page served from memory; a
  `<canvas>` overlay handles live click-to-place against a rendered PNG of
  the current page.
- `gui.py` — a minimal tkinter launcher (file picker → start server → open
  browser) for the packaged exe.
- The only network traffic is your own browser talking to the local server.

## Customizing the palette

Colors live in one list near the top of `pinstamp/core.py` — both the UI
and the exported PDF read from it:

```python
PALETTE = [
    ("Red",    "#d32f2f"),
    ("Blue",   "#1565c0"),
    ("Green",  "#2e7d32"),
    ("Orange", "#ef6c00"),
    ("Purple", "#6a1b9a"),
    ("Black",  "#212121"),
    ("Teal",   "#00838f"),
]
```

Edit, add, or remove entries to match your house style.

## Troubleshooting

| Problem | Fix |
|---|---|
| Page won't load / connection refused | The server auto-shuts-down after ~15–35 s if no tab ever connects. Rerun the command; if it still doesn't open, browse to the printed URL (`http://127.0.0.1:8766/`) manually. |
| Port already in use | Pass `--port <n>`, or just rerun — `serve()` automatically scans the next 20 ports for a free one. |
| SmartScreen warning on the exe | Expected for an unsigned binary. **More info** → **Run anyway**. |

## License

MIT — see [LICENSE](LICENSE).
