"""Исходники: разрешённые папки, список видео с превью. Исходники только читаются."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import cs
from .config import VIDEO_EXT, WORK, load_settings, save_settings
from .ff import run

THUMBS = WORK / "_thumbs"
THUMBS.mkdir(parents=True, exist_ok=True)


def norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def allowed_dirs() -> list[str]:
    return load_settings().get("allowed_dirs", [])


def is_allowed(path: str) -> bool:
    p = norm(path)
    return any(p == norm(d) or p.startswith(norm(d) + os.sep) for d in allowed_dirs())


def allow(folder: str) -> list[str]:
    s = load_settings()
    if not os.path.isdir(folder):
        raise RuntimeError("Папка не найдена: " + folder)
    if not any(norm(folder) == norm(d) for d in s.get("allowed_dirs", [])):
        s.setdefault("allowed_dirs", []).append(os.path.abspath(folder))
        save_settings(s)
    return s["allowed_dirs"]


def thumb_key(path: str) -> str:
    st = os.stat(path)
    return hashlib.md5(f"{norm(path)}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]


def scan(folder: str) -> list[dict]:
    if not is_allowed(folder):
        raise PermissionError("Папка не разрешена: сначала подтвердите доступ")
    out = []
    for p in sorted(Path(folder).iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXT:
            item = {"path": str(p), "name": p.name, "size": p.stat().st_size, "key": thumb_key(str(p))}
            try:
                info = cs.probe(str(p))
                item.update(width=info["width"], height=info["height"], fps=info["fps"],
                            duration=round(info["duration"], 2), hdr=info["hdr"])
            except Exception as e:  # битый файл — показываем, но без данных
                item["error"] = str(e)
            out.append(item)
    return out


def thumbnail(path: str) -> Path:
    if not is_allowed(path):
        raise PermissionError("Файл вне разрешённых папок")
    t = THUMBS / f"{thumb_key(path)}.jpg"
    if not t.exists():
        try:
            d = cs.probe(path)["duration"]
        except Exception:
            d = 2
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.0, d / 3):.2f}", "-i", path, "-frames:v", "1",
             "-vf", "scale=360:-2", "-q:v", "4", str(t)])
    return t
