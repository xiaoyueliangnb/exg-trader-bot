#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务器控制台：均价、日利润和自动上架进程。监听本机 127.0.0.1，由 1Panel 反代对外。"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from db import load_avg_latest, load_day_detail, load_dotenv, load_profit
from jifen import (
    FRONT_DEPTH,
    LIST_COINS,
    MIN_LIST_PROFIT,
    MIN_PROFIT_PER_COIN,
    listing_quotes_from_avg,
)

load_dotenv()

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "web" / "dist"
LOG_LIMIT = 400

app = FastAPI(title="jifen console")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BotState:
    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.logs: deque[str] = deque(maxlen=LOG_LIMIT)
        self.lock = threading.Lock()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def _stamp(text: str) -> str:
        # scan.py 已带 [HH:MM:SS] 时不再重复
        if len(text) >= 10 and text[0] == "[" and text[9] == "]":
            return text
        return f"[{datetime.now().strftime('%H:%M:%S')}] {text}"

    def append(self, line: str) -> None:
        text = line.rstrip("\n")
        if text:
            self.logs.append(self._stamp(text))

    def start(self) -> str:
        with self.lock:
            if self.running():
                return "already"
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            self.proc = subprocess.Popen(
                [sys.executable, str(ROOT / "scan.py"), "--auto"],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            threading.Thread(target=self._pump, daemon=True).start()
            self.append("控制台：已启动 --auto（间隔按时段）")
            return "started"

    def stop(self) -> str:
        with self.lock:
            if not self.running():
                self.proc = None
                return "idle"
            assert self.proc is not None
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
            self.append("控制台：已停止自动上架")
            return "stopped"

    def _pump(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.append(line)
        code = proc.poll()
        self.append(f"控制台：进程退出 code={code}")


bot = BotState()


@app.get("/api/overview")
def overview() -> dict:
    avg = load_avg_latest()
    profit_file = load_profit()
    quote = None
    can_list = False
    if avg.get("point_avg") is not None and avg.get("coin_avg") is not None:
        quote = listing_quotes_from_avg(
            float(avg["point_avg"]), float(avg["coin_avg"]), LIST_COINS
        )
        can_list = quote["profit"] >= MIN_LIST_PROFIT
    days = []
    raw_days = profit_file.get("days")
    if isinstance(raw_days, dict):
        for key in sorted(raw_days, reverse=True):
            row = raw_days[key]
            if isinstance(row, dict):
                days.append(row)
    yesterday = profit_file.get("yesterday")
    yday = None
    if yesterday and isinstance(raw_days, dict):
        yday = raw_days.get(yesterday)
    today_key = date.today().isoformat()
    today_row = raw_days.get(today_key) if isinstance(raw_days, dict) else None
    if not isinstance(today_row, dict):
        today_row = {}
    detail = load_day_detail(today_key)
    return {
        "today": today_key,
        "avg": avg,
        "quote": quote,
        "can_list": can_list,
        "today_stats": {
            "listed": int(today_row.get("n_listed") or len(detail.get("listed") or [])),
            "sold": int(today_row.get("n_pair") or len(detail.get("pairs") or [])),
            "profit": int(today_row.get("profit") or 0),
        },
        "today_detail": detail,
        "profit": {
            "as_of": profit_file.get("as_of"),
            "yesterday": yesterday,
            "yesterday_row": yday,
            "days": days,
        },
        "bot": {
            "running": bot.running(),
        },
        "strategy": {
            "list_coins": LIST_COINS,
            "min_profit": MIN_LIST_PROFIT,
            "min_profit_per_coin": MIN_PROFIT_PER_COIN,
            "front_depth": FRONT_DEPTH,
        },
    }


@app.get("/api/logs")
def logs() -> dict:
    return {"running": bot.running(), "lines": list(bot.logs)}


@app.post("/api/bot/start")
def bot_start() -> dict:
    state = bot.start()
    return {"ok": True, "state": state, "running": bot.running()}


@app.post("/api/bot/stop")
def bot_stop() -> dict:
    state = bot.stop()
    return {"ok": True, "state": state, "running": bot.running()}


if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/")
def index():
    page = DIST_DIR / "index.html"
    if page.is_file():
        return FileResponse(page, headers={"Cache-Control": "no-store"})
    return {"ok": True, "hint": "先在 web 目录执行 npm run build"}


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404)
    target = DIST_DIR / full_path
    if target.is_file():
        return FileResponse(target)
    page = DIST_DIR / "index.html"
    if page.is_file():
        return FileResponse(page, headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=404)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8787"))
    uvicorn.run("api:app", host=host, port=port, reload=False)
