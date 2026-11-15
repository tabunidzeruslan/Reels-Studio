"""Монтажная — FastAPI на http://127.0.0.1:8790."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analyze_style, compose, cs, find_cuts, motion, projects, render, rules, sources, transcribe
from .config import CAPTIONS_DIR, FRONTEND, KIT_DIR, OUTPUT, WORK
from .ff import jdump, jload

app = FastAPI(title="Монтажная")


@app.exception_handler(Exception)
async def _err(_req, exc):
    code = 403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, FileNotFoundError) else 400
    return JSONResponse({"detail": str(exc)}, status_code=code)


# ---------------------------------------------------------------- статика: свой фронтенд + движок Captions Studio
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
app.mount("/cs", StaticFiles(directory=CAPTIONS_DIR / "frontend"), name="cs")      # engine.js как есть
app.mount("/fonts", StaticFiles(directory=cs.FONTS_DIR), name="fonts")            # engine.js грузит /fonts/<file>
app.mount("/emoji", StaticFiles(directory=cs.EMOJI_DIR), name="emoji")            # и /emoji/emoji.json


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/info")
def info():
    gpu = ""
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True,
                             timeout=4).stdout.strip()
    except Exception:
        pass
    return {"gpu": gpu, "ffmpeg": bool(shutil.which("ffmpeg")), "captions": (CAPTIONS_DIR / ".venv").exists(),
            "kit": KIT_DIR.exists(), "motion": motion.status(), "work": str(WORK), "output": str(OUTPUT)}


@app.get("/api/fonts")
def fonts():
    return cs.cs_fonts.list_fonts()


@app.get("/api/presets")
def presets():
    return cs.presets()


@app.post("/api/presets")
def save_preset(body: dict = Body(...)):
    pid = analyze_style.slug(body.get("id") or body.get("name", "preset"))
    return {"path": cs.save_user_preset(pid, body.get("name", pid), body.get("style", {})), "id": pid}


# ---------------------------------------------------------------- задачи
@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = cs.JOBS.get(jid)
    if not j:
        raise FileNotFoundError("Задача не найдена")
    return j.public()


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    j = cs.JOBS.get(jid)
    if j: j.cancel_flag.set()
    return {"ok": True}


@app.get("/api/jobs")
def jobs():
    return [j.public() for j in list(cs.JOBS.values())[-30:]]


# ---------------------------------------------------------------- исходники
@app.get("/api/sources/allowed")
def allowed():
    return sources.allowed_dirs()


@app.post("/api/sources/allow")
def allow(body: dict = Body(...)):
    return sources.allow(body["path"])


@app.post("/api/sources/scan")
def scan(body: dict = Body(...)):
    path = body["path"]
    if not sources.is_allowed(path):
        return JSONResponse({"need_permission": True, "path": os.path.abspath(path)}, status_code=403)
    return sources.scan(path)


@app.get("/api/thumb")
def thumb(path: str):
    return FileResponse(sources.thumbnail(path))


@app.get("/api/media")
def media(path: str):
    """Видео/картинки: исходники из разрешённых папок, файлы work\\, output\\ и библиотеки моушна."""
    ap = os.path.abspath(path)
    ok = sources.is_allowed(ap) or any(sources.norm(ap).startswith(sources.norm(str(d)) + os.sep)
                                       for d in (WORK, OUTPUT, motion.MOTION_DIR / "output"))
    if not ok or not os.path.isfile(ap):
        raise PermissionError("Нет доступа к файлу")
    return FileResponse(ap)


# ---------------------------------------------------------------- проекты
@app.get("/api/projects")
def list_projects():
    return projects.list_all()


@app.post("/api/projects")
def create(body: dict = Body(...)):
    p = projects.new(body.get("title", ""))
    P = rules.params()
    p["caption_preset"] = P["caption_preset"]
    if P.get("music"): p["music"].update(file=P["music"], volume=P["music_volume"])
    else: p["music"]["enabled"] = False
    return projects.save(p)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return projects.load(pid)


@app.put("/api/projects/{pid}")
def put_project(pid: str, body: dict = Body(...)):
    p = projects.load(pid)
    for k in ("title", "sources", "lang", "style", "caption_preset", "caption_style", "hook", "motion", "punch", "music",
              "sfx", "phrases_override", "edits"):
        if k in body:
            p[k] = body[k]
    if "sources" in body:
        for s in p["sources"]:
            if not sources.is_allowed(s["path"]):
                raise PermissionError("Клип вне разрешённых папок: " + s["path"])
        projects.set_stage(p, "sources", "done" if p["sources"] else "todo", reset_after=True)
    if "edits" in body:
        projects.set_stage(p, "cleanup", "review", reset_after=True)
    if any(k in body for k in ("hook", "motion", "punch", "music", "caption_preset", "phrases_override")):
        projects.set_stage(p, "montage", "review", reset_after=True)
    return projects.save(p)


@app.delete("/api/projects/{pid}")
def del_project(pid: str):
    projects.delete(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/file/{name}")
def pfile(pid: str, name: str):
    f = projects.pdir(pid) / Path(name).name
    if not f.exists():
        raise FileNotFoundError(name)
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/prepare")
def prepare(pid: str):
    """Подготовка (кроп, 1080×1920) → распознавание → поиск правок."""
    def work(job):
        p = projects.load(pid); pd = projects.pdir(pid)
        projects.set_stage(p, "prepare", "running", reset_after=True); projects.save(p)
        compose.prepare(p, pd, job)
        p = projects.load(pid); projects.set_stage(p, "prepare", "done"); projects.set_stage(p, "transcribe", "running"); projects.save(p)
        job.update(0.0, "Распознавание речи…")
        r = transcribe.transcribe(str(pd / "raw.mp4"), p.get("lang", "ru"), job=job)
        jdump(r, pd / "words.json")
        P = render.effective_params(p)
        edits = find_cuts.find(r["words"], compose.dur_of(str(pd / "raw.mp4")), P)
        p = projects.load(pid)
        p["edits"] = edits
        projects.set_stage(p, "transcribe", "done"); projects.set_stage(p, "cleanup", "review")
        projects.save(p)
        return {"words": len(r["words"]), "edits": len(edits)}
    return cs.start_job("prepare", _mark_error(pid, work, ("prepare", "transcribe"))).public()


def _mark_error(pid, fn, stages):
    """При ошибке этап «running» → «error», чтобы проект не висел «в работе»."""
    def wrapped(job):
        try:
            return fn(job)
        except Exception:
            p = projects.load(pid)
            for s in stages:
                if p["stages"].get(s) == "running":
                    p["stages"][s] = "error"
            projects.save(p)
            raise
    return wrapped


@app.get("/api/projects/{pid}/words")
def words(pid: str):
    pd = projects.pdir(pid)
    r = jload(pd / "words.json", {"words": []})
    c = jload(pd / "clean_words.json")
    p = projects.load(pid)
    out = {"raw": r["words"], "language": r.get("language")}
    if c:
        out["clean"] = c["words"]
        out["final"] = compose.final_words(p, c["words"])
        out["hooks"] = c.get("hooks", [])
        out["duration"] = c.get("duration")
    return out


@app.post("/api/projects/{pid}/refind")
def refind(pid: str):
    p = projects.load(pid); pd = projects.pdir(pid)
    r = jload(pd / "words.json")
    p["edits"] = find_cuts.find(r["words"], compose.dur_of(str(pd / "raw.mp4")), render.effective_params(p))
    projects.set_stage(p, "cleanup", "review", reset_after=True)
    return projects.save(p)


@app.post("/api/projects/{pid}/apply_cuts")
def apply_cuts(pid: str):
    """Склейка по принятым правкам → clean.mp4, затем план монтажа: хук, punch-in, графика на словах."""
    def work(job):
        p = projects.load(pid); pd = projects.pdir(pid)
        P = render.effective_params(p)
        D = compose.dur_of(str(pd / "raw.mp4"))
        ranges = find_cuts.kept_ranges(p["edits"], D)
        find_cuts.apply(str(pd / "raw.mp4"), str(pd / "clean.mp4"), ranges, P["crossfade_ms"], job)
        W = find_cuts.remap_words(jload(pd / "words.json")["words"], ranges)
        hooks = compose.hook_candidates(W)
        jdump({"words": W, "ranges": ranges, "hooks": hooks, "duration": sum(e - s for s, e in ranges)}, pd / "clean_words.json")
        p = projects.load(pid)
        p["hook"] = ({k: hooks[0][k] for k in ("start", "end", "text")}
                     if P.get("hook", True) and hooks and hooks[0]["score"] >= 3 and hooks[0]["idx"] != 0 else None)
        p["punch"] = compose.plan_punch([e - s for s, e in ranges], W, P["punch_in"], P.get("punch_every", 1))
        # свои клипы из библиотеки оставляем, карточки на словах предлагаем заново (тайминг изменился)
        p["motion"] = [m for m in p.get("motion", []) if m.get("source") == "clip"] + \
            (compose.suggest_graphics(W) if P.get("graphics", True) else [])
        p["phrases_override"] = None
        projects.set_stage(p, "cleanup", "done"); projects.set_stage(p, "montage", "review", reset_after=True)
        projects.save(p)
        return {"ranges": len(ranges), "duration": round(sum(e - s for s, e in ranges), 2)}
    return cs.start_job("cuts", work).public()


@app.post("/api/projects/{pid}/render")
def do_render(pid: str, body: dict = Body(...)):
    kind = body.get("kind", "preview")
    if not body.get("ass"):
        raise ValueError("Нет субтитров (.ass)")
    return render.start(pid, kind, body["ass"], body.get("emojis") or []).public()


@app.get("/api/projects/{pid}/card/{gid}")
def card(pid: str, gid: str):
    p = projects.load(pid)
    g = next((x for x in p["motion"] if x["id"] == gid), None)
    if not g:
        raise FileNotFoundError(gid)
    d = projects.pdir(pid) / "cards"; d.mkdir(exist_ok=True)
    return FileResponse(compose.render_card(g, d / f"{gid}.png"), headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- монтажка с агентами
@app.get("/api/projects/{pid}/agents")
def agents_state(pid: str):
    p = projects.load(pid)
    return {"agents": p.get("agents", {}), "log": jload(projects.pdir(pid) / "agents_log.json", [])}


@app.post("/api/projects/{pid}/agents")
def agents_update(pid: str, body: dict = Body(...)):
    """{agent, status?, note?, log?} — статус агента и строка в журнал."""
    import time as _t
    p = projects.load(pid)
    ag = p.setdefault("agents", {})
    if body.get("reset"):
        p["agents"] = ag = {}
        jdump([], projects.pdir(pid) / "agents_log.json")
    name = body.get("agent")
    if name:
        a = ag.setdefault(name, {"status": "wait"})
        if "status" in body: a["status"] = body["status"]
        if "note" in body: a["note"] = body["note"]
    if body.get("log"):
        lf = projects.pdir(pid) / "agents_log.json"
        log = jload(lf, [])
        log.append({"t": _t.time(), "agent": name or "", "text": body["log"]})
        jdump(log[-400:], lf)
    projects.save(p)
    return agents_state(pid)


@app.get("/api/projects/{pid}/frames")
def frames(pid: str, n: int = 12):
    """Кадры чистого видео (или исходника) для панели «Кадры» и дорожки «Видео»."""
    pd = projects.pdir(pid)
    src = pd / "clean.mp4" if (pd / "clean.mp4").exists() else pd / "raw.mp4"
    if not src.exists():
        return []
    fd = pd / "frames"; fd.mkdir(exist_ok=True)
    stamp = fd / f".{int(src.stat().st_mtime)}_{n}"
    if not stamp.exists():
        for f in fd.glob("*"): f.unlink()
        D = compose.dur_of(str(src))
        from .ff import run as _run
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"fps={n}/{max(D, 0.1):.3f},scale=180:-2", "-q:v", "5",
              "-frames:v", str(n), str(fd / "f_%02d.jpg")])
        stamp.touch()
    D = compose.dur_of(str(src))
    files = sorted(fd.glob("f_*.jpg"))
    return [{"url": f"/api/projects/{pid}/frame/{f.name}?v={int(src.stat().st_mtime)}", "t":round(D * (i + 0.5) / len(files), 2)} for i, f in enumerate(files)]


@app.get("/api/projects/{pid}/frame/{name}")
def frame_file(pid: str, name: str):
    return FileResponse(projects.pdir(pid) / "frames" / Path(name).name)


@app.get("/api/projects/{pid}/wave")
def wave(pid: str, n: int = 600):
    """Огибающая голоса (0..1) для дорожки «Голос»."""
    import numpy as np
    import subprocess as sp
    pd = projects.pdir(pid)
    src = pd / "clean.mp4" if (pd / "clean.mp4").exists() else pd / "raw.mp4"
    if not src.exists():
        return []
    r = sp.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    if not len(a):
        return []
    k = max(1, len(a) // n)
    env = np.sqrt(np.mean(a[: len(a) // k * k].reshape(-1, k) ** 2, axis=1))
    return [round(float(x), 3) for x in env / (env.max() + 1e-9)]


# ---------------------------------------------------------------- стили
@app.get("/api/styles")
def styles():
    return analyze_style.list_styles()


@app.post("/api/styles/analyze")
def analyze(body: dict = Body(...)):
    paths = body["paths"]
    for x in paths:
        if not sources.is_allowed(x):
            raise PermissionError("Файл вне разрешённых папок: " + x)
    return cs.start_job("style", lambda job: analyze_style.analyze(paths, body.get("title", "Стиль"), body.get("lang", "ru"), job)).public()


@app.put("/api/styles/{name}")
def put_style(name: str, body: dict = Body(...)):
    st = analyze_style.get(name)
    st.update({k: v for k, v in body.items() if k in ("title", "summary", "visual", "params")})
    st["name"] = name
    return analyze_style.save(st)


@app.get("/api/img")
def img(path: str):
    ap = os.path.abspath(path)
    if not sources.norm(ap).startswith(sources.norm(str(WORK)) + os.sep):
        raise PermissionError("Нет доступа")
    return FileResponse(ap)


# ---------------------------------------------------------------- моушн, музыка
@app.get("/api/motion/library")
def mlib():
    return motion.library()


@app.get("/api/motion/status")
def mstatus():
    return motion.status()


@app.post("/api/motion/start")
def mstart():
    return motion.start()


@app.get("/api/music")
def music():
    return compose.music_list()


@app.get("/api/music/file")
def music_file(name: str):
    for m in compose.music_list():
        if m["file"] == name:
            return FileResponse(m["path"])
    raise FileNotFoundError(name)


# ---------------------------------------------------------------- правила
@app.get("/api/rules")
def get_rules():
    return {"text": rules.text(), "params": rules.params(), "file": str(rules.FILE)}


@app.put("/api/rules")
def put_rules(body: dict = Body(...)):
    return {"params": rules.save_text(body["text"]), "text": rules.text()}


@app.post("/api/rules/add")
def add_rule(body: dict = Body(...)):
    r = rules.add(body["note"])
    r["text"] = rules.text()
    return r


# ---------------------------------------------------------------- прочее
@app.post("/api/reveal")
def reveal(body: dict = Body(...)):
    p = os.path.abspath(body["path"])
    if os.path.exists(p):
        subprocess.Popen(["explorer", "/select,", p])
    return {"ok": True}
