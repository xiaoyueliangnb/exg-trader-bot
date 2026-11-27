#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
只读分析：用 scan.py 攒下的盘口快照与挂单跟踪数据，回答三个问题。

  1. 各数量档（10/20/50…币）的盘口价差，哪一档 ±1 抢第一后每币利润更高
  2. 自己的单挂出后多久成交，跟「领先盘口几价」「几点挂」有什么关系
  3. 一天里哪些小时成交最多，用来校正高峰 / 平峰时段

用法：
  python analyze_market.py            # 默认看最近 14 天
  python analyze_market.py --days 30
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from db import _connect, load_dotenv
from jifen import MIN_PROFIT_PER_COIN

load_dotenv()


def fetch(sql: str, args: tuple = ()) -> list[dict]:
    conn = _connect()
    if conn is None:
        raise SystemExit("MySQL 未配置或连不上，分析需要数据库里的快照数据")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())
    finally:
        conn.close()


def median(xs: list[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def fmt(x: Optional[float], digits: int = 1) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def report_tiers(since: datetime) -> None:
    rows = fetch(
        "SELECT ts, payload_json FROM market_snapshot WHERE ts >= %s ORDER BY ts",
        (since,),
    )
    print(f"\n=== 一、分档盘口（快照 {len(rows)} 次）===")
    if not rows:
        print("还没有快照。启动自动上架后每轮扫描会记一次。")
        return
    stat: dict[int, dict] = defaultdict(
        lambda: {"seen": 0, "pt": [], "cn": [], "pt_n": [], "cn_n": [], "per_coin": []}
    )
    for row in rows:
        p = json.loads(row["payload_json"])
        for c, v in (p.get("points_book") or {}).items():
            s = stat[int(c)]
            s["pt"].append(v["best"])
            s["pt_n"].append(v["n"])
        for c, v in (p.get("coins_book") or {}).items():
            s = stat[int(c)]
            s["cn"].append(v["best"])
            s["cn_n"].append(v["n"])
        for c, v in (p.get("tier_profit") or {}).items():
            s = stat[int(c)]
            s["seen"] += 1
            s["per_coin"].append(v["per_coin"])
    total = len(rows)
    print(
        f"{'档位':>6} {'两边都有':>8} {'卖积分最优':>10} {'挂单数':>6} "
        f"{'卖币最优':>8} {'挂单数':>6} {'±1每币利润(中位)':>16} {f'≥{MIN_PROFIT_PER_COIN}/币占比':>14}"
    )
    for coins in sorted(stat):
        s = stat[coins]
        ok = sum(1 for x in s["per_coin"] if x >= MIN_PROFIT_PER_COIN)
        ratio = f"{ok / len(s['per_coin']) * 100:.0f}%" if s["per_coin"] else "-"
        print(
            f"{coins:>5}币 {s['seen'] / total * 100:>7.0f}% "
            f"{fmt(median(s['pt'])):>10} {fmt(median(s['pt_n']), 0):>6} "
            f"{fmt(median(s['cn'])):>8} {fmt(median(s['cn_n']), 0):>6} "
            f"{fmt(median(s['per_coin']), 2):>16} {ratio:>14}"
        )
    print("说明：±1每币利润 = 两边都按该档盘口最优 ±1 挂、扣掉双边手续费后每币赚多少（未套均价护栏）。")


def report_fill_speed(since: datetime) -> None:
    tracks = fetch(
        "SELECT listing_id, kind, coins, rate, first_seen, closed_at, status "
        "FROM listing_track WHERE status='sold' AND closed_at >= %s",
        (since,),
    )
    submits = fetch(
        "SELECT ts, kind, coins, rate, book_top FROM listing_submit WHERE ts >= %s ORDER BY ts",
        (since - timedelta(days=2),),
    )
    print(f"\n=== 二、挂单成交速度（成交 {len(tracks)} 张，提交记录 {len(submits)} 次）===")
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for s in submits:
        by_key[(s["kind"], s["coins"], int(s["rate"]))].append(s)

    buckets: dict[tuple, list[float]] = defaultdict(list)
    hours: dict[tuple, list[float]] = defaultdict(list)
    matched = 0
    for t in tracks:
        if t["first_seen"] is None:
            continue
        cands = [
            s
            for s in by_key.get((t["kind"], t["coins"], int(round(t["rate"]))), [])
            if t["first_seen"] - timedelta(hours=6) <= s["ts"] <= t["first_seen"]
        ]
        if not cands:
            continue
        sub = cands[-1]
        minutes = (t["closed_at"] - sub["ts"]).total_seconds() / 60
        if minutes < 0:
            continue
        matched += 1
        lead = None
        if sub["book_top"] is not None:
            if t["kind"] == "sell_points":
                lead = int(sub["rate"]) - round(sub["book_top"])
            else:
                lead = round(sub["book_top"]) - int(sub["rate"])
        side = "卖积分" if t["kind"] == "sell_points" else "卖交易币"
        lead_tag = "无盘口" if lead is None else (f"领先{lead}" if lead > 0 else f"落后{-lead}" if lead < 0 else "持平")
        buckets[(side, lead_tag)].append(minutes)
        hours[(side, sub["ts"].hour // 3 * 3)].append(minutes)

    if not matched:
        print("还没有能对上提交记录的成交单。新逻辑跑几天后再看。")
        return
    print(f"对上提交记录的成交单 {matched} 张")
    print(f"{'方向':<6} {'挂单时相对盘口':<10} {'张数':>4} {'成交耗时中位(分)':>16} {'均值(分)':>10}")
    for (side, tag), xs in sorted(buckets.items()):
        print(f"{side:<6} {tag:<12} {len(xs):>4} {fmt(median(xs)):>16} {fmt(statistics.mean(xs)):>10}")
    print(f"\n{'方向':<6} {'挂单时段':<8} {'张数':>4} {'成交耗时中位(分)':>16}")
    for (side, h), xs in sorted(hours.items()):
        print(f"{side:<6} {h:02d}-{h + 3:02d}点   {len(xs):>4} {fmt(median(xs)):>16}")


def report_hourly(since: datetime) -> None:
    rows = fetch(
        "SELECT kind, closed_at FROM listing_track WHERE status='sold' AND closed_at >= %s",
        (since,),
    )
    print(f"\n=== 三、按小时成交（自己的单，共 {len(rows)} 张）===")
    if not rows:
        print("还没有成交记录。")
        return
    weekday = [0] * 24
    weekend = [0] * 24
    days_wd: set = set()
    days_we: set = set()
    for r in rows:
        ts: datetime = r["closed_at"]
        if ts.weekday() >= 5:
            weekend[ts.hour] += 1
            days_we.add(ts.date())
        else:
            weekday[ts.hour] += 1
            days_wd.add(ts.date())

    def show(name: str, counts: list[int], ndays: int) -> None:
        if not ndays:
            print(f"{name}：无数据")
            return
        per_day = [c / ndays for c in counts]
        mean = sum(per_day) / 24
        peak = [h for h in range(24) if per_day[h] >= mean * 1.2]
        bar = " ".join(f"{h:02d}:{per_day[h]:.1f}" for h in range(24))
        print(f"{name}（{ndays} 天，每天平均张数）：{bar}")
        print(f"  建议高峰小时（≥ 平均 1.2 倍）：{', '.join(f'{h:02d}' for h in peak) or '无明显高峰'}")

    show("工作日", weekday, len(days_wd))
    show("周末", weekend, len(days_we))


def main() -> None:
    p = argparse.ArgumentParser(description="分析分档盘口、成交速度、成交时段")
    p.add_argument("--days", type=int, default=14, help="看最近多少天，默认 14")
    args = p.parse_args()
    since = datetime.now() - timedelta(days=args.days)
    print(f"数据范围：{since:%Y-%m-%d %H:%M} 至今")
    report_tiers(since)
    report_fill_speed(since)
    report_hourly(since)


if __name__ == "__main__":
    main()
