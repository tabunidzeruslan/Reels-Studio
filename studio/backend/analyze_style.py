"""Референсы и стили: разбор чужих роликов локально, без OpenAI.

Склейки и длина плана — PySceneDetect; темп речи и паузы — whisper из Captions Studio; громкость голоса, музыки и
SFX — ffmpeg ebur128 и RMS в паузах между словами; кадры каждые 1.5 с и общий лист кадров — для просмотра глазами
(субтитры, зумы, плашки, хук, CTA заполняются в карточке стиля: их смотрит Claude или вы). Итог — styles\\<имя>.json.
Схема полей — по мотивам style-profiles.md из reels-montage-kit.
"""
from __future__ import annotations

import math
import re
import statistics
import wave
from pathlib import Path

import numpy as np

from . import cs, transcribe
from .config import STYLES, WORK
from .ff import jdump, jload, loudness, run

REFS = WORK / "_refs"

BUILTIN = {
    "dynamic": {
        "name": "dynamic", "title": "Динамичный (по умолчанию)",
        "summary": "Быстрый говорящий ролик: плотные склейки без пауз, punch-in на каждой смене мысли, крупные "
                   "субтитры по 1–3 слова с подсветкой, графика на числах и названиях, тихая музыка, CTA в конце.",
        "params": {"pause_min": 0.3, "punch_in": 1.15, "punch_every": 1, "caption_preset": "01_hormozi", "music_volume": 0.16},
        "visual": {"captions": "белые капс, активное слово жёлтое, обводка", "zoom": "punch-in 1.15× через склейку",
                   "plates": "карточки с числами вверху кадра", "hook": "самая сильная фраза в первые 2 с",
                   "cta": "кнопка-плашка в последние 3 с"},
    }
}


def slug(s: str) -> str:
    s = re.sub(r"[^\w-]+", "_", s.strip().lower()).strip("_")
    return s or "style"


def list_styles() -> list[dict]:
    out = [dict(v, builtin=True) for v in BUILTIN.values()]
    for f in sorted(STYLES.glob("*.json")):
        d = jload(f)
        if d:
            out.append(dict(d, builtin=False))
    return out


def get(name: str) -> dict:
    if name in BUILTIN:
        return BUILTIN[name]
    d = jload(STYLES / f"{name}.json")
    return d or BUILTIN["dynamic"]


def save(style: dict) -> dict:
    style["name"] = slug(style.get("name") or style.get("title", "style"))
    jdump(style, STYLES / f"{style['name']}.json")
    return style


# ---------------------------------------------------------------- измерения
def scenes(path: str) -> list[float]:
    import os
    import shutil
    import tempfile
    from scenedetect import ContentDetector, detect
    src, tmp = path, None
    if not path.isascii():   # OpenCV на Windows не открывает пути с кириллицей — работаем с временной копией
        tmp = os.path.join(tempfile.gettempdir(), "mt_scene" + Path(path).suffix)
        shutil.copy(path, tmp); src = tmp
    try:
        sc = detect(src, ContentDetector(threshold=27.0, min_scene_len=6), show_progress=False)
    finally:
        if tmp: os.remove(tmp)
    return [round(s[0].get_seconds(), 3) for s in sc[1:]]   # начало 2-го и следующих планов = склейки


def _rms_db(wav: str, t0: float, t1: float, a: np.ndarray, sr: int) -> float:
    seg = a[int(t0 * sr):int(t1 * sr)]
    if len(seg) < sr * 0.05:
        return -90.0
    r = float(np.sqrt(np.mean(seg ** 2)) + 1e-9)
    return 20 * math.log10(r)


def frames(path: str, out: Path, every: float = 1.5) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("f_*.jpg"):
        f.unlink()
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vf", f"fps=1/{every},scale=360:-2", "-q:v", "4", str(out / "f_%03d.jpg")])
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vf", f"fps=1/{every},scale=216:-2,tile=8x4:padding=4", "-frames:v", "1",
         "-q:v", "4", str(out / "sheet.jpg")])
    return sorted(str(f) for f in out.glob("f_*.jpg"))


def analyze_one(path: str, lang: str = "ru", job=None, p0=0.0, p1=1.0) -> dict:
    name = Path(path).stem
    wd = REFS / slug(name)
    wd.mkdir(parents=True, exist_ok=True)
    info = cs.probe(path)
    D = info["duration"]
    if job: job.update(p0, f"{name}: склейки")
    cuts = scenes(path)
    shots = [b - a for a, b in zip([0.0] + cuts, cuts + [D])] if cuts else [D]
    if job: job.update(p0 + (p1 - p0) * 0.25, f"{name}: речь")
    tr = jload(wd / "words.json")
    if not tr:
        tr = transcribe.transcribe(path, lang)
        jdump(tr, wd / "words.json")
    W = tr["words"]
    gaps = [b["start"] - a["end"] for a, b in zip(W, W[1:])]
    speech_t = sum(w["end"] - w["start"] for w in W)
    if job: job.update(p0 + (p1 - p0) * 0.7, f"{name}: громкость")
    wav = str(wd / "a.wav")
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav])
    with wave.open(wav) as w:
        sr = w.getframerate(); a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    voice_db = statistics.median([_rms_db(wav, x["start"], x["end"], a, sr) for x in W]) if W else -90
    bed = [_rms_db(wav, x["end"] + 0.05, y["start"] - 0.05, a, sr) for x, y in zip(W, W[1:]) if y["start"] - x["end"] > 0.25]
    bed_db = statistics.median(bed) if bed else None
    # SFX: резкие пики громкости (> +9 дБ к соседям) вне слов
    env = np.array([np.sqrt(np.mean(a[i:i + sr // 20] ** 2)) + 1e-9 for i in range(0, len(a), sr // 20)])
    envdb = 20 * np.log10(env)
    peaks = 0
    for i in range(3, len(envdb) - 3):
        t = i / 20
        if envdb[i] > np.median(envdb[i - 3:i + 4]) + 9 and not any(x["start"] <= t <= x["end"] for x in W):
            peaks += 1
    if job: job.update(p0 + (p1 - p0) * 0.85, f"{name}: кадры")
    fr = frames(path, wd / "frames")
    return {
        "file": path, "name": name, "duration": round(D, 2), "size": f"{info['width']}×{info['height']}", "fps": info["fps"],
        "cuts": len(cuts), "avg_shot": round(statistics.mean(shots), 2), "median_shot": round(statistics.median(shots), 2),
        "cuts_per_10s": round(len(cuts) / D * 10, 2) if D else 0,
        "words": len(W), "wpm": round(len(W) / (speech_t + sum(g for g in gaps if g < 1.5)) * 60, 1) if W else 0,
        "pause_avg": round(statistics.mean(gaps), 3) if gaps else 0,
        "pause_p90": round(sorted(gaps)[int(len(gaps) * 0.9)], 3) if gaps else 0,
        "long_pauses": sum(1 for g in gaps if g > 0.35),
        "first_words": " ".join(w["text"] for w in W[:14]), "last_words": " ".join(w["text"] for w in W[-14:]),
        "loudness": loudness(path), "voice_db": round(voice_db, 1),
        "music_bed_db": round(bed_db, 1) if bed_db is not None else None,
        "music_under_voice_db": round(voice_db - bed_db, 1) if bed_db is not None else None,
        "sfx_hits": peaks, "frames_dir": str(wd / "frames"), "sheet": str(wd / "frames" / "sheet.jpg"), "frames": fr,
    }


def analyze(paths: list[str], title: str, lang: str = "ru", job=None) -> dict:
    refs = []
    for i, p in enumerate(paths):
        refs.append(analyze_one(p, lang, job, i / len(paths), (i + 1) / len(paths)))
    m = lambda k: round(statistics.mean(r[k] for r in refs if r.get(k) is not None), 2) if refs else 0
    avg_shot = m("avg_shot")
    pause_p90 = m("pause_p90")
    mu = [r["music_under_voice_db"] for r in refs if r.get("music_under_voice_db") is not None]
    style = {
        "name": slug(title), "title": title, "refs": refs,
        "metrics": {"avg_shot": avg_shot, "cuts_per_10s": m("cuts_per_10s"), "wpm": m("wpm"), "pause_avg": m("pause_avg"),
                    "pause_p90": pause_p90, "lufs": m("voice_db") and round(statistics.mean(r["loudness"].get("I", -14) for r in refs), 1),
                    "music_under_voice_db": round(statistics.mean(mu), 1) if mu else None, "sfx_per_10s":
                        round(statistics.mean(r["sfx_hits"] / max(r["duration"], 1) * 10 for r in refs), 2)},
        "params": {
            # склейка каждые avg_shot с → punch-in через склейку, если планы короткие
            "pause_min": round(min(0.5, max(0.2, pause_p90 * 0.8)), 2) if pause_p90 else 0.35,
            "punch_in": 1.18 if avg_shot and avg_shot < 2.5 else 1.12,
            "punch_every": 1 if avg_shot and avg_shot < 3 else 2,
            "music_volume": round(min(0.35, max(0.06, 10 ** (-(statistics.mean(mu) if mu else 22) / 20) * 1.6)), 3),
            "caption_preset": "01_hormozi",
        },
        "visual": {"captions": "", "zoom": "", "plates": "", "hook": "", "cta": ""},
        "summary": "",
    }
    return save(style)
