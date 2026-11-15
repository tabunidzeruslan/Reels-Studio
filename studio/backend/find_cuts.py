"""Чистка: поиск правок (паузы, паразиты, дубли, фальстарты) и сборка чистого видео по принятым правкам.

Логика по мотивам prep.py из reels-montage-kit: режем тишину по таймингам слов, оставляя запас у краёв слова
(40–80 мс), склейки звука сглаживаем коротким кроссфейдом, чтобы не было щелчков.
"""
from __future__ import annotations

import re
import uuid

from . import cs, rules
from .ff import run_progress

HESITATION = {"э", "ээ", "эээ", "э-э", "эм", "эмм", "м", "мм", "ммм", "м-м", "хм", "а-а", "ах", "uh", "um", "uhm", "erm", "hmm"}
CONTEXTUAL = {"ну", "вот", "значит", "так", "типа", "как бы", "это самое", "короче", "в общем", "собственно"}


def norm(s: str) -> str:
    return re.sub(r"[^\w-]", "", s.lower()).strip("-")


def _eid() -> str:
    return uuid.uuid4().hex[:8]


def find(words: list[dict], duration: float, P: dict | None = None) -> list[dict]:
    P = P or rules.params()
    keep = set(w.lower() for w in P["keep_words"])
    fillers = (set(cs.fillers()) | set(f.lower() for f in P["extra_fillers"]) | HESITATION) - keep
    edits: list[dict] = []
    W = words
    n = len(W)
    kp = P["keep_pause"]

    # --- паузы (в т.ч. тишина в начале и в конце)
    if n:
        if W[0]["start"] > P["pause_min"]:
            edits.append(dict(type="pause", start=0.0, end=round(W[0]["start"] - kp, 3), text=f"тишина {W[0]['start']:.2f} с"))
        for a, b in zip(W, W[1:]):
            gap = b["start"] - a["end"]
            if gap > P["pause_min"]:
                edits.append(dict(type="pause", start=round(a["end"] + kp, 3), end=round(b["start"] - kp, 3),
                                  text=f"пауза {gap:.2f} с", after=a["text"], before=b["text"]))
        if duration - W[-1]["end"] > P["pause_min"]:
            edits.append(dict(type="pause", start=round(W[-1]["end"] + kp, 3), end=round(duration, 3), text="тишина в конце"))

    def word_cut(i: int, j: int | None = None) -> tuple[float, float]:
        j = i if j is None else j
        s = W[i]["start"] - 0.02
        e = W[j]["end"] + 0.02
        if i > 0: s = max(s, W[i - 1]["end"] + 0.01)
        if j + 1 < n: e = min(e, W[j + 1]["start"] - 0.01)
        return round(s, 3), round(e, 3)

    # --- паразиты (одно- и двухсловные), по контексту
    i = 0
    while i < n:
        t1 = norm(W[i]["text"])
        t2 = (t1 + " " + norm(W[i + 1]["text"])) if i + 1 < n else ""
        hit, span = None, 1
        if t2 in fillers:
            hit, span = t2, 2
        elif t1 in fillers:
            hit = t1
        if hit and hit not in keep:
            j = i + span - 1
            gap_before = W[i]["start"] - W[i - 1]["end"] if i else 1.0
            gap_after = W[j + 1]["start"] - W[j]["end"] if j + 1 < n else 1.0
            sentence_start = i == 0 or re.search(r"[.!?…]$", W[i - 1]["text"]) is not None
            comma_after = re.search(r"[,…]$", W[j]["text"]) is not None
            if hit in HESITATION:
                ok, why = True, "звук-заминка"
            elif hit in CONTEXTUAL:
                ok = gap_before > 0.15 or gap_after > 0.15 or comma_after or (sentence_start and hit in {"ну", "вот", "так", "короче", "в общем", "значит"})
                why = "отдельно стоит, без смысла" if ok else ""
            else:
                ok, why = True, "из списка паразитов"
            if ok:
                s, e = word_cut(i, j)
                edits.append(dict(type="filler", start=s, end=e, text=" ".join(w["text"] for w in W[i:j + 1]), reason=why))
            i += span
            continue
        i += 1

    # --- фальстарты: «я я», оборванное слово («сде… сделали»)
    for i in range(n - 1):
        a, b = norm(W[i]["text"]), norm(W[i + 1]["text"])
        if not a or a in keep:
            continue
        if a == b and len(a) > 0 and W[i + 1]["start"] - W[i]["end"] < 0.8:
            s, e = word_cut(i)
            edits.append(dict(type="falsestart", start=s, end=e, text=W[i]["text"] + " " + W[i + 1]["text"], reason="повтор слова"))
        elif 1 < len(a) <= 5 and len(b) > len(a) and b.startswith(a) and (W[i].get("prob", 1) < 0.7 or W[i]["text"].endswith(("-", "…"))):
            s, e = word_cut(i)
            edits.append(dict(type="falsestart", start=s, end=e, text=W[i]["text"] + " → " + W[i + 1]["text"], reason="оборванное слово"))

    # --- дубли: фраза начата заново (оставляем лучшую — обычно последнюю, или с большей уверенностью)
    phrases, cur = [], []
    for k, w in enumerate(W):
        if cur and (w["start"] - W[k - 1]["end"] > 0.45 or re.search(r"[.!?…]$", W[k - 1]["text"])):
            phrases.append(cur); cur = []
        cur.append(k)
    if cur: phrases.append(cur)
    taken = set()
    for pi, A in enumerate(phrases):
        a_words = [norm(W[k]["text"]) for k in A]
        if len(a_words) < 2 or pi in taken:
            continue
        for qi in (pi + 1, pi + 2):
            if qi >= len(phrases):
                break
            B = phrases[qi]
            b_words = [norm(W[k]["text"]) for k in B]
            m = min(3, len(a_words), len(b_words))
            prefix_same = m >= 2 and a_words[:m] == b_words[:m]
            a_is_part = len(a_words) <= len(b_words) and b_words[:len(a_words)] == a_words
            if prefix_same or a_is_part:
                pa = sum(W[k].get("prob", 1) for k in A) / len(A)
                pb = sum(W[k].get("prob", 1) for k in B) / len(B)
                drop, keepx = (A, B) if (pb >= pa - 0.05 or len(B) >= len(A)) else (B, A)
                s, e = word_cut(drop[0], drop[-1])
                edits.append(dict(type="dup", start=s, end=e, text=" ".join(W[k]["text"] for k in drop),
                                  reason="дубль, оставлен: «" + " ".join(W[k]["text"] for k in keepx)[:80] + "»"))
                taken.add(pi if drop is A else qi)
                break

    edits = [e for e in edits if e["end"] - e["start"] > 0.03]
    edits.sort(key=lambda e: e["start"])
    for e in edits:
        e["id"] = _eid()
        e["accepted"] = None   # None — предложено, True — принять, False — отклонить
    return edits


# ---------------------------------------------------------------- применение
def merged_removals(edits: list[dict]) -> list[tuple[float, float]]:
    iv = sorted((e["start"], e["end"]) for e in edits if e.get("accepted"))
    out: list[list[float]] = []
    for s, e in iv:
        if out and s <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(a, b) for a, b in out]


def kept_ranges(edits: list[dict], duration: float) -> list[tuple[float, float]]:
    rem = merged_removals(edits)
    out, t = [], 0.0
    for s, e in rem:
        if s - t > 0.08:
            out.append((round(t, 3), round(s, 3)))
        t = max(t, e)
    if duration - t > 0.08:
        out.append((round(t, 3), round(duration, 3)))
    return out


def remap_words(words: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """Слова, целиком попавшие в оставленные куски, с временем на чистом таймлайне."""
    out, off = [], []
    acc = 0.0
    for s, e in ranges:
        off.append((s, e, acc)); acc += e - s
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        for s, e, a in off:
            if s <= mid <= e:
                ns = max(s, w["start"]) - s + a
                ne = min(e, w["end"]) - s + a
                out.append(dict(w, start=round(ns, 3), end=round(max(ne, ns + 0.05), 3)))
                break
    return out


def apply(src: str, dst: str, ranges: list[tuple[float, float]], crossfade_ms: int = 30, job=None) -> None:
    import os
    import tempfile
    cf = crossfade_ms / 1000
    parts = []
    for i, (s, e) in enumerate(ranges):
        L = e - s
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={min(cf, L / 3):.3f},afade=t=out:st={max(0, L - min(cf, L / 3)):.3f}:d={min(cf, L / 3):.3f}[a{i}];")
    parts.append("".join(f"[v{i}][a{i}]" for i in range(len(ranges))) + f"concat=n={len(ranges)}:v=1:a=1[v][a]")
    fd, script = tempfile.mkstemp(suffix=".txt", prefix="cut_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    total = sum(e - s for s, e in ranges)
    run_progress(["ffmpeg", "-y", "-hide_banner", "-i", src, "-/filter_complex", script, "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-g", "30", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", dst],
                 total, job, 0.05, 1.0, "Склейка")
    os.remove(script)
