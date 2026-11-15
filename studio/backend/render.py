"""Рендер: очередь задач. Превью 720p → правки → финал 1080×1920 H.264/AAC.

Шаг 1 — compose.build (монтаж без субтитров). Шаг 2 — экспорт Captions Studio (её render.export): вшивает .ass
из engine.js и эмодзи PNG по её пресету «Черновик» (превью) или «Instagram / TikTok / Facebook» (финал).
"""
from __future__ import annotations

import re
import shutil
import threading
import time
from pathlib import Path

from . import compose, cs, projects, rules
from .config import OUTPUT
from .ff import jload

_queue_lock = threading.Lock()   # рендерим по одному: видеокарта и диск не делятся


def effective_params(p: dict) -> dict:
    from . import analyze_style
    P = dict(rules.DEFAULTS)
    P.update(analyze_style.get(p.get("style", "dynamic")).get("params", {}))
    user = rules.params()
    P.update({k: v for k, v in user.items() if v != rules.DEFAULTS.get(k)})   # мои правила важнее стиля
    return P


def out_name(title: str) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or "reel"
    return cs.cs_render.unique_path(OUTPUT / f"{time.strftime('%Y-%m-%d')}_{safe}.mp4")


def start(pid: str, kind: str, ass_text: str, emojis: list[dict]):
    def work(job):
        with _queue_lock:
            p = projects.load(pid)
            pd = projects.pdir(pid)
            clean_words = (jload(pd / "clean_words.json") or {}).get("words", [])
            P = effective_params(p)
            final = kind == "final"
            base, _ = compose.build(p, pd, clean_words, P, final, job)
            D = compose.dur_of(str(base))
            dst = out_name(p["title"]) if final else pd / "preview.mp4"
            sub = _Sub(job, 0.6, 1.0)
            wd = pd / "export"; wd.mkdir(exist_ok=True)
            cs.cs_render.export(sub, str(base), wd, ass_text, Path(dst), D, emojis, "social" if final else "draft")
            p = projects.load(pid)
            projects.set_stage(p, "final" if final else "preview", "done")
            p["renders"].append({"kind": kind, "file": str(dst), "time": time.time(), "duration": round(D, 2)})
            projects.save(p)
            return {"file": str(dst), "duration": D}
    return cs.start_job("render_" + kind, work)


class _Sub:
    """Обёртка задачи: экспорт Captions Studio двигает прогресс 0..1 — переводим в диапазон p0..p1."""
    def __init__(self, job, p0, p1):
        self.j, self.p0, self.p1 = job, p0, p1
        self.cancel_flag = job.cancel_flag

    def update(self, progress=None, message=None):
        self.j.update(None if progress is None else self.p0 + (self.p1 - self.p0) * progress, message)
