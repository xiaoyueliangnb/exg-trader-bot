#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
只读扫描交易市场：拉「买交易币」「买积分」菜单，打印盘口与理论利润，不下单。

用法：
  python scan.py --har capture/list.darkrp.cn.har
  python scan.py                 # 读 .env 后连真实 WebSocket，只扫
  python scan.py --list          # 按今日 5 日均上架预演；均价每天只拉一次走势图
  python scan.py --list --execute  # 真正上架，每轮结束询问是否继续
  python scan.py --auto            # 无人值守循环上架（有货就挂，没货等待）
  python scan.py --auto --wait 60  # 自动模式两轮间隔 60 秒
  python scan.py --list --refresh-avg  # 强制重拉走势图并覆盖今日缓存
  python scan.py --loop 5        # 循环扫描；临近 0 点会改去结算昨天利润
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import random
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Optional

from db import (
    AVG_CACHE_PATH,
    PROFIT_CACHE_PATH,
    bump_today_listed,
    load_daily_avg,
    load_dotenv,
    save_daily_avg,
    save_day_detail,
    save_day_profit,
    save_yesterday_profit,
    today_str,
)
from jifen import (
    LIST_COINS,
    MIN_LIST_PROFIT,
    listing_fee_coins,
    listing_fee_points,
    listing_quotes_competitive,
    listing_quotes_from_avg,
    vs_avg,
)

ROOT = Path(__file__).resolve().parent
SHOP_COOLDOWN_SEC = (10 * 60, 20 * 60)
CAPTCHA_PAUSE_SEC = 10 * 60
CAPTCHA_OCR_MAX_TRIES = 3
LIST_GAP_SEC = (60, 3 * 60)
MENU_OPEN_SEC = (1.0, 3.0)
# SCAN_VERBOSE=1 时打印协议噪声（忽略帧 / 跳过菜单 / 菜单延迟等）
LOG_VERBOSE = os.environ.get("SCAN_VERBOSE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


class _TimestampStream:
    """给每一行 stdout/stderr 加上 [HH:MM:SS] 前缀。"""

    def __init__(self, stream) -> None:
        self._stream = stream
        self._buf = ""

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        if not data:
            return 0
        self._buf += data
        n = 0
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            # 已有时间戳的行不再重复加（如控制台消息、stderr 已戳）
            if len(line) >= 10 and line[0] == "[" and line[9] == "]":
                stamped = line + "\n"
            else:
                stamped = f"[{datetime.now().strftime('%H:%M:%S')}] {line}\n"
            self._stream.write(stamped)
            n += len(stamped)
        return n

    def flush(self) -> None:
        if self._buf:
            line = self._buf
            self._buf = ""
            if len(line) >= 10 and line[0] == "[" and line[9] == "]":
                self._stream.write(line)
            else:
                self._stream.write(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {line}"
                )
        self._stream.flush()

    def reconfigure(self, *args, **kwargs):
        fn = getattr(self._stream, "reconfigure", None)
        if fn is not None:
            return fn(*args, **kwargs)
        return None

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def install_timestamp_logs() -> None:
    if not isinstance(sys.stdout, _TimestampStream):
        sys.stdout = _TimestampStream(sys.stdout)  # type: ignore[assignment]
    if not isinstance(sys.stderr, _TimestampStream):
        sys.stderr = _TimestampStream(sys.stderr)  # type: ignore[assignment]


def vlog(msg: str) -> None:
    if LOG_VERBOSE:
        print(msg)
BUY_COIN_PATH = ["积分商城", "交易市场", "买交易币"]
BUY_POINT_PATH = ["积分商城", "交易市场", "买积分"]
MARKET_PATH = ["积分商城", "交易市场"]
LIST_HUB_PATH = ["积分商城", "交易市场", "上架我的"]
HISTORY_PATH = ["积分商城", "交易市场", "我的上架历史"]
SELL_COIN_PATH = ["积分商城", "交易市场", "卖交易币"]
SELL_POINT_PATH = ["积分商城", "交易市场", "卖积分"]
CONFIRM_CLICK = ["积分商城", "交易市场", "确认上架"]
KIND_BUY_POINTS = "1"  # 用交易币买积分
KIND_BUY_COINS = "2"  # 用积分买交易币

OPEN_SELL_COIN_RE = re.compile(r"(\d+)积分 买 (\d+)个币\s+\((\d+)\)")
OPEN_SELL_POINT_RE = re.compile(r"(\d+)币 买 (\d+)积分\s+\((\d+)\)")
HIST_SELL_COIN_RE = re.compile(
    r"\[(\d+)\]\s*(\d+)个交易币\s*标价：\s*(\d+)积分", re.S
)
HIST_SELL_POINT_RE = re.compile(
    r"\[(\d+)\]\s*(\d+)积分\s*标价：\s*(\d+)交易币", re.S
)
HIST_OPEN_ITEM_RE = re.compile(r"\[(\d+)\]")
HIST_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")

BALANCE_RE = re.compile(
    r"你的积分：\s*(-?\d+)\s*你的交易币：\s*(-?\d+)",
    re.S,
)


class CaptchaRequired(RuntimeError):
    pass


class ProtocolError(RuntimeError):
    pass


class ShopCooldown(ProtocolError):
    pass


class LogsNotReady(RuntimeError):
    pass


class ConnectionLost(ProtocolError):
    """WebSocket 被对端踢掉或本地已关闭。"""


def _is_ws_closed(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name.startswith("ConnectionClosed"):
        return True
    try:
        from websockets.exceptions import ConnectionClosed

        return isinstance(exc, ConnectionClosed)
    except Exception:
        return False


@dataclass
class Lot:
    kind: str
    coins: int
    points: int
    text: str
    cmd: list[str]

    @property
    def rate(self) -> float:
        if self.coins <= 0:
            return 0.0
        return self.points / self.coins


@dataclass
class PricePoint:
    time_str: str
    price: float
    time: str = ""


@dataclass
class ChartStats:
    """走势图：WS 只给成交序列，5 日均 / 10 笔均按页面 JS 同样规则现算。"""

    chart_type: Optional[int] = None
    unit: str = "积分/交易币"
    by_dates: list[PricePoint] = field(default_factory=list)
    by_records: list[PricePoint] = field(default_factory=list)
    text: str = ""

    def avg_first(self, points: list[PricePoint], n: int) -> tuple[Optional[float], int]:
        take = points[:n]
        if not take:
            return None, 0
        return sum(p.price for p in take) / len(take), len(take)

    @property
    def avg_5d(self) -> tuple[Optional[float], int]:
        return self.avg_first(self.by_dates, 5)

    @property
    def avg_10trades(self) -> tuple[Optional[float], int]:
        return self.avg_first(self.by_records, 10)


@dataclass
class MyListing:
    listing_id: str
    kind: str  # sell_coin | sell_points | item
    coins: int
    points: int
    text: str
    open: bool = True
    when: str = ""

    @property
    def rate(self) -> float:
        if self.coins <= 0:
            return 0.0
        return self.points / self.coins

    @property
    def day(self) -> str:
        if self.when:
            return self.when[:10]
        m = HIST_TIME_RE.search(self.text)
        return m.group(1)[:10] if m else ""


@dataclass
class Snapshot:
    money: Optional[int] = None
    coin: Optional[int] = None
    buy_coins: list[Lot] = field(default_factory=list)
    buy_points: list[Lot] = field(default_factory=list)
    buy_coin_chart: Optional[ChartStats] = None
    buy_point_chart: Optional[ChartStats] = None
    my_open: list[MyListing] = field(default_factory=list)
    my_sold: list[MyListing] = field(default_factory=list)
    want_note: str = ""
    avg_cached: bool = False


async def sleep_random(bounds: tuple[int, int], why: str) -> int:
    lo, hi = bounds
    sec = random.randint(lo, hi)
    mins = sec / 60
    if mins >= 1:
        print(f"{why}，等待 {sec} 秒（约 {mins:.1f} 分钟）")
    else:
        print(f"{why}，等待 {sec} 秒")
    await asyncio.sleep(sec)
    return sec


async def reconnect(client: "MenuClient", why: str = "重新连接") -> None:
    """握手/网络失败不退出，短等后一直重试直到连上。"""
    attempt = 0
    while True:
        attempt += 1
        try:
            await client.close()
            await client.connect()
            if attempt > 1:
                print(f"{why}成功（第 {attempt} 次）")
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            wait = min(30 + attempt * 15, 180)
            wait = random.randint(max(15, wait - 15), wait)
            print(f"{why}失败：{exc}，{wait} 秒后再试（第 {attempt} 次）")
            await asyncio.sleep(wait)


async def sleep_before_menu(label: str) -> float:
    sec = random.uniform(*MENU_OPEN_SEC)
    vlog(f"菜单延迟 {sec:.1f}s：{label}")
    await asyncio.sleep(sec)
    return sec


def check_shop_cooldown(text: str) -> None:
    if "冷却" in str(text or ""):
        raise ShopCooldown(str(text).strip() or "商店冷却")


def check_captcha_busy(text: str) -> None:
    """验证码点得太勤时服务器会要求等一分钟，这里直接停 10 分钟。"""
    raw = str(text or "")
    if "验证码" in raw and "频繁" in raw:
        raise CaptchaRequired(raw.strip() or "验证码使用太频繁")


def captcha_answer_rejected(text: str) -> bool:
    raw = str(text or "")
    if "验证码" not in raw or "频繁" in raw:
        return False
    return any(k in raw for k in ("错误", "不对", "有误", "不正确", "失败"))


def archive_wrong_captcha(data: bytes, guess: str) -> Path:
    """把没通过的验证码图片留在 captcha_wrong/，文件名带时间和识别结果。

    人工标注时改名为：时间_ocr猜__正确答案.png（双下划线后是正解）。
    """
    folder = ROOT / "captcha_wrong"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in (guess or "") if c.isalnum()).lower() or "invalid"
    path = folder / f"{stamp}_{safe}.png"
    n = 1
    while path.exists():
        path = folder / f"{stamp}_{safe}_{n}.png"
        n += 1
    path.write_bytes(data)
    print(f"验证码未通过，已保留图片 {path.name}（标正解请改成 …_{safe}__正确答案.png）")
    return path


def archive_ok_captcha(data: bytes, label: str) -> Path:
    """提交成功的验证码留下作训练集，文件名里的标签即正确答案。"""
    folder = ROOT / "captcha_ok"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in (label or "") if c.isalnum()).lower() or "ok"
    path = folder / f"{stamp}_{safe}.png"
    n = 1
    while path.exists():
        path = folder / f"{stamp}_{safe}_{n}.png"
        n += 1
    path.write_bytes(data)
    print(f"验证码通过，已留作训练样本 {path.name}")
    return path


def seconds_until_midnight(now: Optional[datetime] = None) -> float:
    now = now or datetime.now()
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return max((nxt - now).total_seconds(), 0.0) + 1.0


def pair_sold_trades(sold: list[MyListing]) -> list[dict]:
    """卖积分先入队，卖交易币按时间 FIFO 配对。自己赎回不参与。"""
    rows = [
        x
        for x in sold
        if x.kind in ("sell_coin", "sell_points") and "买家" in x.text
    ]
    rows.sort(key=lambda x: (x.when or "", x.listing_id))
    inv: list[dict] = []
    pairs: list[dict] = []
    for x in rows:
        if x.kind == "sell_points":
            inv.append(
                {
                    "id": x.listing_id,
                    "coins": x.coins,
                    "points": x.points,
                    "fee": listing_fee_points(x.points),
                    "when": x.when,
                }
            )
            continue
        left_c = x.coins
        left_p = x.points
        while left_c > 0 and inv:
            lot = inv[0]
            take = min(left_c, lot["coins"])
            if take == lot["coins"]:
                cost_p, cost_f = lot["points"], lot["fee"]
            else:
                cost_p = lot["points"] * take // lot["coins"]
                cost_f = lot["fee"] * take // lot["coins"]
            earn = left_p if take == left_c else left_p * take // left_c
            fee_c = listing_fee_coins(take)
            pairs.append(
                {
                    "coins": take,
                    "earn": earn,
                    "cost": cost_p,
                    "fee_p": cost_f,
                    "fee_c": fee_c,
                    "profit": earn - cost_p - cost_f - fee_c,
                    "coin_id": x.listing_id,
                    "pt_id": lot["id"],
                    "coin_when": x.when,
                    "pt_when": lot["when"],
                }
            )
            left_c -= take
            left_p -= earn
            if take == lot["coins"]:
                inv.pop(0)
            else:
                lot["coins"] -= take
                lot["points"] -= cost_p
                lot["fee"] -= cost_f
    return pairs


def day_history_pnl(sold: list[MyListing], day: date) -> dict:
    """当天完成配对的利润：每一对 = 卖币收款 − 对应卖积分挂出 − 两边上架费。"""
    want = day.isoformat()
    n_redeem = redeem_fee = 0
    for x in sold:
        if x.day != want or "自己赎回" not in x.text:
            continue
        n_redeem += 1
        if x.kind == "sell_coin":
            redeem_fee += listing_fee_coins(x.coins)
        elif x.kind == "sell_points":
            redeem_fee += listing_fee_points(x.points)
    day_pairs = [
        p for p in pair_sold_trades(sold) if str(p.get("coin_when") or "")[:10] == want
    ]
    n_pair = len(day_pairs)
    coin_n = sum(p["coins"] for p in day_pairs)
    coin_pts = sum(p["earn"] for p in day_pairs)
    pt_pts = sum(p["cost"] for p in day_pairs)
    fee_c = sum(p["fee_c"] for p in day_pairs)
    fee_p = sum(p["fee_p"] for p in day_pairs)
    return {
        "date": want,
        "n_coin": n_pair,
        "n_pt": n_pair,
        "n_pair": n_pair,
        "n_redeem": n_redeem,
        "coin_n": coin_n,
        "coin_pts": coin_pts,
        "fee_c": fee_c,
        "pt_n": coin_n,
        "pt_pts": pt_pts,
        "fee_p": fee_p,
        "redeem_fee": redeem_fee,
        "net_coin": 0,
        "profit": coin_pts - pt_pts - fee_c - fee_p,
    }


def print_day_pnl(pnl: dict, title: str) -> None:
    print(f"\n--- {title} ---")
    print(
        f"卖交易币 {pnl['n_coin']} 笔 / {pnl['coin_n']} 币，收款 {pnl['coin_pts']}，"
        f"上架费 {pnl['fee_c']}"
    )
    print(
        f"卖积分 {pnl['n_pt']} 笔 / 收回 {pnl['pt_n']} 币，挂出 {pnl['pt_pts']}，"
        f"上架费 {pnl['fee_p']}"
    )
    print(
        f"配对 {pnl.get('n_pair', pnl['n_coin'])} 对，利润 {pnl['profit']}"
        f"（每对：卖币收款 − 对应卖积分挂出 − 两边上架费）"
    )
    if pnl["n_redeem"]:
        print(
            f"另有自己赎回 {pnl['n_redeem']} 笔，手续费 {pnl['redeem_fee']} 不退，未计入利润"
        )


def listing_row(x: MyListing) -> dict:
    if x.kind == "sell_coin":
        side = "卖交易币"
    elif x.kind == "sell_points":
        side = "卖积分"
    else:
        side = "物品"
    if x.open:
        status = "在售"
    elif "自己赎回" in x.text:
        status = "赎回"
    elif "买家" in x.text:
        status = "成交"
    else:
        status = "历史"
    return {
        "id": x.listing_id,
        "kind": x.kind,
        "side": side,
        "coins": x.coins,
        "points": x.points,
        "rate": round(x.rate) if x.coins else None,
        "open": x.open,
        "status": status,
        "when": x.when,
        "text": x.text[:240],
    }


def today_detail_payload(opened: list[MyListing], sold: list[MyListing]) -> dict:
    want = today_str()
    kinds = ("sell_coin", "sell_points")
    listed = []
    for x in (*opened, *sold):
        if x.kind not in kinds:
            continue
        # 只认带「今天」时间戳的记录；在售但无时间的旧单不算今日。
        if x.day == want:
            listed.append(listing_row(x))
    listed.sort(key=lambda r: str(r.get("when") or ""), reverse=True)
    pairs = []
    for p in pair_sold_trades(sold):
        if str(p.get("coin_when") or "")[:10] != want:
            continue
        earn = int(p["earn"])
        cost = int(p["cost"])
        fee_p = int(p["fee_p"])
        fee_c = int(p["fee_c"])
        profit = int(p["profit"])
        pairs.append(
            {
                "coins": int(p["coins"]),
                "earn": earn,
                "cost": cost,
                "fee_c": fee_c,
                "fee_p": fee_p,
                "profit": profit,
                "coin_id": p.get("coin_id"),
                "pt_id": p.get("pt_id"),
                "coin_when": p.get("coin_when"),
                "pt_when": p.get("pt_when"),
                "formula": f"{earn} − {cost} − {fee_p} − {fee_c} = {profit}",
            }
        )
    redeem = []
    for x in sold:
        if x.kind not in kinds or x.day != want or "自己赎回" not in x.text:
            continue
        redeem.append(listing_row(x))
    return {"date": want, "listed": listed, "pairs": pairs, "redeem": redeem}


def today_listing_stats(opened: list[MyListing], sold: list[MyListing]) -> dict:
    want = today_str()
    kinds = ("sell_coin", "sell_points")
    listed = [
        x for x in (*opened, *sold) if x.kind in kinds and x.day == want
    ]
    pnl = day_history_pnl(sold, date.today())
    pnl["n_listed"] = len(listed)
    return pnl


def save_today_listing_stats(opened: list[MyListing], sold: list[MyListing]) -> dict:
    pnl = today_listing_stats(opened, sold)
    save_day_profit(pnl)
    save_day_detail(today_detail_payload(opened, sold))
    return pnl


def settle_yesterday(sold: list[MyListing], *, midnight: bool = False) -> dict:
    yday = date.today() - timedelta(days=1)
    pnl = day_history_pnl(sold, yday)
    save_yesterday_profit(pnl)
    title = f"昨天利润 {yday.isoformat()}"
    if midnight:
        title = f"0 点结算 · {title}"
    print_day_pnl(pnl, title)
    print(f"已写入利润（MySQL / {PROFIT_CACHE_PATH.name}）")
    return pnl


PEAK_WAIT_SEC = 10 * 60
OFFPEAK_WAIT_SEC = 30 * 60


def auto_round_wait(now: Optional[datetime] = None) -> tuple[int, str]:
    """按北京时间返回下一轮间隔（秒, 说明）。高峰 10 分钟，平峰 30 分钟。

    工作日：中午 12–14、晚上 18–24 为高峰，其余半小时。
    周末：10 点到 24 点都算高峰（上午、下午、晚上都有人），0–10 点半小时。
    """
    now = now or datetime.now()
    hour = now.hour
    weekend = now.weekday() >= 5
    if weekend:
        bands = (
            (0, 10, False, "周末深夜"),
            (10, 12, True, "周末上午"),
            (12, 14, True, "周末中午"),
            (14, 18, True, "周末下午"),
            (18, 24, True, "周末晚上"),
        )
    else:
        bands = (
            (0, 8, False, "工作日深夜"),
            (8, 12, False, "工作日上午"),
            (12, 14, True, "工作日中午"),
            (14, 18, False, "工作日下午"),
            (18, 24, True, "工作日晚上"),
        )
    for start, end, peak, name in bands:
        if start <= hour < end:
            sec = PEAK_WAIT_SEC if peak else OFFPEAK_WAIT_SEC
            return sec, f"{name}·{'高峰' if peak else '平峰'}"
    return OFFPEAK_WAIT_SEC, "平峰"


def recheck_soon(q: Optional[dict]) -> bool:
    """有一侧排不进第一、但两边成交利润仍够时，10 分钟后再看盘口。"""
    if not q or q.get("profit", 0) < MIN_LIST_PROFIT:
        return False
    return bool(q.get("behind_coins") or q.get("behind_points"))


def need_refill(q: Optional[dict]) -> bool:
    """前排不足 2 份、利润仍够时，2–3 分钟后再补一份。"""
    if not q or q.get("profit", 0) < MIN_LIST_PROFIT:
        return False
    return bool(q.get("depth_short_coins") or q.get("depth_short_points"))


async def wait_auto_round(
    client: MenuClient,
    wait: float,
    *,
    idle: bool,
    reason: str = "",
    soon: bool = False,
    refill: bool = False,
) -> bool:
    """先关 WebSocket，等到点再重连。间隔按当前时段，不使用控制台里的固定秒数。"""
    del wait
    wait, slot = auto_round_wait()
    if refill:
        wait = random.randint(2 * 60, 3 * 60)
        slot = f"{slot}，前排不足2份，约 {wait / 60:.0f} 分钟后再补"
    elif soon and wait > PEAK_WAIT_SEC:
        wait = PEAK_WAIT_SEC
        slot = f"{slot}，有一侧落后改 {PEAK_WAIT_SEC // 60} 分钟"
    until_mid = seconds_until_midnight()
    reason = reason or ("本轮已提交" if not idle else "本轮未上架")
    hit_midnight = until_mid <= wait
    sleep_for = until_mid if hit_midnight else wait
    print(
        f"{reason}，{slot}，关闭连接，{sleep_for:.0f} 秒"
        f"（{sleep_for / 60:.0f} 分钟）后重新登录（Ctrl+C 停止）"
    )
    await client.close()
    await asyncio.sleep(sleep_for)
    print("时间到，重新连接并走登录流程")
    await reconnect(client, "重新连接")
    return hit_midnight


def charts_from_daily_avg(cache: dict) -> tuple[ChartStats, ChartStats]:
    day = str(cache.get("date") or today_str())
    coin = ChartStats(
        chart_type=2,
        by_dates=[PricePoint(time_str=day, price=float(cache["coin_avg"]))]
        * max(int(cache.get("n_coin") or 5), 1),
        text="cached",
    )
    point = ChartStats(
        chart_type=1,
        by_dates=[PricePoint(time_str=day, price=float(cache["point_avg"]))]
        * max(int(cache.get("n_point") or 5), 1),
        text="cached",
    )
    return coin, point


def decode_content(content: Any) -> Any:
    if not isinstance(content, str) or not content:
        return content
    text = content.strip()
    if text[:1] in "{[":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return content
    return content


def iter_menu_items(menu: dict) -> list[dict]:
    return list(menu.get("Items") or [])


def parse_scriptdiv_balance(menu: dict) -> tuple[Optional[int], Optional[int]]:
    for item in iter_menu_items(menu):
        if item.get("Type") != "scriptdiv":
            continue
        cmd = item.get("Cmd") or []
        if len(cmd) < 2:
            continue
        payload = decode_content(cmd[1])
        if not isinstance(payload, dict):
            continue
        if "Money" not in payload and "Coin" not in payload:
            continue
        try:
            money = int(payload.get("Money"))
            coin = int(payload.get("Coin"))
        except (TypeError, ValueError):
            continue
        return money, coin
    return None, None


def parse_balance(menu: dict) -> tuple[Optional[int], Optional[int]]:
    for item in iter_menu_items(menu):
        text = str(item.get("Text") or "")
        m = BALANCE_RE.search(text.replace("\r", ""))
        if m:
            return int(m.group(1)), int(m.group(2))
    return parse_scriptdiv_balance(menu)


def balance_known(money: Optional[int], coin: Optional[int]) -> bool:
    return money is not None and coin is not None and money >= 0 and coin >= 0


def parse_ask_cmd(cmd: list) -> Optional[Lot]:
    if len(cmd) < 7 or cmd[2] != "询问购买":
        return None
    kind = str(cmd[3])
    try:
        if kind == KIND_BUY_COINS:
            coins = int(cmd[4])
            points = int(cmd[5])
        elif kind == KIND_BUY_POINTS:
            points = int(cmd[4])
            coins = int(cmd[6])
        else:
            return None
    except (TypeError, ValueError):
        return None
    if coins <= 0 or points <= 0:
        return None
    return Lot(kind=kind, coins=coins, points=points, text="", cmd=[str(x) for x in cmd])


def parse_price_points(raw: Any) -> list[PricePoint]:
    points: list[PricePoint] = []
    if not isinstance(raw, list):
        return points
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            price = float(item.get("Price"))
        except (TypeError, ValueError):
            continue
        points.append(
            PricePoint(
                time_str=str(item.get("TimeStr") or ""),
                price=price,
                time=str(item.get("Time") or ""),
            )
        )
    return points


def parse_chart(menu: dict) -> Optional[ChartStats]:
    for item in iter_menu_items(menu):
        if item.get("Type") != "scriptdiv":
            continue
        cmd = item.get("Cmd") or []
        if len(cmd) < 2 or "market_chart" not in str(cmd[0]):
            continue
        payload = decode_content(cmd[1])
        if not isinstance(payload, dict):
            continue
        chart_type = payload.get("Type")
        try:
            chart_type = int(chart_type)
        except (TypeError, ValueError):
            chart_type = None
        if chart_type == 2:
            by_dates = parse_price_points(payload.get("MoneyByDates"))
            by_records = parse_price_points(payload.get("MoneyByRecords"))
        elif chart_type == 1:
            by_dates = parse_price_points(payload.get("CoinByDates"))
            by_records = parse_price_points(payload.get("CoinByRecords"))
        else:
            by_dates = parse_price_points(payload.get("CoinByDates") or payload.get("MoneyByDates"))
            by_records = parse_price_points(payload.get("CoinByRecords") or payload.get("MoneyByRecords"))
        return ChartStats(
            chart_type=chart_type,
            by_dates=by_dates,
            by_records=by_records,
            text=str(payload.get("Text") or ""),
        )
    return None


def parse_lots(menu: dict) -> list[Lot]:
    lots: list[Lot] = []
    for item in iter_menu_items(menu):
        if item.get("Type") != "button":
            continue
        cmd = item.get("Cmd") or []
        lot = parse_ask_cmd(cmd)
        if lot is None:
            continue
        lot.text = str(item.get("Text") or "")
        lots.append(lot)
    return lots


def parse_listing_history(menu: dict) -> tuple[list[MyListing], list[MyListing]]:
    """离线页：button + 询问赎回 = 正在上架；带买家/自己赎回的 p = 历史成交。"""
    opened: list[MyListing] = []
    sold: list[MyListing] = []

    def from_text(text: str, listing_id: str, is_open: bool) -> Optional[MyListing]:
        compact = text.replace("\r", "")
        tm = HIST_TIME_RE.search(compact)
        when = tm.group(1) if tm else ""
        m = HIST_SELL_COIN_RE.search(compact)
        if m:
            return MyListing(
                listing_id=m.group(1),
                kind="sell_coin",
                coins=int(m.group(2)),
                points=int(m.group(3)),
                text=text.replace("\n", " / "),
                open=is_open,
                when=when,
            )
        m = HIST_SELL_POINT_RE.search(compact)
        if m:
            return MyListing(
                listing_id=m.group(1),
                kind="sell_points",
                coins=int(m.group(3)),
                points=int(m.group(2)),
                text=text.replace("\n", " / "),
                open=is_open,
                when=when,
            )
        m = OPEN_SELL_COIN_RE.search(text)
        if m:
            return MyListing(
                listing_id=listing_id,
                kind="sell_coin",
                coins=int(m.group(2)),
                points=int(m.group(1)),
                text=text,
                open=is_open,
                when=when,
            )
        m = OPEN_SELL_POINT_RE.search(text)
        if m:
            return MyListing(
                listing_id=listing_id,
                kind="sell_points",
                coins=int(m.group(1)),
                points=int(m.group(2)),
                text=text,
                open=is_open,
                when=when,
            )
        if is_open:
            hid = listing_id
            m = HIST_OPEN_ITEM_RE.search(text)
            if m:
                hid = m.group(1)
            return MyListing(
                listing_id=hid,
                kind="item",
                coins=0,
                points=0,
                text=text.replace("\n", " / "),
                open=True,
                when=when,
            )
        return None

    for item in iter_menu_items(menu):
        text = str(item.get("Text") or "")
        typ = str(item.get("Type") or "")
        cmd = [str(x) for x in (item.get("Cmd") or [])]
        listing_id = cmd[-1] if cmd else ""
        if typ == "button" and "询问赎回" in cmd:
            row = from_text(text, listing_id, True)
            if row:
                opened.append(row)
            continue
        if typ == "p" and ("买家" in text or "自己赎回" in text or "标价：" in text):
            row = from_text(text, listing_id, False)
            if row:
                sold.append(row)
    return opened, sold


def extract_menus_from_har(har_path: Path) -> Snapshot:
    har = json.loads(har_path.read_text(encoding="utf-8"))
    snap = Snapshot()
    for entry in har.get("log", {}).get("entries", []):
        for msg in entry.get("_webSocketMessages") or []:
            if msg.get("type") != "receive":
                continue
            data = msg.get("data") or ""
            if not data.startswith("{"):
                continue
            try:
                envelope = json.loads(data)
            except json.JSONDecodeError:
                continue
            if envelope.get("Title") != "DisplayMenu":
                continue
            menu = decode_content(envelope.get("Content"))
            if not isinstance(menu, dict):
                continue
            money, coin = parse_balance(menu)
            if money is not None:
                snap.money = money
                snap.coin = coin
            title = menu.get("Title")
            lots = parse_lots(menu)
            if title == "买交易币":
                snap.buy_coins = lots
                chart = parse_chart(menu)
                if chart is not None:
                    snap.buy_coin_chart = chart
            elif title == "买积分":
                snap.buy_points = lots
                chart = parse_chart(menu)
                if chart is not None:
                    snap.buy_point_chart = chart
            elif title == "我的上架历史":
                snap.my_open, snap.my_sold = parse_listing_history(menu)
    return snap


def best_buy_coins(lots: list[Lot], coins: int = LIST_COINS) -> Optional[Lot]:
    """买交易币盘口最优：只比指定币量档（默认 10 币）。"""
    priced = [x for x in lots if x.kind == KIND_BUY_COINS and x.coins == coins]
    if not priced:
        return None
    return min(priced, key=lambda x: (x.rate, x.points))


def best_sell_coins(lots: list[Lot], coins: int = LIST_COINS) -> Optional[Lot]:
    """买积分盘口最优：只比指定币量档（默认 10 币）。"""
    priced = [x for x in lots if x.kind == KIND_BUY_POINTS and x.coins == coins]
    if not priced:
        return None
    return max(priced, key=lambda x: (x.rate, x.points))


def greedy_roundtrip(buy_lots: list[Lot], sell_lots: list[Lot]) -> tuple[int, int, int]:
    """按单价贪心：尽量买最便宜的币，再按最高积分/币卖掉。返回 (币数, 花费积分, 收回积分)。"""
    buys = sorted(
        [x for x in buy_lots if x.kind == KIND_BUY_COINS],
        key=lambda x: x.rate,
    )
    sells = sorted(
        [x for x in sell_lots if x.kind == KIND_BUY_POINTS],
        key=lambda x: x.rate,
        reverse=True,
    )
    if not buys or not sells:
        return 0, 0, 0

    buy_bag: list[tuple[int, int]] = []  # (coins remaining, points per this lot remaining proportional)
    spent = 0
    got_coins = 0
    for lot in buys:
        buy_bag.append([lot.coins, lot.points])
        spent += lot.points
        got_coins += lot.coins

    remain = got_coins
    earned = 0
    sold = 0
    for lot in sells:
        take = min(remain, lot.coins)
        if take <= 0:
            continue
        earned += int(round(lot.rate * take))
        sold += take
        remain -= take
        if remain <= 0:
            break

    unused_coins = remain
    unused_spend = 0
    leftover = unused_coins
    for coins, points in reversed(buy_bag):
        if leftover <= 0:
            break
        cut = min(coins, leftover)
        unused_spend += int(round(points * cut / coins)) if coins else 0
        leftover -= cut
    spent -= unused_spend
    return sold, spent, earned


def format_lot(lot: Lot, avg5: Optional[float] = None, *, lower_better: bool = True) -> str:
    base = f"{lot.text or ''}  币={lot.coins} 积分={lot.points} 单价={lot.rate:.2f}"
    if avg5 is None:
        return base
    delta = vs_avg(lot.rate, avg5)
    if abs(delta) < 1e-9:
        tag = "等于5日均"
    elif (delta < 0) == lower_better:
        tag = "优于5日均"
    else:
        tag = "劣于5日均"
    return f"{base}  vs5日均{avg5:.1f} {delta:+.1f} {tag}"


def format_avg(avg: Optional[float], count: int, digits: int = 1) -> str:
    if avg is None:
        return "无数据"
    return f"{avg:.{digits}f}（{count}）"


def print_chart(title: str, chart: Optional[ChartStats], day_n: int = 5) -> None:
    print(f"\n走势图 {title}")
    if chart is None:
        print("  （本页没有 scriptdiv 图表数据）")
        return
    avg5, n5 = chart.avg_5d
    avg10, n10 = chart.avg_10trades
    print(f"  Type={chart.chart_type}  单位={chart.unit}")
    if chart.text == "cached":
        print(f"  （今日缓存 {chart.by_dates[0].time_str if chart.by_dates else ''}）")
        print(f"  最近 5 天平均成交比例： {format_avg(avg5, n5)}")
        return
    print(f"  最近 {n5 or 5} 天平均成交比例： {format_avg(avg5, n5)}")
    print(f"  最近 {n10 or 10} 笔平均成交价： {format_avg(avg10, n10)}")
    days = chart.by_dates[:day_n]
    if days:
        bits = "  ".join(f"{p.time_str}={p.price:g}" for p in days)
        print(f"  日线（新→旧，前 {len(days)} 天）：{bits}")
    recs = chart.by_records[:day_n]
    if recs:
        bits = "  ".join(f"{p.time_str}={p.price:g}" for p in recs)
        print(f"  逐笔（新→旧，前 {len(recs)} 笔）：{bits}")


def print_snapshot(snap: Snapshot, top: int, *, quiet: bool = False) -> None:
    money = "未知" if snap.money is None else snap.money
    coin = "未知" if snap.coin is None else snap.coin
    coin_avg, _ = (snap.buy_coin_chart.avg_5d if snap.buy_coin_chart else (None, 0))
    point_avg, _ = (snap.buy_point_chart.avg_5d if snap.buy_point_chart else (None, 0))
    buys = sorted(snap.buy_coins, key=lambda x: x.rate)
    sells = sorted(snap.buy_points, key=lambda x: x.rate, reverse=True)
    open_coins = [x for x in snap.my_open if x.kind == "sell_coin"]
    open_points = [x for x in snap.my_open if x.kind == "sell_points"]
    open_items = [x for x in snap.my_open if x.kind == "item"]

    settle_yesterday(snap.my_sold, midnight=datetime.now().hour == 0)
    today_pnl = save_today_listing_stats(snap.my_open, snap.my_sold)
    q = quotes_from_snap(snap)

    if quiet:
        # --auto：一行余额 + 一行今日 + 一行定价，不刷盘口明细
        print(
            f"── 扫描 ── 余额 积分={money} 交易币={coin}"
            + (" · 5日均已缓存" if snap.avg_cached else "")
        )
        best_buy = f"{buys[0].rate:.0f}" if buys else "-"
        best_sell = f"{sells[0].rate:.0f}" if sells else "-"
        avg_bits = (
            f"5日均 积分={point_avg:.1f} 币={coin_avg:.1f}"
            if point_avg is not None and coin_avg is not None
            else "5日均 无"
        )
        print(
            f"盘口 买币最低={best_buy} 买积分最高={best_sell} | {avg_bits} | "
            f"在售 {len(snap.my_open)}（币{len(open_coins)}/积分{len(open_points)}"
            f"{f'/物{len(open_items)}' if open_items else ''}）"
        )
        print(
            f"今日 已上={today_pnl.get('n_listed', 0)} "
            f"成交={today_pnl.get('n_pair', 0)} "
            f"利润={today_pnl.get('profit', 0)}"
        )
        if q is None:
            print("定价：缺少盘口与 5 日均")
            return
        print(
            f"定价 卖积分={q['low_unit']}（{q.get('low_note', '')}） "
            f"卖交易币={q['high_unit']}（{q.get('high_note', '')}） "
            f"利润={q['profit']}"
        )
        for x in open_points:
            if abs(x.rate - q["low_unit"]) > 0.5:
                print(f"  现挂卖积分 {x.rate:.0f} ≠ 目标 {q['low_unit']}")
                break
        for x in open_coins:
            if abs(x.rate - q["high_unit"]) > 0.5:
                print(f"  现挂卖交易币 {x.rate:.0f} ≠ 目标 {q['high_unit']}")
                break
        return q

    print("─" * 40)
    print(f"余额  积分={money}  交易币={coin}")
    if snap.avg_cached:
        print("5 日均使用今日缓存，未再打开买积分 / 买交易币走势图。")

    print(
        f"买交易币（锚 5 日均 {format_avg(coin_avg, 5) if coin_avg is not None else '无'}）"
        f"共 {len(buys)} 档，前 {min(top, len(buys))}："
    )
    for lot in buys[:top]:
        print("  " + format_lot(lot, coin_avg, lower_better=True))
    print(
        f"买积分（锚 5 日均 {format_avg(point_avg, 5) if point_avg is not None else '无'}）"
        f"共 {len(sells)} 档，前 {min(top, len(sells))}："
    )
    for lot in sells[:top]:
        print("  " + format_lot(lot, point_avg, lower_better=False))

    print_chart("买交易币", snap.buy_coin_chart)
    print_chart("买积分", snap.buy_point_chart)

    print(
        f"我的上架  在售 {len(snap.my_open)}（币 {len(open_coins)} / 积分 {len(open_points)} / 物品 {len(open_items)}）"
        f"  历史成交 {len(snap.my_sold)}"
    )
    if snap.my_open:
        print("  正在上架：")
        for x in snap.my_open[:12]:
            side = {"sell_coin": "卖交易币", "sell_points": "卖积分"}.get(x.kind, "物品")
            extra = f"  单价={x.rate:.2f}" if x.coins else ""
            print(f"    [{x.listing_id}] {side} {x.text}{extra}")
    if snap.my_sold:
        print("  历史成交（最近 8 笔）：")
        for x in snap.my_sold[:8]:
            side = {"sell_coin": "卖交易币", "sell_points": "卖积分"}.get(x.kind, "物品")
            extra = f"  单价={x.rate:.2f}" if x.coins else ""
            print(f"    [{x.listing_id}] {side} {x.text}{extra}")
    if not snap.my_open and not snap.my_sold:
        print("  （没有读到上架历史）")
    print(
        f"今日已上 {today_pnl.get('n_listed', 0)} 份，"
        f"成交 {today_pnl.get('n_pair', 0)} 份，"
        f"利润 {today_pnl.get('profit', 0)}"
    )

    print("--- 实际上架价（盘口抢排序，无盘口回退 5 日均）---")
    if q is None:
        print("缺少盘口与 5 日均，无法定价。")
        return

    print(f"卖积分：{q['low_unit']} 积分/币（{q.get('low_note', '')}）")
    print(f"卖交易币：{q['high_unit']} 积分/币（{q.get('high_note', '')}）")
    if point_avg is not None and coin_avg is not None:
        print(f"  参考 5 日均：买积分 {point_avg:.1f} / 买交易币 {coin_avg:.1f}")
    print(
        f"表单  卖积分：上架 {q['points_listed']} 、标价 {q['coins']} 币；"
        f"卖交易币：上架 {q['coins']} 币、标价 {q['earned']}"
    )
    print(
        f"手续费 {q['fee_in']}+{q['fee_out']}，两边成交利润 {q['profit']} "
        f"（{q['earned']} - {q['points_listed']} - {q['fee_in']} - {q['fee_out']}）"
    )

    seen_dev = set()
    for x in open_points:
        key = ("sell_points", round(x.rate))
        if abs(x.rate - q["low_unit"]) > 0.5 and key not in seen_dev:
            seen_dev.add(key)
            print(f"  现挂卖积分 {x.rate:.0f} 偏离实际上架价 {q['low_unit']}")
    for x in open_coins:
        key = ("sell_coin", round(x.rate))
        if abs(x.rate - q["high_unit"]) > 0.5 and key not in seen_dev:
            seen_dev.add(key)
            print(f"  现挂卖交易币 {x.rate:.0f} 偏离实际上架价 {q['high_unit']}")
    return q


def quotes_from_snap(snap: Snapshot) -> Optional[dict]:
    coin_avg = point_avg = None
    if snap.buy_coin_chart is not None:
        coin_avg, _ = snap.buy_coin_chart.avg_5d
    if snap.buy_point_chart is not None:
        point_avg, _ = snap.buy_point_chart.avg_5d
    # 抢排序只盯 10 币档，其它份量不参与比价。
    best_coin = best_buy_coins(snap.buy_coins, LIST_COINS)
    best_point = best_sell_coins(snap.buy_points, LIST_COINS)
    market_coin = best_coin.rate if best_coin else None
    market_point = best_point.rate if best_point else None
    my_coin_rates = [
        x.rate
        for x in snap.my_open
        if x.kind == "sell_coin" and x.coins == LIST_COINS
    ]
    my_point_rates = [
        x.rate
        for x in snap.my_open
        if x.kind == "sell_points" and x.coins == LIST_COINS
    ]
    q = listing_quotes_competitive(
        point_avg,
        coin_avg,
        market_point,
        market_coin,
        my_point_rates,
        my_coin_rates,
        LIST_COINS,
    )
    if q is not None:
        return q
    if point_avg is None or coin_avg is None:
        return None
    return listing_quotes_from_avg(point_avg, coin_avg, LIST_COINS)


def print_list_plan(snap: Snapshot, q: dict, side: str) -> list[str]:
    money = snap.money if snap.money is not None else -1
    coin = snap.coin if snap.coin is not None else -1
    remain_money = money
    todo: list[str] = []
    bits: list[str] = [f"利润={q['profit']}"]
    if q["profit"] < MIN_LIST_PROFIT:
        print(f"计划：利润{q['profit']}＜{MIN_LIST_PROFIT}，跳过本轮")
        return []
    if side in ("both", "coins"):
        need_coin = q["coins"]
        need_fee = q["fee_out"]
        if q.get("skip_coins") or q.get("hold_coins"):
            bits.append(f"卖币=跳过({q.get('skip_coins') or '维持'})")
        elif coin < need_coin:
            bits.append("卖币=跳过(币不足)")
            q["depth_short_coins"] = False
            q["skip_coins"] = "币不足"
        elif remain_money < need_fee:
            bits.append("卖币=跳过(积分不够付费)")
            q["depth_short_coins"] = False
            q["skip_coins"] = "积分不够付费"
        else:
            todo.append("coins")
            remain_money -= need_fee
            bits.append(
                f"卖币=提交 {need_coin}币@{q['high_unit']}→{q['earned']}(费{need_fee})"
            )
    if side in ("both", "points"):
        need_pts = q["points_listed"] + q["fee_in"]
        if q.get("skip_points") or q.get("hold_points"):
            bits.append(f"卖积分=跳过({q.get('skip_points') or '维持'})")
        elif remain_money < need_pts:
            bits.append("卖积分=跳过(积分不够)")
            q["depth_short_points"] = False
            q["skip_points"] = "积分不够"
        else:
            todo.append("points")
            bits.append(
                f"卖积分=提交 {q['points_listed']}积分@{q['low_unit']}→{q['coins']}币"
                f"(含费共扣{need_pts})"
            )
    bits.append(f"余额 积分={money} 币={coin}")
    print("计划：" + " | ".join(bits))
    return todo


def no_list_reason(q: Optional[dict]) -> str:
    """本轮没挂新单时的原因，避免一律写成余额不够或库存不够。"""
    if q is None:
        return "没有定价，本轮不上架"
    if q["profit"] < MIN_LIST_PROFIT:
        return f"利润{q['profit']}＜{MIN_LIST_PROFIT}，本轮不上架"
    notes = []
    for key, label in (("skip_coins", "卖币"), ("skip_points", "卖积分")):
        why = str(q.get(key) or "")
        if why:
            notes.append(f"{label}{why}")
    if notes and all("维持" in n for n in notes):
        return "已有目标价，维持现挂"
    if notes:
        return "本轮不上新单：" + "，".join(notes)
    return "余额不够，本轮不上架"


def debit_after_listing(snap: Snapshot, q: dict, todo: list[str]) -> None:
    if "coins" in todo:
        if snap.coin is not None:
            snap.coin -= q["coins"]
        if snap.money is not None:
            snap.money -= q["fee_out"]
    if "points" in todo:
        if snap.money is not None:
            snap.money -= q["points_listed"] + q["fee_in"]


async def ask_continue() -> bool:
    try:
        raw = await asyncio.to_thread(input, "继续上架？[Y/n] ")
    except EOFError:
        return False
    ans = raw.strip().lower()
    return ans in ("", "y", "yes", "是", "继续")


class MenuClient:
    def __init__(self, steam_id: int, password: str, host: str) -> None:
        self.steam_id = steam_id
        self.password = password
        self.host = host
        self._ws = None
        self._recv_lock = asyncio.Lock()
        self.bound_server = ""
        self.menu_path: list[str] = []
        self.pending_path: list[str] = []
        self.last_menu: dict = {}
        self.captcha_tries: int = 0
        self.captcha_image: bytes = b""
        self.captcha_guess: str = ""
        self._cookies = CookieJar()
        self._ssl_http = ssl.create_default_context()

    @property
    def url(self) -> str:
        # 站点已改为 Cookie 会话登录，WS 不再带 id3。
        return f"wss://{self.host}/Client/Ws"

    @property
    def origin(self) -> str:
        return f"https://{self.host}"

    @property
    def user_agent(self) -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

    def _cookie_header(self) -> str:
        return "; ".join(f"{c.name}={c.value}" for c in self._cookies)

    def _http_opener(self) -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ssl_http),
            urllib.request.HTTPCookieProcessor(self._cookies),
        )

    def _http_request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(
            f"{self.origin}{path}",
            data=data,
            method=method,
            headers={
                "User-Agent": self.user_agent,
                "Origin": self.origin,
                "Referer": f"{self.origin}/",
                **(headers or {}),
            },
        )
        try:
            with self._http_opener().open(req, timeout=20) as resp:
                return int(resp.status), resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp is not None else b""
            return int(exc.code), body

    def _account_login_sync(self) -> None:
        """新站：先 /Account/Csrf + /Account/Login 拿 Identity Cookie，再连 WS。"""
        status, raw = self._http_request("GET", "/Account/Csrf")
        csrf = raw.decode("utf-8", errors="replace").strip()
        if status != 200 or not csrf:
            raise ProtocolError(f"获取 CSRF 失败：HTTP {status} {raw[:120]!r}")
        payload = json.dumps(
            {
                "steam": self.steam_id,
                "password": self.password,
                "remember": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        status, raw = self._http_request(
            "POST",
            "/Account/Login",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "RequestVerificationToken": csrf,
            },
        )
        if status != 200:
            text = raw.decode("utf-8", errors="replace").strip()
            raise ProtocolError(f"Account/Login 失败：HTTP {status} {text[:200]}")
        if not any(c.name == ".AspNetCore.Identity.Application" for c in self._cookies):
            raise ProtocolError("Account/Login 成功但未拿到登录 Cookie")

    def envelope(self, title: str, content: Any = "") -> dict:
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        # 抓包里客户端发出的 Server 始终是空字符串；回包上的 cs2ze17 只表示来源。
        return {
            "Player": 0,
            "Server": "",
            "Title": title,
            "Content": content,
        }

    async def connect(self) -> None:
        import websockets

        await asyncio.to_thread(self._account_login_sync)
        headers = {
            "Origin": self.origin,
            "User-Agent": self.user_agent,
            "Cookie": self._cookie_header(),
        }
        # Kestrel 只在 HTTP/1.1 上升级 WebSocket；ALPN 走到 h2 会回 HTTP 200。
        # Origin 只放在 headers 里，勿再传 origin=，重复 Origin 也会被拒。
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.set_alpn_protocols(["http/1.1"])
        kwargs = dict(
            ssl=ssl_ctx,
            ping_interval=None,
            max_size=8 * 1024 * 1024,
            compression=None,
        )
        try:
            self._ws = await websockets.connect(
                self.url, additional_headers=headers, **kwargs
            )
        except TypeError:
            kwargs.pop("compression", None)
            try:
                self._ws = await websockets.connect(
                    self.url, extra_headers=headers, **kwargs
                )
            except TypeError:
                self._ws = await websockets.connect(
                    self.url,
                    extra_headers=headers,
                    ssl=ssl_ctx,
                    ping_interval=None,
                    max_size=8 * 1024 * 1024,
                )
        # 密码已在 HTTP 登录时校验；WS 只等服务端 ok。
        first = await asyncio.wait_for(self._ws.recv(), timeout=15)
        if first != "ok":
            raise ProtocolError(f"登录未通过：{first!r}")
        self.captcha_tries = 0
        self.captcha_image = b""
        self.captcha_guess = ""

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self.bound_server = ""
        self.menu_path = []
        self.pending_path = []
        self.last_menu = {}

    async def send(self, title: str, content: Any = "") -> None:
        if self._ws is None:
            raise ConnectionLost("WebSocket 未连接")
        raw = json.dumps(
            self.envelope(title, content), ensure_ascii=False, separators=(",", ":")
        )
        try:
            await self._ws.send(raw)
        except Exception as exc:
            if _is_ws_closed(exc):
                raise ConnectionLost(f"发送失败，连接已断开：{exc}") from exc
            raise

    async def recv_json(self, timeout: float = 15.0) -> dict:
        if self._ws is None:
            raise ConnectionLost("WebSocket 未连接")
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except Exception as exc:
            if _is_ws_closed(exc):
                raise ConnectionLost(f"接收失败，连接已断开：{exc}") from exc
            raise
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if raw == "ok":
            return {"Title": "ok", "Content": ""}
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"非 JSON 帧：{raw[:200]!r}") from exc
        server = str(msg.get("Server") or "")
        if server:
            self.bound_server = server
        title = (msg.get("Title") or "").lower()
        if title == "captcha":
            return msg
        if title == "msgbox0":
            text = str(msg.get("Content") or "")
            if "密码错误" in text or "还没有设置过密码" in text:
                raise ProtocolError(text)
        return msg

    def _keep_wrong_captcha(self) -> None:
        data = self.captcha_image
        guess = self.captcha_guess
        self.captcha_image = b""
        self.captcha_guess = ""
        if data:
            archive_wrong_captcha(data, guess)

    def _captcha_passed(self) -> None:
        data = self.captcha_image
        label = self.captcha_guess
        self.captcha_image = b""
        self.captcha_guess = ""
        if data and label and label not in ("ocrfail", "invalid"):
            try:
                archive_ok_captcha(data, label)
            except Exception as exc:
                print(f"保存成功验证码样本失败：{exc}")

    def note_captcha_reply(self, text: str) -> None:
        if captcha_answer_rejected(text):
            self._keep_wrong_captcha()

    async def solve_captcha(self, content: str) -> None:
        """存图 → ocr_captcha 识别 → 提交 CaptchaCode；连续失败再抛 CaptchaRequired 暂停。"""
        img = ROOT / "captcha.png"
        try:
            data = base64.b64decode(content)
        except Exception as exc:
            raise CaptchaRequired(f"验证码图片无法保存：{exc}") from exc
        if self.captcha_guess:
            self._keep_wrong_captcha()
        self.captcha_image = data
        img.write_bytes(data)
        print(f"需要验证码，图片已保存：{img}")

        self.captcha_tries += 1
        if self.captcha_tries > CAPTCHA_OCR_MAX_TRIES:
            print(
                f"验证码 OCR 已试 {self.captcha_tries - 1} 次仍未过，"
                f"暂停 {CAPTCHA_PAUSE_SEC // 60} 分钟后再完整登录"
            )
            raise CaptchaRequired("验证码 OCR 多次失败")

        try:
            from ocr_captcha import recognize

            raw = await asyncio.to_thread(recognize, img)
        except Exception as exc:
            print(f"OCR 调用失败：{exc}")
            self.captcha_guess = "ocrfail"
            self._keep_wrong_captcha()
            raise CaptchaRequired(f"OCR 失败：{exc}") from exc

        code = "".join(c for c in str(raw or "") if c.isalnum()).lower()
        if len(code) < 3:
            print(f"OCR 结果无效：{raw!r} → {code!r}")
            self.captcha_guess = code or "invalid"
            self._keep_wrong_captcha()
            raise CaptchaRequired(f"OCR 结果无效：{code!r}")

        print(f"OCR 识别为 {code}（第 {self.captcha_tries}/{CAPTCHA_OCR_MAX_TRIES} 次），正在提交")
        self.captcha_guess = code
        await self.send("CaptchaCode", code)

    async def wait_display_menu_optional(
        self, timeout: float, want_title: Optional[str] = None
    ) -> Optional[dict]:
        try:
            return await self.wait_display_menu(want_title, timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError, LogsNotReady):
            return None

    async def wait_display_menu(
        self,
        want_title: Optional[str],
        timeout: float = 25.0,
        want_path: Optional[list[str]] = None,
    ) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout
        seen: list[str] = []
        while True:
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                raise TimeoutError(
                    f"等待菜单超时：{want_title or '任意 DisplayMenu'}，收到过 {seen or '无'}"
                )
            try:
                msg = await self.recv_json(timeout=remain)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise TimeoutError(
                    f"等待菜单超时：{want_title or '任意 DisplayMenu'}，收到过 {seen or '无'}"
                ) from exc
            title = msg.get("Title")
            if str(title or "").lower() == "captcha":
                await self.solve_captcha(str(msg.get("Content") or ""))
                deadline = asyncio.get_event_loop().time() + timeout
                continue
            if title in ("GetTopMenu", "MsgBox1", "MsgBox0"):
                seen.append(str(title))
                text = str(msg.get("Content") or "")
                if title.startswith("MsgBox"):
                    print(f"服务器：{text}")
                    check_shop_cooldown(text)
                    check_captcha_busy(text)
                    self.note_captcha_reply(text)
                if "还没加载出来" in text or "日志信息" in text:
                    raise LogsNotReady(text)
                if "验证码" in text and getattr(self, "pending_path", None):
                    await asyncio.sleep(0.4)
                    await self.send("GoMenu", self.pending_path)
                    deadline = asyncio.get_event_loop().time() + timeout
                continue
            if title != "DisplayMenu":
                seen.append(str(title))
                vlog(f"忽略帧 Title={title!r}")
                continue
            menu = decode_content(msg.get("Content"))
            if not isinstance(menu, dict):
                continue
            got_title = str(menu.get("Title") or "")
            got_path = [str(x) for x in (menu.get("Path") or [])]
            seen.append(got_title or "(主菜单)")
            matched = False
            if want_title is None and want_path is None:
                matched = True
            elif want_title is not None and got_title == want_title:
                matched = True
            elif want_path is not None and got_path == want_path:
                matched = True
            if not matched:
                vlog(f"跳过菜单 Title={got_title!r} Path={got_path}")
                continue
            if got_path:
                self.menu_path = list(got_path)
            self.last_menu = menu
            self._captcha_passed()
            return menu

    async def wait_event(
        self,
        *,
        titles: Optional[list[str]] = None,
        menu_title: Optional[str] = None,
        timeout: float = 25.0,
    ) -> dict:
        want = {t.lower() for t in (titles or [])}
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                raise TimeoutError(f"等待超时：{titles or menu_title}")
            try:
                msg = await self.recv_json(timeout=remain)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise TimeoutError(f"等待超时：{titles or menu_title}") from exc
            title = str(msg.get("Title") or "")
            low = title.lower()
            if title == "DisplayMenu":
                menu = decode_content(msg.get("Content"))
                got = menu.get("Title") if isinstance(menu, dict) else None
                vlog(f"回包 DisplayMenu Title={got!r}")
            if str(title).lower() == "captcha":
                await self.solve_captcha(str(msg.get("Content") or ""))
                deadline = asyncio.get_event_loop().time() + timeout
                continue
            if title in ("MsgBox1", "MsgBox0"):
                text = str(msg.get("Content") or "")
                print(f"服务器：{text}")
                check_shop_cooldown(text)
                check_captcha_busy(text)
                self.note_captcha_reply(text)
            if low in want:
                if not captcha_answer_rejected(str(msg.get("Content") or "")):
                    self._captcha_passed()
                return msg
            if title == "DisplayMenu" and menu_title:
                menu = decode_content(msg.get("Content"))
                if isinstance(menu, dict) and menu.get("Title") == menu_title:
                    self._captcha_passed()
                    return msg

    async def wait_listing_done(self, timeout: float = 40.0) -> str:
        deadline = asyncio.get_event_loop().time() + timeout
        seen: list[str] = []
        while True:
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                raise TimeoutError(f"确认上架后无结果，收到过 {seen or '无'}")
            try:
                msg = await self.recv_json(timeout=remain)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise TimeoutError(f"确认上架后无结果，收到过 {seen or '无'}") from exc
            title = str(msg.get("Title") or "")
            if str(title).lower() == "captcha":
                await self.solve_captcha(str(msg.get("Content") or ""))
                deadline = asyncio.get_event_loop().time() + timeout
                continue
            if title in ("MsgBox1", "MsgBox0"):
                text = str(msg.get("Content") or "")
                print(f"服务器：{text}")
                seen.append(title)
                check_shop_cooldown(text)
                check_captcha_busy(text)
                self.note_captcha_reply(text)
                if title == "MsgBox0" and "成功" not in text:
                    raise ProtocolError(text or "上架失败")
                if "成功" in text or title == "MsgBox1":
                    self._captcha_passed()
                    return text
                continue
            if title == "DisplayMenu":
                menu = decode_content(msg.get("Content"))
                got = menu.get("Title") if isinstance(menu, dict) else None
                seen.append(str(got or title))
                vlog(f"回包 DisplayMenu Title={got!r}")
                if isinstance(menu, dict):
                    got_path = [str(x) for x in (menu.get("Path") or [])]
                    if got_path:
                        self.menu_path = got_path
                    self.last_menu = menu
                if got in ("上架我的", "交易市场", "我的上架历史"):
                    self._captcha_passed()
                    return f"已返回{got}（在线服可能不推通知框）"
                continue
            seen.append(title)

    def confirm_button_cmd(self, menu: dict) -> list[str]:
        for item in iter_menu_items(menu):
            typ = str(item.get("Type") or "")
            text = str(item.get("Text") or "")
            if typ not in ("button_confirm", "button") or "确认上架" not in text:
                continue
            cmd = [str(x) for x in (item.get("Cmd") or [])]
            if cmd and str(cmd[0]).startswith(";safe;"):
                cmd = cmd[1:]
            if cmd:
                return cmd
        return list(CONFIRM_CLICK)

    async def confirm_listing(
        self,
        path: list[str],
        data: dict[str, str],
        expect: list[str],
        safe_code: str,
    ) -> str:
        async with self._recv_lock:
            await asyncio.sleep(0.6)
            payload = {"Path": path, "Data": data}
            print(f"提交表单 {data}")
            await self.send("SubmitForm", payload)
            try:
                menu = await self.wait_display_menu("询问上架", timeout=30)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise TimeoutError(
                    f"提交后没有出现询问上架确认框。表单={data}。{exc}"
                ) from exc
            blob = json.dumps(menu, ensure_ascii=False)
            for piece in expect:
                if piece not in blob:
                    raise ProtocolError(f"确认框与报价不符，缺少 {piece!r}")
            await self.send("UseSafeCode", safe_code)
            chk = await self.wait_event(
                titles=["SafeCodeCheckResult", "MsgBox0", "MsgBox1"]
            )
            chk_title = str(chk.get("Title") or "")
            if chk_title.lower() == "msgbox0":
                check_shop_cooldown(str(chk.get("Content") or ""))
                check_captcha_busy(str(chk.get("Content") or ""))
                self.note_captcha_reply(str(chk.get("Content") or ""))
                raise ProtocolError(str(chk.get("Content") or "安全码失败"))
            if chk_title == "MsgBox1":
                text = str(chk.get("Content") or "")
                print(f"服务器：{text}")
                check_captcha_busy(text)
                self.note_captcha_reply(text)
                if "成功" in text:
                    return text
            click = self.confirm_button_cmd(menu)
            print(f"确认上架 → {' / '.join(click[-2:]) if len(click) >= 2 else click}")
            await asyncio.sleep(0.3)
            await self.send("ButtonClick", click)
            return await self.wait_listing_done()

    async def go_menu(
        self, path: list[str], want_title: Optional[str], *, direct: bool = False
    ) -> dict:
        async with self._recv_lock:
            if direct:
                prefixes = [path]
            else:
                start = 0
                while (
                    start < len(path)
                    and start < len(self.menu_path)
                    and path[start] == self.menu_path[start]
                ):
                    start += 1
                if start == len(path):
                    start = max(len(path) - 1, 0)
                prefixes = [path[:i] for i in range(start + 1, len(path) + 1)]
            menu: dict = {}
            if (
                direct
                and list(path) == self.menu_path
                and isinstance(self.last_menu, dict)
                and self.last_menu.get("Title") == want_title
            ):
                vlog(f"已在菜单：{' / '.join(path)}")
                return self.last_menu
            for prefix in prefixes:
                label = " / ".join(prefix)
                # 只打最终目标路径，中间层级走 verbose
                if prefix == path:
                    print(f"打开：{label}")
                else:
                    vlog(f"打开：{label}")
                await sleep_before_menu(label)
                self.pending_path = list(prefix)
                await self.send("GoMenu", prefix)
                menu = None
                last_exc: Optional[BaseException] = None
                for attempt in range(1, 7):
                    try:
                        menu = await self.wait_display_menu(
                            want_title if prefix == path else prefix[-1],
                            timeout=25,
                            want_path=prefix,
                        )
                        last_exc = None
                        break
                    except LogsNotReady:
                        last_exc = None
                        print(f"日志未加载，回主菜单重试（{attempt}/6）")
                        await asyncio.sleep(1.5)
                        await self.send("GoMenu", ["主菜单"])
                        await self.wait_display_menu_optional(timeout=15)
                        self.menu_path = []
                        await asyncio.sleep(0.8)
                        if prefix == path:
                            print(f"打开：{label}")
                        else:
                            vlog(f"打开：{label}")
                        await sleep_before_menu(label)
                        self.pending_path = list(prefix)
                        await self.send("GoMenu", prefix)
                    except (TimeoutError, asyncio.TimeoutError) as exc:
                        last_exc = exc
                        print(f"等菜单超时（{attempt}/6），回交易市场重发")
                        vlog(str(exc))
                        if attempt >= 6:
                            break
                        await asyncio.sleep(0.8)
                        if prefix != MARKET_PATH:
                            await self.send("GoMenu", MARKET_PATH)
                            await self.wait_display_menu_optional(
                                timeout=12, want_title="交易市场"
                            )
                            self.menu_path = list(MARKET_PATH)
                            await asyncio.sleep(0.4)
                        if prefix == path:
                            print(f"打开：{label}")
                        else:
                            vlog(f"打开：{label}")
                        await sleep_before_menu(label)
                        self.pending_path = list(prefix)
                        await self.send("GoMenu", prefix)
                if menu is None:
                    if last_exc is not None:
                        raise last_exc
                    raise TimeoutError(f"日志一直未加载：{' / '.join(prefix)}")
                self.menu_path = list(prefix)
            return menu

    async def open_home(self) -> dict:
        async with self._recv_lock:
            print("打开：主菜单")
            await sleep_before_menu("主菜单")
            await self.send("GoMenu", ["主菜单"])
            menu = await self.wait_display_menu(None, timeout=25)
            self.menu_path = []
            return menu

    async def login_session(self) -> dict:
        """离线：GetTopMenu[] → AskConnectOffline → 再 GoMenu 主菜单。
        在线（抓包）：GoMenu 主菜单后游戏服直接 DisplayMenu，不要二次刷新。"""
        async with self._recv_lock:
            await self.send("GoMenu", ["主菜单"])
            first = await self.wait_event(titles=["GetTopMenu", "DisplayMenu"], timeout=25)
            title = first.get("Title")
            if title == "GetTopMenu":
                servers = decode_content(first.get("Content"))
                if isinstance(servers, list) and servers:
                    print(f"GetTopMenu 非空（{len(servers)}），等待游戏服菜单")
                    menu = await self.wait_display_menu(None, timeout=25)
                    self.menu_path = []
                    return menu
                print("未进服，发送 AskConnectOffline")
                await self.send("AskConnectOffline", "")
                # 抓包会先回余额 -1 的空菜单；这份经常不来，死等就会让离线登录卡死。
                stub = await self.wait_display_menu_optional(timeout=3)
                await asyncio.sleep(0.4)
                await self.send("GoMenu", ["主菜单"])
                menu = await self.wait_display_menu_optional(timeout=25)
                if menu is None and stub is None:
                    raise TimeoutError("离线登录后未收到主菜单")
                if menu is None:
                    menu = stub
                money, coin = parse_balance(menu) if isinstance(menu, dict) else (None, None)
                for n in range(8):
                    if balance_known(money, coin):
                        break
                    print(f"离线余额未就绪，刷新主菜单（{n + 1}/8）")
                    await asyncio.sleep(1.5)
                    await self.send("GoMenu", ["主菜单"])
                    menu2 = await self.wait_display_menu_optional(timeout=15)
                    if isinstance(menu2, dict):
                        menu = menu2
                        money, coin = parse_balance(menu)
                self.menu_path = []
                print("离线菜单已就绪")
                return menu if isinstance(menu, dict) else stub
            menu = decode_content(first.get("Content"))
            if not isinstance(menu, dict):
                raise ProtocolError("主菜单不是 DisplayMenu")
            game = str(first.get("Server") or self.bound_server or "")
            if game and game != "cs2ui":
                self.bound_server = game
                print(f"已在服务器内（{game}），发出仍用空 Server，回包来自该服")
            else:
                print("已收到主菜单")
            self.menu_path = []
            await asyncio.sleep(0.4)
            return menu

    async def scan_once(
        self,
        *,
        bootstrap: bool = False,
        fetch_charts: bool = True,
        fetch_market: bool = False,
    ) -> Snapshot:
        snap = Snapshot()
        if bootstrap:
            home = await self.login_session()
            money, coin = parse_balance(home)
            if balance_known(money, coin):
                snap.money, snap.coin = money, coin
        else:
            home = await self.open_home()
            money, coin = parse_balance(home)
            if balance_known(money, coin):
                snap.money, snap.coin = money, coin
        # 上架要看盘口抢排序时只拉列表，可不解析走势图（有今日均价缓存）。
        if fetch_charts or fetch_market:
            point_menu = await self.go_menu(BUY_POINT_PATH, "买积分")
            money, coin = parse_balance(point_menu)
            if balance_known(money, coin):
                snap.money, snap.coin = money, coin
            snap.buy_points = parse_lots(point_menu)
            if fetch_charts:
                snap.buy_point_chart = parse_chart(point_menu)
            coin_menu = await self.go_menu(BUY_COIN_PATH, "买交易币")
            money, coin = parse_balance(coin_menu)
            if balance_known(money, coin):
                snap.money, snap.coin = money, coin
            snap.buy_coins = parse_lots(coin_menu)
            if fetch_charts:
                snap.buy_coin_chart = parse_chart(coin_menu)
        hist = await self.go_menu(HISTORY_PATH, "我的上架历史", direct=True)
        snap.my_open, snap.my_sold = parse_listing_history(hist)
        if not balance_known(snap.money, snap.coin):
            print("余额未知，重新打开主菜单获取")
            home = await self.open_home()
            money, coin = parse_balance(home)
            if balance_known(money, coin):
                snap.money, snap.coin = money, coin
        if not balance_known(snap.money, snap.coin):
            print("余额仍未知，再刷新一次主菜单")
            home = await self.open_home()
            money, coin = parse_balance(home)
            if balance_known(money, coin):
                snap.money, snap.coin = money, coin
        return snap


async def refresh_list_balance(client: MenuClient, snap: Snapshot, side: str) -> None:
    """继续上架只打开目标表单刷余额，不走主菜单 / 历史 / 交易市场。"""
    if side == "points" or (snap.coin is not None and snap.coin < LIST_COINS):
        path, title = SELL_POINT_PATH, "卖积分"
    else:
        path, title = SELL_COIN_PATH, "卖交易币"
    print(f"继续上架：直接打开 {title}")
    menu = await client.go_menu(path, title, direct=True)
    money, coin = parse_balance(menu)
    if balance_known(money, coin):
        snap.money, snap.coin = money, coin
        return
    print("表单里没有余额，只刷一次主菜单")
    home = await client.open_home()
    money, coin = parse_balance(home)
    if balance_known(money, coin):
        snap.money, snap.coin = money, coin


async def apply_listings(
    client: MenuClient,
    snap: Snapshot,
    q: dict,
    todo: list[str],
    *,
    execute: bool,
    safe_code: str,
) -> None:
    if not todo:
        print("没有可提交的上架。")
        return
    if not execute:
        print("预演结束，未提交。确认后加 --list --execute")
        return
    if not safe_code:
        raise SystemExit("请设置 SAFE_CODE 或 MENU_PASSWORD")
    print("开始提交上架…")
    # 卖交易币/卖积分是交易市场的平级页。先停在「上架我的」再 GoMenu 卖单，
    # 在线服经常不回包（等待菜单超时、收到过 无）。
    on_sell_form = client.menu_path[-1:] in (["卖交易币"], ["卖积分"])
    in_market = (
        len(client.menu_path) >= 2
        and client.menu_path[:2] == MARKET_PATH
        and client.menu_path[-1] == "交易市场"
    )
    if not on_sell_form and not in_market:
        await client.go_menu(MARKET_PATH, "交易市场", direct=True)
    if "coins" in todo:
        await client.go_menu(SELL_COIN_PATH, "卖交易币", direct=True)
        msg = await client.confirm_listing(
            SELL_COIN_PATH,
            {"sell": str(q["coins"]), "price": str(q["earned"])},
            [str(q["coins"]), str(q["earned"])],
            safe_code,
        )
        print(f"卖交易币结果：{msg}")
        await asyncio.sleep(0.8)
    if "points" in todo:
        await client.go_menu(SELL_POINT_PATH, "卖积分", direct=True)
        msg = await client.confirm_listing(
            SELL_POINT_PATH,
            {"sell": str(q["points_listed"]), "price": str(q["coins"])},
            [str(q["points_listed"]), str(q["coins"])],
            safe_code,
        )
        print(f"卖积分结果：{msg}")


def _listing_record(q: dict, side_key: str) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    if side_key == "coins":
        return {
            "id": "",
            "kind": "sell_coin",
            "side": "卖交易币",
            "coins": int(q["coins"]),
            "points": int(q["earned"]),
            "rate": int(q["high_unit"]),
            "open": True,
            "status": "刚提交",
            "when": now,
            "text": f"{q['coins']}币标{q['earned']}",
        }
    return {
        "id": "",
        "kind": "sell_points",
        "side": "卖积分",
        "coins": int(q["coins"]),
        "points": int(q["points_listed"]),
        "rate": int(q["low_unit"]),
        "open": True,
        "status": "刚提交",
        "when": now,
        "text": f"{q['points_listed']}积分标{q['coins']}币",
    }


async def drain_listings(
    client: MenuClient,
    snap: Snapshot,
    q: Optional[dict],
    *,
    execute: bool,
    safe_code: str,
    side: str,
) -> int:
    """两边都能挂就各挂 1 份（卖交易币 / 卖积分分开提交），余额不够的一侧跳过。"""
    if q is None:
        print("没有定价，无法上架。")
        return 0

    async def try_once() -> int:
        todo = print_list_plan(snap, q, side)
        if not todo:
            print(no_list_reason(q) + "。")
            return 0
        if not execute:
            print("预演结束，未提交。确认后加 --list --execute 或 --auto")
            return 0
        labels = {"coins": "卖交易币", "points": "卖积分"}
        print(
            "本轮提交 "
            + "、".join(labels.get(x, x) for x in todo)
            + f"（共 {len(todo)} 份，两侧分开挂）"
        )
        await apply_listings(
            client, snap, q, todo, execute=True, safe_code=safe_code
        )
        debit_after_listing(snap, q, todo)
        for side_key in todo:
            bump_today_listed(1, _listing_record(q, side_key))
        print(f"本轮已挂 {len(todo)} 份，下一轮再按盘口定价")
        return len(todo)

    try:
        return await try_once()
    except ShopCooldown as exc:
        print(f"商店冷却：{exc}，关闭连接后再挂")
        await client.close()
        await sleep_random(SHOP_COOLDOWN_SEC, "商店冷却")
        print("冷却结束，重新连接并登录，再试本轮上架")
        await client.connect()
        await client.login_session()
        await refresh_list_balance(client, snap, side)
        try:
            return await try_once()
        except ShopCooldown as exc2:
            print(f"冷却后仍遇商店冷却：{exc2}，本轮放弃")
            return 0


async def run_live(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")
    env_file = ROOT / ".env"
    steam = os.environ.get("STEAM_ID", "").strip()
    password = os.environ.get("MENU_PASSWORD", "").strip()
    safe_code = os.environ.get("SAFE_CODE", "").strip() or password
    host = os.environ.get("WS_HOST", "list.darkrp.cn:6514").strip()
    if args.steam:
        steam = args.steam
    if args.password:
        password = args.password
        if not os.environ.get("SAFE_CODE", "").strip():
            safe_code = password
    if not env_file.is_file():
        raise SystemExit(
            f"未找到 {env_file}\n请复制 .env.example 为 .env，填入 STEAM_ID 和 MENU_PASSWORD。"
        )
    if not steam.isdigit() or int(steam) < 1:
        raise SystemExit(
            "请在 .env 里设置 STEAM_ID 为 Steam 好友代码数字（抓包 WebSocket 地址里的 id3）。"
        )
    if len(password) < 8:
        raise SystemExit("请在 .env 里设置 MENU_PASSWORD（至少 8 位，登录菜单时用的密码）。")

    do_list = args.list or args.execute or args.auto
    if args.auto:
        args.execute = True
    if args.execute and args.loop:
        raise SystemExit("循环扫描不会自动上架，无人值守请用 --auto")

    cache = None if args.refresh_avg else load_daily_avg()
    fetch_charts = cache is None or args.refresh_avg or not do_list
    # 上架每轮都要拉盘口（买积分/买交易币列表），才能按对手价 ±1 抢排序。
    fetch_market = bool(do_list)
    if do_list and cache is not None and not args.refresh_avg:
        fetch_charts = False
        print(
            f"今日均价已缓存（{cache['date']}）："
            f"买积分 {cache['point_avg']:.1f} / 买交易币 {cache['coin_avg']:.1f}。"
            f"上架仍拉盘口定价，不重拉走势图。强制刷新均价：--refresh-avg"
        )

    interval = args.loop if args.loop and args.loop > 0 else None
    client = MenuClient(int(steam), password, host)
    print(f"连接 {client.url}")
    if args.auto:
        await reconnect(client, "首次连接")
    else:
        await client.connect()
    try:
        first = True
        relist = False
        snap = Snapshot()
        while True:
            try:
                if relist:
                    if cache is not None:
                        snap.buy_coin_chart, snap.buy_point_chart = charts_from_daily_avg(
                            cache
                        )
                        snap.avg_cached = True
                    # 继续上架前再刷一遍盘口，避免沿用过期对手价。
                    point_menu = await client.go_menu(BUY_POINT_PATH, "买积分")
                    snap.buy_points = parse_lots(point_menu)
                    money, coin = parse_balance(point_menu)
                    if balance_known(money, coin):
                        snap.money, snap.coin = money, coin
                    coin_menu = await client.go_menu(BUY_COIN_PATH, "买交易币")
                    snap.buy_coins = parse_lots(coin_menu)
                    money, coin = parse_balance(coin_menu)
                    if balance_known(money, coin):
                        snap.money, snap.coin = money, coin
                    hist = await client.go_menu(HISTORY_PATH, "我的上架历史", direct=True)
                    snap.my_open, snap.my_sold = parse_listing_history(hist)
                    await refresh_list_balance(client, snap, args.side)
                else:
                    snap = await client.scan_once(
                        bootstrap=first,
                        fetch_charts=fetch_charts,
                        fetch_market=fetch_market,
                    )
                    first = False
                    if do_list and not fetch_charts and cache is not None:
                        snap.buy_coin_chart, snap.buy_point_chart = charts_from_daily_avg(
                            cache
                        )
                        snap.avg_cached = True
                    print_snapshot(snap, args.top, quiet=bool(args.auto))
                    if fetch_charts and snap.buy_point_chart and snap.buy_coin_chart:
                        pa, pn = snap.buy_point_chart.avg_5d
                        ca, cn = snap.buy_coin_chart.avg_5d
                        if pa is not None and ca is not None:
                            save_daily_avg(pa, ca, pn or 5, cn or 5)
                            print(f"已写入今日均价（MySQL / {AVG_CACHE_PATH.name}）")
                if do_list:
                    q = quotes_from_snap(snap)
                    # --auto 的 quiet 摘要里已含定价，避免重复一行
                    listed = 0
                    list_failed = False
                    try:
                        listed = await drain_listings(
                            client,
                            snap,
                            q,
                            execute=args.execute,
                            safe_code=safe_code,
                            side=args.side,
                        )
                    except (
                        TimeoutError,
                        asyncio.TimeoutError,
                        ProtocolError,
                        ConnectionLost,
                    ) as exc:
                        if not args.auto:
                            raise
                        list_failed = True
                        print(f"本轮上架失败：{exc}，关闭连接后短等再完整登录")
                    if args.auto:
                        if list_failed:
                            await client.close()
                            await sleep_random((15, 45), "菜单/协议失败，不按库存等待")
                            print("短等结束，重新连接并走登录流程")
                            await reconnect(client, "重新连接")
                        else:
                            await wait_auto_round(
                                client,
                                args.wait,
                                idle=listed == 0,
                                reason="" if listed else no_list_reason(q),
                                soon=recheck_soon(q),
                                refill=need_refill(q),
                            )
                        first = True
                        relist = False
                        continue
                    if not await ask_continue():
                        print("已退出")
                        break
                    relist = True
                    continue
                if interval is None:
                    break
                until_mid = seconds_until_midnight()
                if until_mid <= interval:
                    print(f"\n{until_mid:.0f} 秒后到 0 点，结算昨天利润（Ctrl+C 停止）...")
                    await asyncio.sleep(until_mid)
                    continue
                print(f"\n{interval} 秒后再次扫描（Ctrl+C 停止）...")
                await asyncio.sleep(interval)
            except CaptchaRequired as exc:
                print(f"遇到验证码：{exc}")
                await client.close()
                print(
                    f"暂停 {CAPTCHA_PAUSE_SEC // 60} 分钟后再继续"
                    f"（图片 captcha.png，Ctrl+C 停止）"
                )
                await asyncio.sleep(CAPTCHA_PAUSE_SEC)
                print("时间到，重新连接并走登录流程")
                await reconnect(client, "重新连接")
                first = True
                relist = False
            except (ConnectionLost, ProtocolError, TimeoutError, asyncio.TimeoutError) as exc:
                # scan_once / 菜单途中断线（1002 等）不应直接退出 --auto
                if not args.auto and not interval:
                    raise
                print(f"连接异常：{exc}")
                await client.close()
                await sleep_random((20, 60), "断线后短等再重连")
                print("重新连接并走登录流程")
                await reconnect(client, "重新连接")
                first = True
                relist = False
            except Exception as exc:
                # --auto：握手拒绝、网络抖动等一律不退出，短等后重连
                if not args.auto:
                    raise
                print(f"本轮异常：{exc}，关闭连接后短等再完整登录")
                await client.close()
                await sleep_random((20, 60), "异常后短等再重连")
                await reconnect(client, "重新连接")
                first = True
                relist = False
    finally:
        await client.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="扫描盘口，并可按 5 日均上架")
    p.add_argument("--har", type=Path, help="从 HAR 回放解析，不连接服务器")
    p.add_argument("--loop", type=float, default=0, help="循环间隔秒数，0 表示只扫一次")
    p.add_argument("--top", type=int, default=int(os.environ.get("SCAN_TOP", "8")))
    p.add_argument("--steam", default="", help="覆盖 STEAM_ID")
    p.add_argument("--password", default="", help="覆盖 MENU_PASSWORD")
    p.add_argument("--list", action="store_true", help="按 5 日均生成上架计划")
    p.add_argument(
        "--refresh-avg",
        action="store_true",
        help="强制重新拉取买积分/买交易币走势图，覆盖今日均价缓存",
    )
    p.add_argument("--execute", action="store_true", help="真正提交上架（需有 .env 凭证）")
    p.add_argument(
        "--auto",
        action="store_true",
        help="无人值守循环上架：有货就挂，没货等待，Ctrl+C 停止",
    )
    p.add_argument(
        "--wait",
        type=float,
        default=45,
        help="--auto 两轮间隔秒数，默认 45",
    )
    p.add_argument(
        "--side",
        choices=["both", "coins", "points"],
        default="both",
        help="上架哪一侧，默认两边都挂",
    )
    return p.parse_args()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    install_timestamp_logs()
    args = parse_args()
    if args.har:
        if args.execute or args.auto:
            raise SystemExit("HAR 回放不能 --execute / --auto")
        snap = extract_menus_from_har(args.har)
        print_snapshot(snap, args.top)
        if args.list:
            q = quotes_from_snap(snap)
            if q:
                save_daily_avg(
                    q["point_avg"],
                    q["coin_avg"],
                    snap.buy_point_chart.avg_5d[1] if snap.buy_point_chart else 5,
                    snap.buy_coin_chart.avg_5d[1] if snap.buy_coin_chart else 5,
                )
                print_list_plan(snap, q, args.side)
                print("预演结束，未提交。确认后用真实连接加 --list --execute")
                print(f"已写入今日均价（MySQL / {AVG_CACHE_PATH.name}）")
        return
    try:
        asyncio.run(run_live(args))
    except CaptchaRequired as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
    except ProtocolError as exc:
        print(f"协议错误：{exc}", file=sys.stderr)
        sys.exit(1)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        print(f"等待服务器超时：{exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
