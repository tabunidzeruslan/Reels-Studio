"""Генерация голоса через ElevenLabs (по желанию; без ключа всё остальное работает как раньше).

Ключ хранится только локально: studio\\settings.json (в .gitignore) или переменная ELEVENLABS_API_KEY, или
~/.config/reels-montage/keys.env от кита. Ключ никогда не отдаётся во фронтенд и не пишется в логи.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .config import load_settings, save_settings

API = "https://api.elevenlabs.io/v1"
_voices_cache: dict = {}


def key() -> str | None:
    k = load_settings().get("elevenlabs_key") or os.environ.get("ELEVENLABS_API_KEY")
    if k:
        return k
    f = Path.home() / ".config" / "reels-montage" / "keys.env"
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ELEVENLABS_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"\'')
                if v:
                    return v
    except OSError:
        pass
    return None


def set_key(k: str) -> None:
    s = load_settings()
    if k.strip():
        s["elevenlabs_key"] = k.strip()
    else:
        s.pop("elevenlabs_key", None)
    save_settings(s)
    _voices_cache.clear()


def _req(path: str, body: dict | None = None, timeout: int = 120) -> bytes:
    k = key()
    if not k:
        raise RuntimeError("Нет ключа ElevenLabs: вставьте его в разделе «Голос»")
    req = urllib.request.Request(API + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"xi-api-key": k, "Content-Type": "application/json", "Accept": "*/*"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = e.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"ElevenLabs: HTTP {e.code} {msg}")


def status() -> dict:
    return {"has_key": bool(key())}


def voices() -> list[dict]:
    if "list" in _voices_cache and time.time() - _voices_cache["t"] < 600:
        return _voices_cache["list"]
    d = json.loads(_req("/voices"))
    out = [{"id": v["voice_id"], "name": v.get("name", ""), "category": v.get("category", ""),
            "labels": v.get("labels", {}), "preview": v.get("preview_url")} for v in d.get("voices", [])]
    _voices_cache.update(list=out, t=time.time())
    return out


def tts(text: str, voice_id: str, out_dir: Path, model: str = "eleven_multilingual_v2", job=None) -> Path:
    if job: job.update(0.1, "ElevenLabs: озвучиваю текст…")
    audio = _req(f"/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                 {"text": text, "model_id": model, "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.2}},
                 timeout=180)
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"vo_{uuid.uuid4().hex[:8]}.mp3"
    f.write_bytes(audio)
    if job: job.update(0.95, "Готово")
    return f
