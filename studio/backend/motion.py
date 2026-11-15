"""Моушн-слой: библиотека клипов Моушн-студии (D:\\Моушн-графика\\output), её статус и запуск, свои карточки (Pillow).

Код Моушн-студии не меняем: читаем её output\\ и обращаемся к её HTTP API на :3000. Новые анимации делаются в ней
(шаблоны с вашими текстами и брендом, рендер на прозрачном фоне или хромакее, генерация через Claude CLI) — готовый
файл сразу появляется здесь в библиотеке.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

from . import cs
from .compose import overlay_mode
from .config import MOTION_DIR, MOTION_URL
from .ff import NO_WINDOW

EXT = {".mp4", ".mov", ".webm"}


_cache: dict[str, dict] = {}


def library() -> list[dict]:
    out = []
    d = MOTION_DIR / "output"
    if d.is_dir():
        for f in sorted(d.iterdir(), key=lambda x: -x.stat().st_mtime):
            if f.suffix.lower() in EXT:
                st = f.stat()
                key = f"{f}|{st.st_mtime}|{st.st_size}"
                if key not in _cache:
                    item = {"file": str(f), "name": f.name, "mode": overlay_mode(str(f)), "size": st.st_size}
                    try:
                        i = cs.probe(str(f)); item.update(duration=round(i["duration"], 2), width=i["width"], height=i["height"])
                    except Exception:
                        pass
                    _cache[key] = item
                out.append(_cache[key])
    return out


def status() -> dict:
    try:
        with urllib.request.urlopen(MOTION_URL + "/api/settings", timeout=1.5) as r:
            json.loads(r.read() or b"{}")
        return {"running": True, "url": MOTION_URL}
    except Exception:
        return {"running": False, "url": MOTION_URL}


def start() -> dict:
    """Запуск Моушн-студии её собственной командой (npm start) в отдельном окне."""
    if status()["running"]:
        return status()
    subprocess.Popen(["cmd", "/c", "start", "Моушн-студия", "cmd", "/k", "npm start"], cwd=str(MOTION_DIR),
                     creationflags=NO_WINDOW)
    return {"running": False, "starting": True, "url": MOTION_URL}
