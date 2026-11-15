"""Запуск Монтажной: python run.py → http://127.0.0.1:8790"""
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402

from backend.config import HOST, PORT  # noqa: E402

if __name__ == "__main__":
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run("backend.app:app", host=HOST, port=PORT, log_level="warning")
