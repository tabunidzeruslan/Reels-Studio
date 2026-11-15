"""Пути и общие настройки Монтажной."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent          # D:\Монтаж
STUDIO = ROOT / "studio"
FRONTEND = STUDIO / "frontend"
WORK = ROOT / "work"                                           # всё временное, по проектам
OUTPUT = ROOT / "output"                                       # готовые ролики
STYLES = ROOT / "styles"                                       # styles\<имя>.json, my_rules.md
SETTINGS_FILE = STUDIO / "settings.json"

CAPTIONS_DIR = Path(os.environ.get("CAPTIONS_DIR", r"D:\Captions my"))
MOTION_DIR = Path(os.environ.get("MOTION_DIR", r"D:\Моушн-графика"))
MOTION_URL = os.environ.get("MOTION_URL", "http://127.0.0.1:3000")
KIT_DIR = Path(os.environ.get("REELS_KIT", str(Path.home() / ".claude" / "skills" / "reels-montage")))
KIT_MUSIC = KIT_DIR / "assets" / "music"
KIT_SFX = KIT_DIR / "assets" / "sfx"

HOST, PORT = "127.0.0.1", 8790
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts"}

for d in (WORK, OUTPUT, STYLES):
    d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"allowed_dirs": []}


def save_settings(s: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
