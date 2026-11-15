"""Распознавание речи: faster-whisper из Captions Studio, локально и бесплатно.

Запускаем её `backend.transcribe_worker` отдельным процессом в её .venv (модель large-v3-turbo уже в её models\\),
сначала на видеокарте, при сбое — на процессоре. Её код не меняем. Затем применяем её словарь автозамен.
Слова: [{text, start, end, prob}] — тот же формат, что понимает engine.js.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

from . import cs
from .config import CAPTIONS_DIR
from .ff import NO_WINDOW, run


def _py() -> str:
    p = CAPTIONS_DIR / ".venv" / "Scripts" / "python.exe"
    if not p.exists():
        raise RuntimeError(f"Нет окружения Captions Studio: {p}")
    return str(p)


def transcribe(media: str, lang: str | None = "ru", model: str = "large-v3-turbo", job=None) -> dict:
    lang = None if (not lang or lang == "auto") else lang
    tmp = tempfile.mkdtemp(prefix="mt_whisper_")
    wav, out, jf = (os.path.join(tmp, n) for n in ("a.wav", "out.json", "job.json"))
    run(["ffmpeg", "-y", "-v", "error", "-i", media, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    last = ""
    for dev in (os.environ.get("WHISPER_DEVICE") and [os.environ["WHISPER_DEVICE"]]) or ["cuda", "cpu"]:
        with open(jf, "w", encoding="utf-8") as f:
            json.dump({"audio": wav, "language": lang, "model": model, "device": dev, "out": out}, f)
        proc = subprocess.Popen([_py(), "-m", "backend.transcribe_worker", jf], cwd=str(CAPTIONS_DIR),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", creationflags=NO_WINDOW)
        for line in proc.stdout:
            try:
                m = json.loads(line)
                if job is not None:
                    job.update(m.get("progress"), f"{m.get('message', '')} ({'видеокарта' if dev == 'cuda' else 'процессор'})")
            except ValueError:
                pass
        err = proc.stderr.read()
        proc.wait()
        if proc.returncode == 0 and os.path.exists(out):
            break
        last = err[-600:]
    else:
        raise RuntimeError("Распознавание не удалось: " + last)
    with open(out, encoding="utf-8") as f:
        r = json.load(f)
    r["words"] = apply_dictionary(r["words"])
    return r


def apply_dictionary(words: list[dict]) -> list[dict]:
    """Словарь автозамен Captions Studio: «чат джипити = ChatGPT» (фразы из нескольких слов склеиваются)."""
    rules = cs.dictionary()
    if not rules:
        return words
    norm = lambda s: re.sub(r"[^\w]", "", s.lower())
    out, i = [], 0
    while i < len(words):
        done = False
        for src, dst in rules:
            parts = [norm(x) for x in src.split()]
            n = len(parts)
            if n and [norm(w["text"]) for w in words[i:i + n]] == parts:
                tail = re.search(r"[.,!?;:…]+$", words[i + n - 1]["text"])
                w = dict(words[i], text=dst + (tail.group(0) if tail else ""), end=words[i + n - 1]["end"])
                out.append(w); i += n; done = True
                break
        if not done:
            out.append(words[i]); i += 1
    return out
