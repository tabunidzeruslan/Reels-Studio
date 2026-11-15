"""«Мои правила»: styles\\my_rules.md — текст для человека + блок параметров, который читает код.

Каждое замечание («паузы длиннее», «субтитры крупнее», «не режь "смотрите"») дописывается строкой в журнал и, если
его удалось понять, меняет параметр. Параметры применяются ко всем следующим роликам.
"""
from __future__ import annotations

import json
import re
import time

from .config import STYLES

FILE = STYLES / "my_rules.md"

DEFAULTS = {
    "pause_min": 0.35,          # паузы длиннее — вырезать
    "keep_pause": 0.06,         # запас у края слова при склейке, с (40–80 мс)
    "crossfade_ms": 30,         # аудио-кроссфейд на склейке
    "keep_words": [],           # никогда не резать эти слова
    "extra_fillers": ["ну", "типа", "короче", "как бы", "вот", "значит", "э-э", "м-м"],
    "caption_preset": "01_hormozi",
    "caption_font_scale": 1.0,  # множитель размера субтитров
    "caption_position": "",     # '' = как в пресете; top|center|bottom
    "punch_in": 1.15,           # punch-in на смене мысли
    "punch_every": 1,           # каждый n-й склейка — punch-in
    "music_volume": 0.18,
    "music": "lofi_keys_84.mp3",
    "sfx": True,
    "hook": True,               # ставить сильную фразу в начало
    "graphics": True,           # предлагать графику на словах
    "lufs": -14,
}

TEMPLATE = """# Мои правила монтажа

Всё, что я поправляю, записывается сюда и применяется ко всем следующим роликам.
Текст можно править свободно. Параметры для программы — в блоке json ниже.

## Журнал правок

## Параметры

```json
{params}
```
"""


def _read() -> str:
    if not FILE.exists():
        FILE.write_text(TEMPLATE.format(params=json.dumps(DEFAULTS, ensure_ascii=False, indent=1)), encoding="utf-8")
    return FILE.read_text(encoding="utf-8")


def text() -> str:
    return _read()


def save_text(t: str) -> dict:
    params(t)  # проверка: json должен читаться
    FILE.write_text(t, encoding="utf-8")
    return params()


def params(t: str | None = None) -> dict:
    t = t if t is not None else _read()
    m = re.search(r"```json\s*(\{.*?\})\s*```", t, re.S)
    p = dict(DEFAULTS)
    if m:
        try:
            p.update(json.loads(m.group(1)))
        except ValueError as e:
            raise ValueError(f"Блок параметров не читается: {e}")
    return p


def _write_params(t: str, p: dict) -> str:
    block = "```json\n" + json.dumps(p, ensure_ascii=False, indent=1) + "\n```"
    if re.search(r"```json\s*\{.*?\}\s*```", t, re.S):
        return re.sub(r"```json\s*\{.*?\}\s*```", lambda _: block, t, count=1, flags=re.S)
    return t.rstrip() + "\n\n## Параметры\n\n" + block + "\n"


def add(note: str) -> dict:
    """Добавить правило словами. Возвращает {understood: [...], params}."""
    t = _read()
    p = params(t)
    low = note.lower()
    did = []
    quoted = re.findall(r"[«\"“']([^»\"”']+)[»\"”']", note)
    if re.search(r"не (режь|вырезай|удаляй|трогай)", low) and quoted:
        for q in quoted:
            if q.lower() not in [x.lower() for x in p["keep_words"]]:
                p["keep_words"].append(q.lower())
            p["extra_fillers"] = [f for f in p["extra_fillers"] if f.lower() != q.lower()]
        did.append(f"не резать: {', '.join(quoted)}")
    elif re.search(r"(режь|вырезай|удаляй|убирай)", low) and quoted:
        p["extra_fillers"] += [q.lower() for q in quoted if q.lower() not in p["extra_fillers"]]
        did.append(f"резать как паразит: {', '.join(quoted)}")
    if "пауз" in low:
        if re.search(r"длинн|больше|оставляй", low):
            p["pause_min"] = round(p["pause_min"] + 0.1, 2); p["keep_pause"] = min(0.08, p["keep_pause"] + 0.01)
            did.append(f"паузы режем от {p['pause_min']} с")
        elif re.search(r"короч|меньше|плотн|быстр", low):
            p["pause_min"] = round(max(0.2, p["pause_min"] - 0.05), 2); did.append(f"паузы режем от {p['pause_min']} с")
    if "субтитр" in low or "подпис" in low:
        if re.search(r"крупн|больш", low):
            p["caption_font_scale"] = round(p["caption_font_scale"] * 1.12, 2); did.append(f"субтитры ×{p['caption_font_scale']}")
        elif re.search(r"мельч|меньш", low):
            p["caption_font_scale"] = round(p["caption_font_scale"] / 1.12, 2); did.append(f"субтитры ×{p['caption_font_scale']}")
        for word, pos in (("вверх", "top"), ("центр", "center"), ("посередин", "center"), ("вниз", "bottom")):
            if word in low:
                p["caption_position"] = pos; did.append(f"субтитры: {pos}")
    if "музык" in low:
        if re.search(r"тише|меньше", low): p["music_volume"] = round(p["music_volume"] * 0.75, 3); did.append(f"музыка {p['music_volume']}")
        elif re.search(r"громч|больше", low): p["music_volume"] = round(p["music_volume"] * 1.3, 3); did.append(f"музыка {p['music_volume']}")
        elif re.search(r"без|убер|не надо", low): p["music"] = ""; did.append("без музыки")
    if re.search(r"зум|punch|приближ|наезд", low):
        if re.search(r"меньше|реже|слабее|без", low): p["punch_in"] = round(max(1.0, p["punch_in"] - 0.05), 2)
        else: p["punch_in"] = round(min(1.3, p["punch_in"] + 0.05), 2)
        did.append(f"punch-in ×{p['punch_in']}")
    if re.search(r"звук|sfx|вжух", low) and re.search(r"без|убер|не надо|меньше", low):
        p["sfx"] = False; did.append("без звуков")
    if "хук" in low and re.search(r"без|не став|не надо", low):
        p["hook"] = False; did.append("без хука")
    stamp = time.strftime("%Y-%m-%d")
    line = f"- {stamp}: {note.strip()}" + (f"  → {'; '.join(did)}" if did else "  → (понять автоматически не удалось, учтёт Claude)")
    t = re.sub(r"(## Журнал правок\n)", lambda m: m.group(1) + line + "\n", t, count=1) if "## Журнал правок" in t else t + "\n" + line + "\n"
    t = _write_params(t, p)
    FILE.write_text(t, encoding="utf-8")
    return {"understood": did, "params": p}
