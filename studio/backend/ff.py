"""Запуск ffmpeg с прогрессом и мелкие помощники."""
from __future__ import annotations

import json
import subprocess
import threading

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]}: " + (r.stderr or r.stdout)[-800:])
    return r


def run_progress(cmd: list[str], duration: float, job=None, p0: float = 0.0, p1: float = 1.0, msg: str = "",
                 cwd: str | None = None) -> None:
    """ffmpeg с -progress pipe:1: двигает job.progress от p0 до p1."""
    cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    err: list[str] = []
    threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True).start()
    for line in proc.stdout:
        if job is not None and line.startswith("out_time_us="):
            try:
                t = int(line.split("=")[1]) / 1e6
                job.update(p0 + (p1 - p0) * min(t / max(duration, 0.1), 1.0), f"{msg} {t:.1f}/{duration:.1f} c")
            except ValueError:
                pass
        if job is not None and job.cancel_flag.is_set():
            proc.kill()
    proc.wait()
    if job is not None and job.cancel_flag.is_set():
        raise RuntimeError("Отменено")
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg: " + "".join(err)[-1200:])


def duration(path: str) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(r.stdout.strip() or 0)


def loudness(path: str) -> dict:
    """Интегральная громкость (LUFS) и диапазон через ebur128."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    txt = r.stderr
    out = {}
    import re
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", txt)
    if m: out["I"] = float(m[-1])
    m = re.findall(r"LRA:\s+(-?[\d.]+) LU", txt)
    if m: out["LRA"] = float(m[-1])
    m = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", txt)
    if m: out["peak"] = float(m[-1])
    return out


def jdump(obj, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
