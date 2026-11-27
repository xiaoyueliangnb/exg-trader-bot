#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务器控制台：均价、日利润和自动上架进程。监听本机 127.0.0.1，由 1Panel 反代对外。"""

from __future__ import annotations

import hmac
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from db import load_avg_latest, load_day_detail, load_dotenv, load_market_latest, load_profit
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
LOG_DIR = ROOT / "logs"
LOG_LIMIT = 400
CONSOLE_TOKEN = os.environ.get("CONSOLE_TOKEN", "").strip()
BOT_AUTOSTART = os.environ.get("BOT_AUTOSTART", "1").strip() not in ("0", "false", "no", "")
WATCHDOG_DELAY = 30

app = FastAPI(title="jifen console")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_token(request: Request, call_next):
    path = request.url.path
    if CONSOLE_TOKEN and path.startswith("/api/") and path != "/api/auth":
        given = request.headers.get("x-token", "")
        if not hmac.compare_digest(given.encode(), CONSOLE_TOKEN.encode()):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


class BotState:
    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.logs: deque[tuple[int, str]] = deque(maxlen=LOG_LIMIT)
        self.seq = 0
        self.lock = threading.Lock()
        self.wanted = False
        self.started_at: Optional[datetime] = None
        self.restarts = 0
        self.last_exit: Optional[int] = None

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
        if not text:
            return
        text = self._stamp(text)
        with self.lock:
            self.seq += 1
            self.logs.append((self.seq, text))
        try:
            LOG_DIR.mkdir(exist_ok=True)
            with (LOG_DIR / f"bot-{date.today().isoformat()}.log").open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass

    def lines_since(self, since: int) -> tuple[int, list[str], bool]:
        with self.lock:
            items = list(self.logs)
            seq = self.seq
        if not items or since <= 0 or since < items[0][0] - 1 or since > seq:
            return seq, [t for _, t in items], True
        return seq, [t for s, t in items if s > since], False

    def start(self) -> str:
        with self.lock:
            self.wanted = True
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
            self.started_at = datetime.now()
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        self.append("控制台：已启动 --auto（间隔按时段）")
        return "started"

    def stop(self) -> str:
        with self.lock:
            self.wanted = False
            proc = self.proc
            self.proc = None
        if proc is None or proc.poll() is not None:
            return "idle"
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.append("控制台：已停止自动上架")
        return "stopped"

    def _pump(self, proc: subprocess.Popen) -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            self.append(line)
        code = proc.wait()
        self.last_exit = code
        self.append(f"控制台：进程退出 code={code}")
        if self.wanted and self.proc is proc:
            self.append(f"控制台：非手动停止，{WATCHDOG_DELAY} 秒后自动拉起")
            threading.Timer(WATCHDOG_DELAY, self._revive, args=(proc,)).start()

    def _revive(self, dead: subprocess.Popen) -> None:
        if self.wanted and self.proc is dead:
            self.restarts += 1
            self.start()

    def phase(self) -> dict:
        """从最后一行日志推断当前在干什么、下一轮几点。"""
        if not self.running():
            return {"state": "stopped", "label": "未运行", "next_at": None}
        with self.lock:
            last = self.logs[-1][1] if self.logs else ""
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)\]", last)
        stamp = None
        if m:
            now = datetime.now()
            stamp = now.replace(hour=int(m[1]), minute=int(m[2]), second=int(m[3]), microsecond=0)
            if stamp > now + timedelta(minutes=1):
                stamp -= timedelta(days=1)
        wait = None
        if (p := re.search(r"暂停 (\d+) 分钟", last)):
            state, label, wait = "paused", "验证码暂停", int(p[1]) * 60
        elif (p := re.search(r"(\d+) 秒（.*?）后重新登录", last)):
            state, label, wait = "waiting", "等待下一轮", int(p[1])
        elif (p := re.search(r"^\[[\d:]+\] (.*?)，等待 (\d+) 秒", last)):
            state, wait = "waiting", int(p[2])
            label = "商店冷却" if "冷却" in p[1] else "等待中"
        elif (p := re.search(r"(\d+) 秒后到 0 点", last)):
            state, label, wait = "waiting", "等 0 点结算", int(p[1])
        elif (p := re.search(r"(\d+) 秒后", last)):
            state, label, wait = "retry", "等待重连", int(p[1])
        else:
            state, label = "working", "扫描 / 上架中"
        next_at = (stamp + timedelta(seconds=wait)).isoformat() if stamp and wait else None
        return {"state": state, "label": label, "next_at": next_at}


bot = BotState()


@app.on_event("startup")
def autostart() -> None:
    if BOT_AUTOSTART:
        bot.start()


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
        "market": load_market_latest(),
        "bot": {
            "running": bot.running(),
            "started_at": bot.started_at.isoformat() if bot.started_at else None,
            "restarts": bot.restarts,
            "last_exit": bot.last_exit,
            "autostart": BOT_AUTOSTART,
            **bot.phase(),
        },
        "strategy": {
            "list_coins": LIST_COINS,
            "min_profit": MIN_LIST_PROFIT,
            "min_profit_per_coin": MIN_PROFIT_PER_COIN,
            "front_depth": FRONT_DEPTH,
        },
    }


@app.get("/api/auth")
def auth(request: Request) -> dict:
    """前端探测是否需要口令、口令是否正确。"""
    given = request.headers.get("x-token", "")
    ok = not CONSOLE_TOKEN or hmac.compare_digest(given.encode(), CONSOLE_TOKEN.encode())
    return {"required": bool(CONSOLE_TOKEN), "ok": ok}


@app.get("/api/logs")
def logs(since: int = 0) -> dict:
    seq, lines, reset = bot.lines_since(since)
    return {"running": bot.running(), "seq": seq, "reset": reset, "lines": lines}


_analysis_cache: dict[int, tuple[float, dict]] = {}


@app.get("/api/analysis")
def analysis(days: int = 14) -> dict:
    from analyze_market import NoDatabase, analyze

    days = max(1, min(days, 365))
    hit = _analysis_cache.get(days)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        data = analyze(days)
    except NoDatabase as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    _analysis_cache[days] = (time.monotonic(), data)
    return data


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
