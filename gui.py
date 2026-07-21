"""PinStamp — standalone launcher (tkinter, packaged as PinStamp.exe).
Double-click -> native "Open PDF" dialog -> PinStamp opens in the browser,
ready to click-and-stamp immediately.
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

if getattr(sys, "frozen", False):  # PyInstaller bundle
    sys.path.insert(0, str(Path(sys._MEIPASS)))
else:
    sys.path.insert(0, str(Path(__file__).parent))

CONFIG = Path(os.environ.get("APPDATA", ".")) / "PinStamp" / "gui.json"


def _free_port(start=8766):
    import socket

    for port in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def _last_dir() -> str:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("last_dir", "")
    except Exception:
        return ""


def _save_last_dir(p: Path) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"last_dir": str(p.parent)}), encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    path = filedialog.askopenfilename(
        title="Open a PDF to mark up",
        initialdir=_last_dir() or str(Path.home()),
        filetypes=[("PDF", "*.pdf")],
    )
    if not path:
        return
    pdf_path = Path(path)
    _save_last_dir(pdf_path)

    from pinstamp.core import serve

    try:
        serve(str(pdf_path), port=_free_port(), open_browser=True)
    except Exception as e:
        messagebox.showerror("PinStamp", f"Failed to start: {e}")


if __name__ == "__main__":
    main()
