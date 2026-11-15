"""Мост к Captions Studio (D:\\Captions my) без правки её кода.

Её пакет `backend` загружается под именем `cs_backend` (у Монтажной свой пакет `backend`), поэтому её относительные
импорты (`.config`, `.jobs`) работают как есть. Отсюда берём: задачи с прогрессом (jobs), ffprobe и экспорт с вшитыми
.ass-субтитрами и эмодзи (render), список шрифтов (fonts), пресеты, словарь и слова-паразиты (settings.json).
Распознавание речи — её worker в её же .venv (см. transcribe.py).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

from .config import CAPTIONS_DIR


def _load_pkg():
    if "cs_backend" in sys.modules:
        return sys.modules["cs_backend"]
    init = CAPTIONS_DIR / "backend" / "__init__.py"
    spec = importlib.util.spec_from_file_location("cs_backend", init, submodule_search_locations=[str(init.parent)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cs_backend"] = mod
    spec.loader.exec_module(mod)
    return mod


_load_pkg()
cs_config = importlib.import_module("cs_backend.config")
cs_jobs = importlib.import_module("cs_backend.jobs")
cs_render = importlib.import_module("cs_backend.render")
cs_fonts = importlib.import_module("cs_backend.fonts")

Job, JOBS, start_job = cs_jobs.Job, cs_jobs.JOBS, cs_jobs.start_job
probe = cs_render.probe
QUALITY = cs_render.QUALITY
FONTS_DIR, EMOJI_DIR = cs_config.FONTS_DIR, cs_config.EMOJI_DIR
PRESETS_DIR, USER_PRESETS_DIR = cs_config.PRESETS_DIR, cs_config.USER_PRESETS_DIR

# Слова-паразиты по умолчанию (копия DEFAULT_FILLERS из frontend/editor.js Captions Studio)
CS_DEFAULT_FILLERS = ['э', 'ээ', 'эээ', 'э-э', 'эм', 'эмм', 'м', 'мм', 'ммм', 'хм', 'ну', 'типа', 'короче', 'как бы',
                      'это самое', 'е', 'ее', 'еее', 'типу', 'ніби', 'uh', 'um', 'uhm', 'umm', 'erm', 'hmm']


def settings() -> dict:
    p = CAPTIONS_DIR / "settings.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fillers() -> list[str]:
    t = settings().get("fillers")
    if t and t.strip():
        return [x.strip().lower() for x in t.split("\n") if x.strip()]
    return list(CS_DEFAULT_FILLERS)


def dictionary() -> list[tuple[str, str]]:
    """Словарь автозамен «чат джипити = ChatGPT»."""
    raw = settings().get("dictionary") or ""
    if isinstance(raw, list):
        raw = "\n".join(raw)
    out = []
    for line in str(raw).split("\n"):
        if "=" in line:
            a, b = line.split("=", 1)
            if a.strip():
                out.append((a.strip(), b.strip()))
    return out


def presets() -> list[dict]:
    out = []
    for folder, builtin in ((PRESETS_DIR, True), (USER_PRESETS_DIR, False)):
        for p in sorted(Path(folder).glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"id": p.stem, "name": d.get("name", p.stem), "builtin": builtin,
                            "order": d.get("order", 99), "style": d.get("style", {})})
            except (OSError, ValueError):
                pass
    return sorted(out, key=lambda x: (not x["builtin"], x["order"], x["name"]))


def save_user_preset(pid: str, name: str, style: dict) -> str:
    p = Path(USER_PRESETS_DIR) / f"{pid}.json"
    p.write_text(json.dumps({"name": name, "order": 50, "style": style}, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)
