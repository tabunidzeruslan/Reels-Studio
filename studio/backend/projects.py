"""Проекты роликов: work\\<id>\\project.json + все промежуточные файлы рядом."""
from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path

from .config import WORK
from .ff import jdump, jload

STAGES = ["sources", "prepare", "transcribe", "cleanup", "montage", "preview", "final"]
STAGE_NAMES = {"sources": "Исходники", "prepare": "Подготовка", "transcribe": "Распознавание", "cleanup": "Чистка",
               "montage": "Монтаж", "preview": "Превью", "final": "Финал"}


def pdir(pid: str) -> Path:
    if not re.fullmatch(r"[\w-]+", pid):
        raise ValueError("bad id")
    return WORK / pid


def new(title: str) -> dict:
    pid = time.strftime("%Y%m%d") + "_" + uuid.uuid4().hex[:6]
    d = pdir(pid)
    d.mkdir(parents=True)
    p = {"id": pid, "title": title or "Новый ролик", "created": time.time(), "updated": time.time(),
         "sources": [], "lang": "ru", "style": "dynamic", "caption_preset": "01_hormozi", "caption_style": {},
         "stages": {s: "todo" for s in STAGES}, "edits": [], "hook": None, "motion": [], "punch": [],
         "music": {"file": "lofi_keys_84.mp3", "volume": 0.18, "enabled": True}, "sfx": True,
         "phrases_override": None, "renders": []}
    save(p)
    return p


def load(pid: str) -> dict:
    p = jload(pdir(pid) / "project.json")
    if p is None:
        raise FileNotFoundError("Проект не найден")
    return p


def save(p: dict) -> dict:
    p["updated"] = time.time()
    jdump(p, pdir(p["id"]) / "project.json")
    return p


def set_stage(p: dict, stage: str, status: str, reset_after: bool = False) -> None:
    p["stages"][stage] = status
    if reset_after:
        for s in STAGES[STAGES.index(stage) + 1:]:
            if p["stages"].get(s) == "done":
                p["stages"][s] = "stale"


def list_all() -> list[dict]:
    out = []
    for f in WORK.glob("*/project.json"):
        p = jload(f)
        if p:
            out.append({k: p.get(k) for k in ("id", "title", "created", "updated", "stages", "renders")})
    return sorted(out, key=lambda x: -x["updated"])


def delete(pid: str) -> None:
    shutil.rmtree(pdir(pid), ignore_errors=True)
