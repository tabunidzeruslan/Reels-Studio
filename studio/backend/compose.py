"""Монтаж: подготовка исходников (кроп по лицу, 1080×1920), хук, punch-in, графика на словах, музыка и звуки.

Правила по мотивам reels-montage-kit (beat-planning, move-bank, sound-design): сильная фраза — в начало, на каждой
смене мысли punch-in 1.1–1.2×, чтобы спрятать джамп-кат, графика ставится ровно на слово и живёт 1.2–2 с, не чаще
раза в ~3 с, музыка тихо под голосом с ducking, итог -14 LUFS.
"""
from __future__ import annotations

import os
import re
import statistics
import tempfile
import uuid
from pathlib import Path

from . import cs
from .config import KIT_MUSIC, KIT_SFX, MOTION_DIR
from .ff import duration as dur_of, jdump, jload, run, run_progress

W, H, FPS = 1080, 1920, 30


# ================================================================ подготовка исходников
def face_center(path: str, samples: int = 14) -> tuple[float, float] | None:
    """Медианный центр лица (доли кадра) по нескольким кадрам. OpenCV Haar."""
    # OpenCV на Windows не открывает пути с кириллицей: каскад копируем во временную папку,
    # кадры достаём через ffmpeg (сырые серые пиксели в pipe)
    import shutil
    import subprocess

    import cv2
    import numpy as np
    from .ff import NO_WINDOW
    casc = Path(tempfile.gettempdir()) / "mt_haar_face.xml"
    if not casc.exists():
        shutil.copy(cv2.data.haarcascades + "haarcascade_frontalface_default.xml", casc)
    det = cv2.CascadeClassifier(str(casc))
    info = cs.probe(path)
    D, w0, h0 = info["duration"], info["width"], info["height"]
    sc = 640 / max(w0, h0)
    gw, gh = int(w0 * sc) // 2 * 2, int(h0 * sc) // 2 * 2
    xs, ys = [], []
    for k in range(samples):
        t = D * (k + 0.5) / samples
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", f"scale={gw}:{gh}",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, creationflags=NO_WINDOW)
        if len(r.stdout) != gw * gh:
            continue
        g = np.frombuffer(r.stdout, np.uint8).reshape(gh, gw)
        faces = det.detectMultiScale(g, 1.15, 5, minSize=(24, 24))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + fw / 2) / gw); ys.append((y + fh / 2) / gh)
    if not xs:
        return None
    return statistics.median(xs), statistics.median(ys)


def prepare(p: dict, pd: Path, job=None) -> dict:
    """Все выбранные клипы → work\\<id>\\raw.mp4: 1080×1920, 30 fps, кроп по лицу, звук 48 кГц стерео."""
    srcs = p["sources"]
    if not srcs:
        raise RuntimeError("Не выбраны клипы")
    inputs, chains, faces, total = [], [], [], 0.0
    for i, s in enumerate(srcs):
        info = cs.probe(s["path"])
        total += info["duration"]
        inputs += ["-i", s["path"]]
        if job: job.update(0.02 + 0.1 * i / len(srcs), f"Ищу лицо: {Path(s['path']).name}")
        fc = face_center(s["path"]) or (0.5, 0.4)
        faces.append(fc)
        w, h = info["width"], info["height"]
        pre = cs.cs_render._HDR_TO_SDR + "," if info.get("hdr") else ""
        if w / h > W / H + 0.01:          # шире вертикали — кроп по лицу
            cw = f"ih*{W}/{H}"
            x = f"max(0\\,min(iw-{cw}\\,iw*{fc[0]:.4f}-{cw}/2))"
            vf = f"{pre}crop={cw}:ih:{x}:0,scale={W}:{H}"
        else:                              # уже или ровно вертикаль — заполняем кадр
            vf = f"{pre}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        chains.append(f"[{i}:v]{vf},fps={FPS},setsar=1,format=yuv420p[v{i}]")
        if info.get("acodec"):
            chains.append(f"[{i}:a]aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo[a{i}]")
        else:
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{info['duration']:.3f}[a{i}]")
    durs = [cs.probe(s["path"])["duration"] for s in srcs]
    if len(srcs) == 1:
        chains.append("[v0]null[v];[a0]anull[a]")
    else:
        # переходы между клипами: плавный сдвиг кадра 0.35 с + кроссфейд звука (чередуем направление)
        T = 0.35
        trans = ["smoothleft", "smoothup", "fadeblack", "smoothright"]
        vl, al, acc = "v0", "a0", durs[0]
        for i in range(1, len(srcs)):
            off = max(0.1, acc - T)
            chains.append(f"[{vl}][v{i}]xfade=transition={trans[(i - 1) % len(trans)]}:duration={T}:offset={off:.3f}[vx{i}]")
            chains.append(f"[{al}][a{i}]acrossfade=d={T}[ax{i}]")
            vl, al = f"vx{i}", f"ax{i}"
            acc += durs[i] - T
        chains.append(f"[{vl}]null[v];[{al}]anull[a]")
    out = pd / "raw.mp4"
    run_progress(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-g", "30", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)],
                 total, job, 0.15, 0.95, "Подготовка")
    # лицо на готовом кадре (для punch-in по лицу)
    f = face_center(str(out)) or (0.5, 0.4)
    jdump({"cx": f[0], "cy": f[1]}, pd / "face.json")
    return {"duration": dur_of(str(out))}


# ================================================================ хук
HOOK_WORDS = ("никто", "секрет", "ошибк", "главн", "почему", "стоп", "не делай", "самы", "лучш", "худш", "правд", "миф",
              "деньг", "бесплатн", "быстр", "просто", "никогда", "всегда", "срочно", "запомни", "важн", "вы теряете",
              "проблем", "как ", "сколько", "зачем", "хватит", "внимание", "результат", "рост", "миллион", "тысяч")


def sentences(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for k, w in enumerate(words):
        if cur and (w["start"] - words[k - 1]["end"] > 0.6 or re.search(r"[.!?…]$", words[k - 1]["text"])):
            out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["text"] for w in s), "n": len(s), "idx": i}
            for i, s in enumerate(out)]


def hook_candidates(words: list[dict], top: int = 3) -> list[dict]:
    res = []
    ss = sentences(words)
    for s in ss:
        t = s["text"].lower()
        sc = 0.0
        if 4 <= s["n"] <= 14: sc += 2
        elif s["n"] > 20: sc -= 2
        if re.search(r"\d", t): sc += 3
        if "?" in t or "!" in t: sc += 1.5
        sc += 1.5 * sum(1 for k in HOOK_WORDS if k in t)
        if s["idx"] == 0: sc -= 1.5          # уже стоит в начале
        if s["idx"] == len(ss) - 1 and len(ss) > 2: sc -= 1.5   # концовка (часто CTA) — не хук
        if s["end"] - s["start"] > 6: sc -= 2
        res.append(dict(s, score=round(sc, 2)))
    res.sort(key=lambda x: -x["score"])
    return res[:top]


# ================================================================ punch-in
def plan_punch(clean_ranges_len: list[float], words: list[dict], zoom: float, every: int = 1) -> list[dict]:
    """Куски чистого видео между склейками; на смене мысли чередуем 1.0 / zoom. Куски < 1.2 с сливаем."""
    cuts, acc = [], 0.0
    for L in clean_ranges_len[:-1]:
        acc += L; cuts.append(round(acc, 3))
    total = round(sum(clean_ranges_len), 3)
    sent_ends = [s["end"] for s in sentences(words)]
    # склейка «на смене мысли»: рядом конец предложения; иначе каждая n-я склейка
    marks = []
    for k, c in enumerate(cuts):
        near = any(abs(c - e) < 0.6 for e in sent_ends)
        if near or (k % max(1, every) == 0):
            marks.append(c)
    pieces, t0, z_on = [], 0.0, False
    for c in marks + [total]:
        if c - t0 < 1.2 and c != total:
            continue
        pieces.append({"start": round(t0, 3), "end": round(c, 3), "zoom": zoom if z_on else 1.0})
        z_on = not z_on; t0 = c
    if pieces and pieces[-1]["end"] < total:
        pieces[-1]["end"] = total
    return pieces


# ================================================================ графика на словах
NUM_RE = re.compile(r"^\d[\d\s.,]*(%|₽|\$|€|к|k|тыс|млн|млрд)?$", re.I)
NUM_WORDS = {"тысяч", "тысячи", "тысяча", "миллион", "миллиона", "миллионов", "процентов", "процента", "рублей", "долларов", "раз"}
CTA_RE = re.compile(r"(оставь|оставьте|пиши|напиши|напишите|подпиш|ссылк|директ|коммент|заявк|запис|переходи|жми|сохрани|забирай)", re.I)


def suggest_graphics(words: list[dict], min_gap: float = 3.0) -> list[dict]:
    out, last_t = [], -99.0
    n = len(words)
    i = 0
    while i < n:
        w = words[i]
        t = w["text"].strip(".,!?;:…«»\"")
        nxt = words[i + 1]["text"].strip(".,!?;:…«»\"").lower() if i + 1 < n else ""
        item = None
        if NUM_RE.match(t) and re.search(r"\d", t):
            label = t + ((" " + nxt) if nxt in NUM_WORDS or nxt in {"%", "₽"} else "")
            item = {"kind": "number", "text": label.upper()}
        elif re.match(r"^[A-Z][A-Za-z0-9+.]{2,}$", t) and t.lower() not in {"the", "and"}:
            item = {"kind": "title", "text": t}
        elif CTA_RE.search(w["text"]) and w["start"] > max(4.0, words[-1]["end"] * 0.6):
            seg = " ".join(x["text"] for x in words[i:i + 4]).strip(".,!?…")
            item = {"kind": "cta", "text": seg[:28].upper()}
        if item and w["start"] - last_t >= min_gap:
            item.update(id=uuid.uuid4().hex[:8], t=round(w["start"], 2), dur=1.8 if item["kind"] != "cta" else 2.6,
                        y=0.2, source="card", accepted=None, word=w["text"])
            out.append(item); last_t = w["start"]
        i += 1
    return out


# ---------------------------------------------------------------- карточки (Pillow)
def _font(name: str, size: int):
    from PIL import ImageFont
    for f in (cs.FONTS_DIR / name, cs.FONTS_DIR / "MontserratBlack.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(str(f), size)
    return ImageFont.load_default()


def render_card(item: dict, out: Path, accent: str = "#FFE14D") -> Path:
    from PIL import Image, ImageDraw, ImageFilter
    kind, text = item["kind"], item["text"]
    if kind == "number":
        font, fg, bg, pad, rad = _font("UnboundedExtraBold.ttf", 100), accent, (16, 16, 22, 225), 48, 40
    elif kind == "cta":
        font, fg, bg, pad, rad = _font("MontserratBlack.ttf", 68), "#111111", accent, 40, 60
        text = text + "  →"
    else:
        font, fg, bg, pad, rad = _font("MontserratBlack.ttf", 78), "#111111", (255, 255, 255, 245), 38, 28
    tmp = Image.new("RGBA", (10, 10)); d = ImageDraw.Draw(tmp)
    # перенос строк по ширине
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if d.textlength(trial, font=font) > 780 and cur:
            lines.append(cur); cur = wd
        else:
            cur = trial
    lines.append(cur)
    lh = int(font.size * 1.1)
    tw = int(max(d.textlength(l, font=font) for l in lines))
    bw, bh = tw + pad * 2, lh * len(lines) + pad * 2 - int(font.size * 0.1)
    img = Image.new("RGBA", (bw + 60, bh + 60), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((30, 40, 30 + bw, 40 + bh), rad, fill=(0, 0, 0, 120))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    dd = ImageDraw.Draw(img)
    dd.rounded_rectangle((30, 30, 30 + bw, 30 + bh), rad, fill=bg)
    y = 30 + pad - int(font.size * 0.08)
    for l in lines:
        lw = d.textlength(l, font=font)
        dd.text((30 + (bw - lw) / 2, y), l, font=font, fill=fg)
        y += lh
    img.save(out)
    return out


# ================================================================ сборка
def _sfx(name: str) -> str | None:
    d = KIT_SFX / name
    if d.is_dir():
        f = sorted(d.glob("*.wav"))
        return str(f[0]) if f else None
    return None


def music_list() -> list[dict]:
    out = []
    for d, src in ((KIT_MUSIC, "kit"), (MOTION_DIR / "music", "motion")):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}:
                    out.append({"file": f.name, "path": str(f), "source": src})
    return out


MOODS = {
    "ambient_tech_90.mp3": ("нейросет", "ии", "claude", "chatgpt", "gpt", "код", "программ", "сайт", "приложен", "автоматиз", "технолог", "бот", "агент"),
    "tense_b.mp3": ("ошибк", "проблем", "теряе", "стоп", "опасн", "никогда", "хватит", "срочно", "минус", "провал", "долг"),
    "tense_c.mp3": ("деньг", "заработ", "доход", "миллион", "продаж", "клиент", "бизнес", "рост", "результат", "рубл", "доллар"),
    "lofi_keys_84.mp3": ("жизн", "утро", "дом", "семь", "кофе", "спокой", "привычк", "отдых", "путешеств", "еда", "рецепт"),
}


def pick_music(words: list[dict]) -> tuple[str, str]:
    """Музыка «в тему»: по словам ролика выбираем настроение из библиотеки (кит + Моушн-студия)."""
    text = " ".join(w["text"].lower() for w in words)
    have = {m["file"] for m in music_list()}
    score = {f: sum(text.count(k) for k in ks) for f, ks in MOODS.items() if f in have}
    if not score:
        return (next(iter(have)) if have else ""), "единственный трек"
    best = max(score, key=score.get)
    if score[best] == 0:
        best = "lofi_keys_84.mp3" if "lofi_keys_84.mp3" in have else best
        return best, "спокойный фон по умолчанию"
    why = {"ambient_tech_90.mp3": "про технологии", "tense_b.mp3": "про проблему/ошибку", "tense_c.mp3": "про деньги и рост",
           "lofi_keys_84.mp3": "про жизнь и спокойные темы"}[best]
    return best, why


def _music_path(name: str) -> str | None:
    for m in music_list():
        if m["file"] == name:
            return m["path"]
    return None


def overlay_mode(path: str) -> str:
    n = Path(path).name.lower()
    if "_transparent" in n or n.endswith((".mov", ".webm")):
        return "alpha"
    if "_green" in n:
        return "green"
    return "full"


def build(p: dict, pd: Path, words: list[dict], P: dict, final: bool, job=None) -> tuple[Path, float]:
    """clean.mp4 → base.mp4 (без субтитров): хук + punch-in + графика + музыка/звуки + -14 LUFS."""
    clean = pd / "clean.mp4"
    face = jload(pd / "face.json", {"cx": 0.5, "cy": 0.4})
    cx, cy = face["cx"] * W, face["cy"] * H
    pieces = []
    hook = p.get("hook") if P.get("hook", True) else None
    if hook:
        pieces.append({"start": hook["start"], "end": hook["end"], "zoom": round(max(P["punch_in"], 1.1) + 0.05, 2), "hook": True})
    pieces += p.get("punch") or [{"start": 0, "end": dur_of(str(clean)), "zoom": 1.0}]
    hook_len = (hook["end"] - hook["start"]) if hook else 0.0

    inputs = ["-i", str(clean)]
    ch = []
    for i, pc in enumerate(pieces):
        z = pc["zoom"]
        L = pc["end"] - pc["start"]
        if z > 1.001:
            sw, sh = int(W * z) // 2 * 2, int(H * z) // 2 * 2
            x = int(min(max(cx * z - cx, 0), sw - W)); y = int(min(max(cy * z - cy, 0), sh - H))
            zf = f",scale={sw}:{sh},crop={W}:{H}:{x}:{y}"
        else:
            zf = ""
        ch.append(f"[0:v]trim=start={pc['start']:.3f}:end={pc['end']:.3f},setpts=PTS-STARTPTS{zf},setsar=1[pv{i}]")
        f = min(0.02, L / 4)
        ch.append(f"[0:a]atrim=start={pc['start']:.3f}:end={pc['end']:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d={f:.3f},afade=t=out:st={L - f:.3f}:d={f:.3f}[pa{i}]")
    ch.append("".join(f"[pv{i}][pa{i}]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=1[vc][voice0]")
    total = sum(pc["end"] - pc["start"] for pc in pieces)

    # ---- графика
    last, nin = "vc", 1
    sfx_events: list[tuple[float, str]] = []
    if hook:
        sfx_events.append((hook_len, "whoosh_soft"))
    cards_dir = pd / "cards"; cards_dir.mkdir(exist_ok=True)
    for k, g in enumerate(x for x in p.get("motion", []) if x.get("accepted")):
        T = round(g["t"] + hook_len, 3)
        D = float(g.get("dur", 1.8))
        if g.get("source") == "card":
            png = render_card(g, cards_dir / f"{g['id']}.png")
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D:.2f}", "-i", str(png)]
            ch.append(f"[{nin}:v]format=rgba,fade=t=in:st=0:d=0.15:alpha=1,fade=t=out:st={max(0, D - 0.2):.2f}:d=0.2:alpha=1,"
                      f"setpts=PTS+{T:.3f}/TB[g{k}]")
            Y = g.get("y", 0.2) * H
            ch.append(f"[{last}][g{k}]overlay=x=(W-w)/2:y='{Y:.0f}-h/2+60*max(0\\,1-(t-{T:.3f})/0.18)':eval=frame:"
                      f"eof_action=pass[o{k}]")
            sfx_events.append((T, "pop" if g["kind"] != "cta" else "whoosh"))
        else:
            path = g["file"]
            mode = g.get("mode") or overlay_mode(path)
            dec = ["-c:v", "libvpx-vp9"] if path.lower().endswith(".webm") else []
            inputs += [*dec, "-t", f"{D:.2f}", "-i", path]
            sc = float(g.get("scale", 1.0 if mode == "full" else 0.8))
            base = f"[{nin}:v]"
            if mode == "full":
                ch.append(f"{base}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=rgba,"
                          f"fade=t=in:d=0.12:alpha=1,setpts=PTS-STARTPTS+{T:.3f}/TB[g{k}]")
                ch.append(f"[{last}][g{k}]overlay=0:0:eof_action=pass[o{k}]")
            else:
                key = ",chromakey=0x00FF00:0.28:0.08" if mode == "green" else ""
                ch.append(f"{base}format=rgba{key},scale=iw*{sc}*{W}/iw:-2,setpts=PTS-STARTPTS+{T:.3f}/TB[g{k}]")
                Y = g.get("y", 0.3) * H
                ch.append(f"[{last}][g{k}]overlay=x=(W-w)/2:y={Y:.0f}-h/2:eof_action=pass[o{k}]")
            sfx_events.append((T, "whoosh"))
        last = f"o{k}"; nin += 1

    # ---- озвучка ElevenLabs: подмешиваем к голосу до ducking (музыка приглушается и под неё)
    vos = [v for v in p.get("voiceovers", []) if v.get("enabled", True) and Path(v["file"]).exists()]
    if vos:
        labs = []
        for j, v in enumerate(vos):
            inputs += ["-i", v["file"]]
            ms = int(max(0.0, v["t"] + hook_len) * 1000)
            ch.append(f"[{nin}:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(v.get('volume', 1)):.2f},"
                      f"adelay={ms}|{ms}[vo{j}]")
            labs.append(f"[vo{j}]"); nin += 1
        ch.append("[voice0]" + "".join(labs) + f"amix=inputs={len(labs) + 1}:normalize=0:duration=first[voice]")
    else:
        ch.append("[voice0]anull[voice]")

    # ---- звук: голос + музыка с ducking + sfx, итог -14 LUFS
    amix_in = []
    mpath = _music_path(p["music"]["file"]) if p.get("music", {}).get("enabled") and p["music"].get("file") else None
    if mpath:
        inputs += ["-stream_loop", "-1", "-i", mpath]
        vol = float(p["music"].get("volume", P["music_volume"]))
        ch.append(f"[voice]asplit=2[vo][key]")
        ch.append(f"[{nin}:a]atrim=0:{total:.3f},aresample=48000,aformat=channel_layouts=stereo,volume={vol:.3f},"
                  f"afade=t=in:d=0.6,afade=t=out:st={max(0, total - 1.2):.3f}:d=1.2[mus]")
        ch.append("[mus][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1[duck]")
        amix_in += ["[vo]", "[duck]"]; nin += 1
    else:
        amix_in.append("[voice]")
    if p.get("sfx", True) and P.get("sfx", True):
        for j, (T, name) in enumerate(sfx_events):
            f = _sfx(name) or _sfx("whoosh")
            if not f:
                continue
            inputs += ["-i", f]
            ms = int(max(0, T - 0.05) * 1000)
            ch.append(f"[{nin}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.45,adelay={ms}|{ms}[s{j}]")
            amix_in.append(f"[s{j}]"); nin += 1
    lufs = P.get("lufs", -14)
    ch.append("".join(amix_in) + f"amix=inputs={len(amix_in)}:normalize=0:duration=first,"
              f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[aout]")

    out = pd / ("base_final.mp4" if final else "base_preview.mp4")
    vq = ["-preset", "medium", "-crf", "15"] if final else ["-preset", "ultrafast", "-crf", "22"]
    fd, script = tempfile.mkstemp(suffix=".txt", prefix="compose_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(";\n".join(ch))
    try:
        run_progress(["ffmpeg", "-y", "-hide_banner", *inputs, "-/filter_complex", script, "-map", f"[{last}]", "-map", "[aout]",
                      "-t", f"{total:.3f}", "-c:v", "libx264", *vq, "-g", "60", "-pix_fmt", "yuv420p", "-r", str(FPS),
                      "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)],
                     total, job, 0.02, 0.6, "Монтаж")
    finally:
        os.remove(script)
    return out, hook_len


def final_words(p: dict, clean_words: list[dict]) -> list[dict]:
    """Слова на итоговом таймлайне: хук (копия фразы) + весь ролик со сдвигом."""
    hook = p.get("hook")
    if not hook:
        return clean_words
    L = hook["end"] - hook["start"]
    hw = [dict(w, start=round(w["start"] - hook["start"], 3), end=round(w["end"] - hook["start"], 3))
          for w in clean_words if w["start"] >= hook["start"] - 0.01 and w["end"] <= hook["end"] + 0.01]
    return hw + [dict(w, start=round(w["start"] + L, 3), end=round(w["end"] + L, 3)) for w in clean_words]
