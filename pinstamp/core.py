"""PinStamp — local web page (stdlib http.server, 127.0.0.1 only, PyMuPDF for
rendering/drawing) for manually stamping numbered pins + optional direction
arrows onto any PDF. Nothing here auto-detects anything; every mark is a
deliberate click.

Design goals:
  - Non-destructive: the source PDF is never modified. Every stamp lives in a
    sidecar "<name>.pinstamp.json" next to it, autosaved on every change —
    close the tool and reopen the same PDF to resume exactly where you left
    off, like a project file.
  - Real, editable PDF output: "Export marked PDF" writes each stamp as
    genuine PDF annotation objects (Circle / Line / Polygon / FreeText), not
    flattened page content. Anyone opening the exported file in Adobe
    Acrobat/Reader (no PinStamp install needed) can select, move, recolor, or
    delete a mark afterward — same as any PDF comment.
  - Per-marker style: each pin has its own color (from a small palette),
    size, border style (solid/dashed/none), and an optional arrow whose angle and
    length can be re-aimed at any time after placement.

Usage:  python -m pinstamp.core <pdf_path> [--port 8766]
Then in the browser: click to drop a numbered pin, move the mouse to aim the
optional arrow 360 degrees, click again to fix direction and advance to the
next number. Right-click cancels an in-progress placement. Toggle "Stretch
arrow" to make the second click's distance set the arrow's length instead of
the fixed default. Toggle "Pin only" to place bare numbered pins with no
arrow at all (single click). Already-placed markers can have their color,
size, and border style changed from the list below the canvas, and their
arrow re-aimed with the "aim" button — everything autosaves.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz

HEARTBEAT_TIMEOUT = 15.0  # seconds without a /ping before we assume the
                          # browser tab was closed and the process should exit
                          # (a windowed exe has no console to Ctrl+C)

DEFAULT_SIZE = 10.0   # default pin radius, pt
MIN_SIZE = 4.0
MAX_SIZE = 40.0
BORDER_W = 0.6         # stroke width, pt — constant regardless of pin size
ARROW_LEN_RATIO = 1.8  # default arrow length = size * this ratio
MIN_ARROW_LEN = 8.0
MAX_ARROW_LEN = 200.0
HEAD_LEN_RATIO = 0.42   # arrowhead length along the shaft, relative to size
HEAD_HALF_RATIO = 0.245  # arrowhead half-width, relative to size
ZOOM = 2.0              # PDF pt -> preview PNG px

# a small, deliberately generic palette — pick colors that read clearly at
# small sizes and print well; add/replace entries here to reskin the tool
PALETTE = [
    ("Red", "#d32f2f"),
    ("Blue", "#1565c0"),
    ("Green", "#2e7d32"),
    ("Orange", "#ef6c00"),
    ("Purple", "#6a1b9a"),
    ("Black", "#212121"),
    ("Teal", "#00838f"),
]
DEFAULT_COLOR = PALETTE[0][1]


def hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    h = (hex_color or DEFAULT_COLOR).lstrip("#")
    if len(h) != 6:
        h = DEFAULT_COLOR.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def draw_marker(page: fitz.Page, m: dict) -> None:
    """Add one stamp (pin + number [+ arrow]) to a live fitz page as real PDF
    annotation objects — editable/movable in Acrobat or any annotation-aware
    viewer, not burned into the page's content stream."""
    x, y = m["x"], m["y"]
    size = float(m.get("size") or DEFAULT_SIZE)
    color = hex_to_rgb01(m.get("color"))
    style = m.get("style", "solid")
    angle_deg = m.get("angle")
    length = m.get("length")

    if style != "none":
        circle = page.add_circle_annot(fitz.Rect(x - size, y - size, x + size, y + size))
        circle.set_colors(stroke=color, fill=(1, 1, 1))
        circle.set_border(width=BORDER_W, dashes=[4, 4] if style == "dashed" else [])
        circle.update()

    if angle_deg is not None:
        # a native PDF line-ending arrow (PDF_ANNOT_LE_CLOSED_ARROW) renders
        # at a size the viewer decides from the border width — wildly
        # different between Acrobat, Word, and other renderers. Draw the
        # shaft as a plain line and the head as its own small filled Polygon
        # annotation instead, so the triangle's exact geometry is explicit
        # and renders identically everywhere.
        arrow_len = ARROW_LEN_RATIO * size if length is None else \
            max(MIN_ARROW_LEN, min(MAX_ARROW_LEN, length))
        theta = math.radians(angle_deg)
        ux, uy = math.cos(theta), math.sin(theta)
        p_start = fitz.Point(x + size * ux, y + size * uy)
        p_end = fitz.Point(x + (size + arrow_len) * ux, y + (size + arrow_len) * uy)
        line = page.add_line_annot(p_start, p_end)
        line.set_colors(stroke=color)
        line.set_border(width=BORDER_W)
        line.update()

        head_len = HEAD_LEN_RATIO * size
        head_half = HEAD_HALF_RATIO * size
        bx, by = p_end.x - head_len * ux, p_end.y - head_len * uy
        px, py = -uy, ux
        b1 = fitz.Point(bx + head_half * px, by + head_half * py)
        b2 = fitz.Point(bx - head_half * px, by - head_half * py)
        head = page.add_polygon_annot([b1, p_end, b2])
        head.set_colors(stroke=color, fill=color)
        head.set_border(width=BORDER_W)
        head.update()

    text = str(m["number"])
    fsize = (size * 1.09) if len(text) <= 1 else ((size * 0.98) if len(text) == 2 else size * 0.76)
    tw = fitz.get_text_length(text, fontname="helv", fontsize=fsize)
    trect = fitz.Rect(x - tw / 2 - 1, y - fsize * 0.62, x + tw / 2 + 1, y + fsize * 0.62)
    label = page.add_freetext_annot(trect, text, fontsize=fsize, fontname="helv",
                                     text_color=color, border_width=0, align=1)
    label.update()


def _sidecar(pdf_path: Path) -> Path:
    return pdf_path.with_suffix("").with_name(pdf_path.stem + ".pinstamp.json")


def _load_state(pdf_path: Path) -> dict:
    sc = _sidecar(pdf_path)
    if sc.exists():
        return json.loads(sc.read_text(encoding="utf-8"))
    return {"markers": [], "nextNumber": 1}


def _save_state(pdf_path: Path, state: dict) -> None:
    _sidecar(pdf_path).write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                   encoding="utf-8")


_PAGE = """<!doctype html><meta charset="utf-8"><title>PinStamp</title>
<style>
 body{font-family:"Segoe UI",sans-serif;margin:0;background:#e8e8e8}
 #bar{position:sticky;top:0;background:#fff;padding:8px 14px;border-bottom:2px solid #333;
      display:flex;align-items:center;gap:10px;flex-wrap:wrap;z-index:9}
 #bar b{font-size:15px}
 button{font-size:14px;padding:6px 14px;cursor:pointer}
 button.active{outline:3px solid #2962ff}
 input[type=number]{width:60px;font-size:14px;padding:4px}
 select{font-size:14px;padding:4px}
 #msg{font-weight:bold;color:#2962ff}
 #wrap{padding:20px;overflow:auto}
 canvas{background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.3);cursor:crosshair}
 #list{padding:0 20px 30px;font-size:13px}
 #list table{border-collapse:collapse}
 #list td,#list th{border:1px solid #ccc;padding:3px 8px}
 .del{color:#c00;cursor:pointer}
 .upl{margin-left:auto}
 .swatch{display:inline-block;width:12px;height:12px;border:1px solid #999;
         border-radius:50%;vertical-align:middle;margin-right:4px}
 .swbtn{width:22px;height:22px;padding:0;border:2px solid #fff;border-radius:50%;
        box-shadow:0 0 0 1px #999;cursor:pointer}
 .swbtn.active{box-shadow:0 0 0 2px #2962ff}
</style>
<div id="bar">
 <b>📍 PinStamp</b>
 <label>Page <select id="pageSel"></select></label>
 <button id="btnSolid" class="active">● Solid</button>
 <button id="btnDashed">○ Dashed</button>
 <button id="btnNone" title="No circle border, just the number">Ⓝ None</button>
 <span id="palette"></span>
 <label>Size <input type="number" id="curSize" value="__DEFAULT_SIZE__" min="__MIN_SIZE__" max="__MAX_SIZE__" step="0.5"></label>
 <label>Start # <input type="number" id="startNum" value="1" min="1"></label>
 <button id="btnApply">Apply</button>
 <button id="btnPinOnly" title="Place a bare numbered pin with a single click, no arrow">📍 Pin only</button>
 <button id="btnStretch" title="When on, the 2nd click's distance sets the arrow length instead of the fixed default">📏 Stretch arrow</button>
 <button id="btnUndo">↶ Undo last</button>
 <button id="btnExport" style="background:#c8e6c9">✅ Export marked PDF</button>
 <button id="btnQuit" style="background:#ffcdd2">⏻ Quit</button>
 <span id="msg"></span>
 <span class="upl"><input type="file" id="fileInput" accept="application/pdf"> Upload different PDF</span>
</div>
<div id="wrap"><canvas id="cv"></canvas></div>
<div id="list"></div>
<script>
let doc = {pageCount: __PAGECOUNT__, sizes: __SIZES__};
let curPage = 0;
let markers = __MARKERS__;
let nextNumber = __NEXTNUM__;
let style = 'solid';
let curColor = __DEFAULT_COLOR__;
let stretch = false;
let pinOnly = false;
let pending = null;   // {cx,cy,number,style,color,size,editIndex} awaiting angle/length
let mouse = null;
let img = new Image();
const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
const zoom = __ZOOM__;
const PALETTE = __PALETTE__;
const DEFAULT_SIZE = __DEFAULT_SIZE__;
const MIN_ARROW_LEN = __MIN_ARROW_LEN__ * zoom, MAX_ARROW_LEN = __MAX_ARROW_LEN__ * zoom;
const ARROW_LEN_RATIO = __ARROW_LEN_RATIO__, HEAD_LEN_RATIO = __HEAD_LEN_RATIO__, HEAD_HALF_RATIO = __HEAD_HALF_RATIO__;

const paletteEl = document.getElementById('palette');
PALETTE.forEach(([name, hex]) => {
  const b = document.createElement('button');
  b.className = 'swbtn' + (hex === curColor ? ' active' : '');
  b.style.background = hex; b.title = name; b.dataset.hex = hex;
  b.onclick = () => { curColor = hex; refreshPaletteActive(); render(); };
  paletteEl.appendChild(b);
});
function refreshPaletteActive() {
  [...paletteEl.children].forEach(b => b.classList.toggle('active', b.dataset.hex === curColor));
}

function pageSel() { return document.getElementById('pageSel'); }
for (let i = 0; i < doc.pageCount; i++) {
  const o = document.createElement('option'); o.value = i; o.textContent = 'Page ' + (i + 1);
  pageSel().appendChild(o);
}
pageSel().onchange = () => { curPage = +pageSel().value; pending = null; loadPage(); };

function loadPage() {
  const sz = doc.sizes[curPage];
  cv.width = Math.round(sz.width * zoom);
  cv.height = Math.round(sz.height * zoom);
  img = new Image();
  img.onload = render;
  img.src = '/page.png?n=' + curPage + '&t=' + Date.now();
}

function drawArrowShaft(cx, cy, angleDeg, len, color, sizePx) {
  const th = angleDeg * Math.PI / 180, ux = Math.cos(th), uy = Math.sin(th);
  const sx = cx + sizePx * ux, sy = cy + sizePx * uy;
  const ex = cx + (sizePx + len) * ux, ey = cy + (sizePx + len) * uy;
  ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey);
  ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.setLineDash([]); ctx.stroke();
  const headLen = HEAD_LEN_RATIO * sizePx, headHalf = HEAD_HALF_RATIO * sizePx;
  const bx = ex - headLen * ux, by = ey - headLen * uy, px = -uy, py = ux;
  ctx.beginPath();
  ctx.moveTo(bx + headHalf * px, by + headHalf * py);
  ctx.lineTo(ex, ey);
  ctx.lineTo(bx - headHalf * px, by - headHalf * py);
  ctx.closePath(); ctx.fillStyle = color; ctx.fill();
}

function drawStamp(cx, cy, number, sty, angleDeg, len, color, sizePx, alpha) {
  ctx.globalAlpha = alpha === undefined ? 1 : alpha;
  if (sty !== 'none') {
    ctx.beginPath(); ctx.arc(cx, cy, sizePx, 0, 2 * Math.PI);
    ctx.fillStyle = '#fff'; ctx.fill();
    ctx.setLineDash(sty === 'dashed' ? [4 * zoom, 4 * zoom] : []);
    ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.stroke();
    ctx.setLineDash([]);
  }
  const text = String(number);
  const fsize = (text.length <= 1 ? sizePx * 1.09 : (text.length === 2 ? sizePx * 0.98 : sizePx * 0.76));
  ctx.font = fsize + 'px Helvetica, Arial, sans-serif';
  ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, cx, cy + 0.5);
  if (angleDeg !== null && angleDeg !== undefined)
    drawArrowShaft(cx, cy, angleDeg, len === undefined ? ARROW_LEN_RATIO * sizePx : len, color, sizePx);
  ctx.globalAlpha = 1;
}

function curSizePx() { return (+document.getElementById('curSize').value || DEFAULT_SIZE) * zoom; }

function pendingLenAngle(sizePx) {
  if (!mouse) return {ang: 0, len: ARROW_LEN_RATIO * sizePx};
  const dx = mouse.x - pending.cx, dy = mouse.y - pending.cy;
  const ang = Math.atan2(dy, dx) * 180 / Math.PI;
  if (!stretch) return {ang, len: ARROW_LEN_RATIO * sizePx};
  const dist = Math.hypot(dx, dy) - sizePx;
  const len = Math.max(MIN_ARROW_LEN, Math.min(MAX_ARROW_LEN, dist));
  return {ang, len};
}

function render() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, cv.width, cv.height);
  for (const m of markers) if (m.page === curPage) {
    const sizePx = (m.size || DEFAULT_SIZE) * zoom;
    drawStamp(m.x * zoom, m.y * zoom, m.number, m.style, m.angle,
              (m.length === undefined || m.length === null ? null : m.length * zoom),
              m.color || __DEFAULT_COLOR__, sizePx);
  }
  if (pending) {
    const sizePx = pending.size * zoom;
    const {ang, len} = pendingLenAngle(sizePx);
    drawStamp(pending.cx, pending.cy, pending.number, pending.style, pinOnly ? null : ang, len,
              pending.color, sizePx);
    if (mouse && stretch && !pinOnly) {
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#333';
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      ctx.fillText(Math.round(len / zoom) + 'pt', mouse.x + 10, mouse.y + 10);
    }
  } else if (mouse) {
    const sizePx = curSizePx();
    drawStamp(mouse.x, mouse.y, nextNumber, style, null, ARROW_LEN_RATIO * sizePx, curColor, sizePx, 0.45);
  }
  renderList();
}

function colorOptions(selected) {
  return PALETTE.map(([name, hex]) =>
    `<option value="${hex}" ${hex === selected ? 'selected' : ''}>${name}</option>`).join('');
}

function renderList() {
  const rows = markers.map((m, i) => {
    const hasArrow = m.angle !== null && m.angle !== undefined;
    const lenPt = hasArrow ? Math.round(m.length === undefined || m.length === null ?
      ARROW_LEN_RATIO * (m.size || DEFAULT_SIZE) : m.length) : '—';
    const angText = hasArrow ? Math.round(m.angle) + '°' : '—';
    return `<tr>
      <td>${m.number}</td><td>p${m.page + 1}</td>
      <td><span class="swatch" style="background:${m.color || __DEFAULT_COLOR__}"></span>
          <select onchange="setColor(${i}, this.value)">${colorOptions(m.color)}</select></td>
      <td><select onchange="setRowStyle(${i}, this.value)">
            <option value="solid" ${m.style === 'solid' ? 'selected' : ''}>Solid</option>
            <option value="dashed" ${m.style === 'dashed' ? 'selected' : ''}>Dashed</option>
            <option value="none" ${m.style === 'none' ? 'selected' : ''}>None</option>
          </select></td>
      <td><input type="number" value="${m.size || DEFAULT_SIZE}" min="__MIN_SIZE__" max="__MAX_SIZE__" step="0.5"
                  style="width:55px" onchange="setSize(${i}, this.value)"></td>
      <td>${angText}</td><td>${lenPt}pt</td>
      <td><button onclick="aimMarker(${i})" title="Click, then click the canvas to re-aim">↻ aim</button>
          ${hasArrow ? `<button onclick="stripArrow(${i})" title="Remove arrow">⊘</button>` : ''}</td>
      <td class="del" onclick="delMarker(${i})">✕</td></tr>`;
  }).join('');
  document.getElementById('list').innerHTML =
    '<table><tr><th>#</th><th>page</th><th>color</th><th>style</th><th>size</th>' +
    '<th>angle</th><th>length</th><th>arrow</th><th></th></tr>' + rows + '</table>';
}
function delMarker(i) { if (pending && pending.editIndex === i) pending = null; markers.splice(i, 1); saveMarkers(); render(); }
function setColor(i, hex) { markers[i].color = hex; saveMarkers(); render(); }
function setRowStyle(i, v) { markers[i].style = v; saveMarkers(); render(); }
function setSize(i, v) {
  markers[i].size = Math.max(__MIN_SIZE__, Math.min(__MAX_SIZE__, +v || DEFAULT_SIZE));
  saveMarkers(); render();
}
function stripArrow(i) { markers[i].angle = null; markers[i].length = null; saveMarkers(); render(); }
function aimMarker(i) {
  const m = markers[i];
  pending = {cx: m.x * zoom, cy: m.y * zoom, number: m.number, style: m.style,
             color: m.color, size: m.size || DEFAULT_SIZE, editIndex: i};
  render();
}

function getPos(e) {
  const r = cv.getBoundingClientRect();
  return {x: e.clientX - r.left, y: e.clientY - r.top};
}
cv.addEventListener('mousemove', e => { mouse = getPos(e); render(); });
cv.addEventListener('mouseleave', () => { mouse = null; render(); });
cv.addEventListener('click', e => {
  const p = getPos(e);
  if (!pending) {
    const size = +document.getElementById('curSize').value || DEFAULT_SIZE;
    if (pinOnly) {
      markers.push({page: curPage, x: p.x / zoom, y: p.y / zoom, number: nextNumber,
                    style, angle: null, length: null, color: curColor, size});
      nextNumber++;
      saveMarkers(); render();
      return;
    }
    pending = {cx: p.x, cy: p.y, number: nextNumber, style, color: curColor, size, editIndex: null};
  } else {
    mouse = p;
    const sizePx = pending.size * zoom;
    const {ang, len} = pendingLenAngle(sizePx);
    const angle = pinOnly ? null : ang;
    const length = pinOnly ? null : len / zoom;
    if (pending.editIndex === null) {
      markers.push({page: curPage, x: pending.cx / zoom, y: pending.cy / zoom,
                     number: pending.number, style: pending.style, angle, length,
                     color: pending.color, size: pending.size});
      nextNumber++;
    } else {
      const mk = markers[pending.editIndex];
      mk.angle = angle; mk.length = length;
    }
    pending = null;
    saveMarkers();
  }
  render();
});
cv.addEventListener('contextmenu', e => {
  e.preventDefault();
  if (pending) { pending = null; render(); }
});

document.getElementById('btnSolid').onclick = () => setStyle('solid');
document.getElementById('btnDashed').onclick = () => setStyle('dashed');
document.getElementById('btnNone').onclick = () => setStyle('none');
function setStyle(s) {
  style = s;
  document.getElementById('btnSolid').classList.toggle('active', s === 'solid');
  document.getElementById('btnDashed').classList.toggle('active', s === 'dashed');
  document.getElementById('btnNone').classList.toggle('active', s === 'none');
}
document.getElementById('btnPinOnly').onclick = () => {
  pinOnly = !pinOnly;
  document.getElementById('btnPinOnly').classList.toggle('active', pinOnly);
};
document.getElementById('btnStretch').onclick = () => {
  stretch = !stretch;
  document.getElementById('btnStretch').classList.toggle('active', stretch);
};
document.getElementById('btnApply').onclick = () => {
  nextNumber = +document.getElementById('startNum').value || 1;
  render();
};
document.getElementById('btnUndo').onclick = () => {
  if (markers.length) {
    const last = markers.pop();
    if (last.number === nextNumber - 1) nextNumber = last.number;
    saveMarkers(); render();
  }
};
document.getElementById('btnExport').onclick = async () => {
  msg('Exporting...');
  const r = await fetch('/export', {method: 'POST', body: JSON.stringify({markers, nextNumber})});
  const j = await r.json();
  msg(j.msg);
};
document.getElementById('fileInput').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  msg('Uploading...');
  const buf = await f.arrayBuffer();
  const r = await fetch('/upload', {method: 'POST', headers: {'X-Filename': encodeURIComponent(f.name)}, body: buf});
  const j = await r.json();
  if (j.ok) location.reload(); else msg(j.msg);
};
document.getElementById('btnQuit').onclick = () => {
  if (confirm('Quit PinStamp? (already-placed markers are saved)')) {
    fetch('/quit', {method: 'POST'});
    document.body.innerHTML = '<p style="padding:40px;font-size:16px">Closed. This tab and the background app can now be closed.</p>';
  }
};

let saveTimer = null;
function saveMarkers() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fetch('/markers', {method: 'POST', body: JSON.stringify({markers, nextNumber})});
  }, 300);
}
function msg(t) { document.getElementById('msg').textContent = t; }

// tells the background process the tab is still open; if these stop
// arriving (tab closed, browser crashed) the process exits on its own
setInterval(() => { navigator.sendBeacon('/ping'); }, 3000);

loadPage();
</script>
"""


class _Handler(BaseHTTPRequestHandler):
    pdf_path: Path = None
    upload_dir: Path = None
    httpd: ThreadingHTTPServer = None
    last_ping: float = 0.0

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj).encode(), "application/json")

    def _doc(self):
        return fitz.open(str(self.pdf_path))

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/":
            doc = self._doc()
            sizes = [{"width": p.rect.width, "height": p.rect.height} for p in doc]
            state = _load_state(self.pdf_path)
            doc.close()
            html = (_PAGE
                    .replace("__PAGECOUNT__", str(len(sizes)))
                    .replace("__SIZES__", json.dumps(sizes))
                    .replace("__MARKERS__", json.dumps(state["markers"]))
                    .replace("__NEXTNUM__", json.dumps(state["nextNumber"]))
                    .replace("__ZOOM__", json.dumps(ZOOM))
                    .replace("__DEFAULT_SIZE__", json.dumps(DEFAULT_SIZE))
                    .replace("__MIN_SIZE__", json.dumps(MIN_SIZE))
                    .replace("__MAX_SIZE__", json.dumps(MAX_SIZE))
                    .replace("__DEFAULT_COLOR__", json.dumps(DEFAULT_COLOR))
                    .replace("__PALETTE__", json.dumps(PALETTE))
                    .replace("__ARROW_LEN_RATIO__", json.dumps(ARROW_LEN_RATIO))
                    .replace("__MIN_ARROW_LEN__", json.dumps(MIN_ARROW_LEN))
                    .replace("__MAX_ARROW_LEN__", json.dumps(MAX_ARROW_LEN))
                    .replace("__HEAD_LEN_RATIO__", json.dumps(HEAD_LEN_RATIO))
                    .replace("__HEAD_HALF_RATIO__", json.dumps(HEAD_HALF_RATIO)))
            return self._send(200, html.encode("utf-8"))
        if u.path == "/page.png":
            n = int(parse_qs(u.query).get("n", ["0"])[0])
            doc = self._doc()
            pix = doc[n].get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
            png = pix.tobytes("png")
            doc.close()
            return self._send(200, png, "image/png")
        self._send(404, b"not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        if self.path == "/ping":
            _Handler.last_ping = time.time()
            return self._json({"ok": True})

        if self.path == "/quit":
            self._json({"ok": True})
            threading.Timer(0.3, self.httpd.shutdown).start()
            return

        if self.path == "/markers":
            data = json.loads(raw or b"{}")
            _save_state(self.pdf_path, {"markers": data.get("markers", []),
                                         "nextNumber": data.get("nextNumber", 1)})
            return self._json({"ok": True})

        if self.path == "/upload":
            fname = self.headers.get("X-Filename", "uploaded.pdf")
            from urllib.parse import unquote
            fname = Path(unquote(fname)).name or "uploaded.pdf"
            target = self.upload_dir / fname
            target.write_bytes(raw)
            _Handler.pdf_path = target
            _save_state(target, {"markers": [], "nextNumber": 1})
            return self._json({"ok": True})

        if self.path == "/export":
            data = json.loads(raw or b"{}")
            markers = data.get("markers", [])
            _save_state(self.pdf_path, {"markers": markers,
                                         "nextNumber": data.get("nextNumber", 1)})
            doc = self._doc()
            for m in markers:
                draw_marker(doc[int(m["page"])], m)
            # never silently overwrite a previous export -- each Export click
            # gets its own file, numbered up from _marked.pdf
            out = self.pdf_path.with_name(self.pdf_path.stem + "_marked.pdf")
            n = 2
            while out.exists():
                out = self.pdf_path.with_name(f"{self.pdf_path.stem}_marked_v{n}.pdf")
                n += 1
            for attempt in range(10):
                try:
                    doc.save(str(out))
                    break
                except Exception:
                    out = self.pdf_path.with_name(
                        f"{self.pdf_path.stem}_marked_v{n}.pdf")
                    n += 1
            doc.close()
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(out)])
            return self._json({"msg": f"Exported: {out.name}", "path": str(out)})

        self._send(404, b"not found")


def serve(pdf_path: str, port: int = 8766, open_browser: bool = True) -> None:
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(pdf_path)
    _Handler.pdf_path = path
    _Handler.upload_dir = path.parent
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), _Handler)
            port = p
            break
        except OSError:
            continue
    else:
        raise RuntimeError("no free port found")
    _Handler.httpd = httpd
    # generous initial grace period: the exe/browser can take a few seconds
    # to actually load the page and start pinging
    _Handler.last_ping = time.time() + 20

    def _watch():
        while True:
            time.sleep(2)
            if time.time() - _Handler.last_ping > HEARTBEAT_TIMEOUT:
                httpd.shutdown()
                return

    threading.Thread(target=_watch, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    try:
        print(f"PinStamp: {url}  (editing {path.name}, Ctrl+C to quit)")
    except Exception:
        pass  # no console when frozen as a --windowed exe
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    httpd.serve_forever()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", help="PDF to mark up")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    serve(args.pdf, port=args.port, open_browser=not args.no_browser)
