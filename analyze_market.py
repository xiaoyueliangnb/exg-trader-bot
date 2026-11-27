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

控制台「分析」页通过 api.py 调用 analyze()，与命令行结果一致。
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from db import _connect, load_dotenv
from jifen import MIN_PROFIT_PER_COIN

load_dotenv()

PEAK_RATIO = 1.2
SIDE_NAME = {"sell_points": "卖积分", "sell_coin": "卖交易币"}


class NoDatabase(RuntimeError):
    pass


def fetch(sql: str, args: tuple = ()) -> list[dict]:
    conn = _connect()
    if conn is None:
        raise NoDatabase("MySQL 未配置或连不上，分析需要数据库里的快照数据")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())
    finally:
        conn.close()


def median(xs: list[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def mean(xs: list[float]) -> Optional[float]:
    return statistics.mean(xs) if xs else None


def fmt(x: Optional[float], digits: int = 1) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def lead_label(lead: Optional[int]) -> str:
    if lead is None:
        return "无盘口"
    if lead > 0:
        return f"领先{lead}"
    if lead < 0:
        return f"落后{-lead}"
    return "持平"


# ---------- 计算 ----------


def compute_tiers(since: datetime) -> dict:
    rows = fetch(
        "SELECT ts, payload_json FROM market_snapshot WHERE ts >= %s ORDER BY ts",
        (since,),
    )
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
    tiers = []
    for coins in sorted(stat):
        s = stat[coins]
        ok = sum(1 for x in s["per_coin"] if x >= MIN_PROFIT_PER_COIN)
        tiers.append(
            {
                "coins": coins,
                "both_ratio": s["seen"] / total if total else 0,
                "points_seen": len(s["pt"]) / total if total else 0,
                "coins_seen": len(s["cn"]) / total if total else 0,
                "points_best": median(s["pt"]),
                "points_n": median(s["pt_n"]),
                "coins_best": median(s["cn"]),
                "coins_n": median(s["cn_n"]),
                "per_coin": median(s["per_coin"]),
                "ok_ratio": ok / len(s["per_coin"]) if s["per_coin"] else None,
            }
        )
    return {
        "snapshots": total,
        "first": str(rows[0]["ts"]) if rows else None,
        "last": str(rows[-1]["ts"]) if rows else None,
        "tiers": tiers,
    }


def compute_fill_speed(since: datetime) -> dict:
    tracks = fetch(
        "SELECT listing_id, kind, coins, rate, first_seen, closed_at, status "
        "FROM listing_track WHERE status='sold' AND closed_at >= %s",
        (since,),
    )
    submits = fetch(
        "SELECT ts, kind, coins, rate, book_top FROM listing_submit WHERE ts >= %s ORDER BY ts",
        (since - timedelta(days=2),),
    )
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for s in submits:
        by_key[(s["kind"], s["coins"], int(s["rate"]))].append(s)

    by_lead: dict[tuple, list[float]] = defaultdict(list)
    by_slot: dict[tuple, list[float]] = defaultdict(list)
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
        by_lead[(t["kind"], lead)].append(minutes)
        by_slot[(t["kind"], sub["ts"].hour // 3 * 3)].append(minutes)

    def stat(xs: list[float]) -> dict:
        return {"n": len(xs), "median": median(xs), "mean": mean(xs)}

    lead_rows = [
        {"kind": k, "side": SIDE_NAME.get(k, k), "lead": lead, "label": lead_label(lead), **stat(xs)}
        for (k, lead), xs in sorted(
            by_lead.items(), key=lambda kv: (kv[0][0], -999 if kv[0][1] is None else kv[0][1])
        )
    ]
    slot_rows = [
        {"kind": k, "side": SIDE_NAME.get(k, k), "hour": h, **stat(xs)}
        for (k, h), xs in sorted(by_slot.items())
    ]
    return {
        "sold": len(tracks),
        "submits": len(submits),
        "matched": matched,
        "by_lead": lead_rows,
        "by_slot": slot_rows,
    }


def compute_hourly(since: datetime) -> dict:
    rows = fetch(
        "SELECT kind, closed_at FROM listing_track WHERE status='sold' AND closed_at >= %s",
        (since,),
    )
    counts = {"weekday": [0] * 24, "weekend": [0] * 24}
    days: dict[str, set] = {"weekday": set(), "weekend": set()}
    for r in rows:
        ts: datetime = r["closed_at"]
        key = "weekend" if ts.weekday() >= 5 else "weekday"
        counts[key][ts.hour] += 1
        days[key].add(ts.date())

    out = {"sold": len(rows)}
    for key in ("weekday", "weekend"):
        ndays = len(days[key])
        per_day = [c / ndays for c in counts[key]] if ndays else [0.0] * 24
        avg = sum(per_day) / 24
        out[key] = {
            "days": ndays,
            "per_day": per_day,
            "mean": avg,
            "suggested_peaks": [h for h in range(24) if ndays and per_day[h] >= avg * PEAK_RATIO],
        }
    return out


def current_peaks() -> dict:
    """scan.py 里实际生效的高峰小时，供页面和建议值对照。"""
    from scan import auto_round_wait

    monday = date(2026, 11, 23)
    saturday = date(2026, 11, 28)

    def peaks(day: date) -> list[int]:
        out = []
        for h in range(24):
            _, label = auto_round_wait(datetime(day.year, day.month, day.day, h, 30))
            if "高峰" in label:
                out.append(h)
        return out

    return {"weekday": peaks(monday), "weekend": peaks(saturday)}


def analyze(days: int = 14) -> dict:
    since = datetime.now() - timedelta(days=days)
    hourly = compute_hourly(since)
    try:
        cur = current_peaks()
    except Exception:
        cur = {"weekday": [], "weekend": []}
    for key in ("weekday", "weekend"):
        hourly[key]["current_peaks"] = cur[key]
    return {
        "days": days,
        "since": since.strftime("%Y-%m-%d %H:%M"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "min_profit_per_coin": MIN_PROFIT_PER_COIN,
        "peak_ratio": PEAK_RATIO,
        "tiers": compute_tiers(since),
        "fill": compute_fill_speed(since),
        "hourly": hourly,
    }


# ---------- 命令行输出 ----------


def print_tiers(r: dict) -> None:
    print(f"\n=== 一、分档盘口（快照 {r['snapshots']} 次）===")
    if not r["snapshots"]:
        print("还没有快照。启动自动上架后每轮扫描会记一次。")
        return
    print(
        f"{'档位':>6} {'两边都有':>8} {'卖积分最优':>10} {'挂单数':>6} "
        f"{'卖币最优':>8} {'挂单数':>6} {'±1每币利润(中位)':>16} {f'≥{MIN_PROFIT_PER_COIN}/币占比':>14}"
    )
    for t in r["tiers"]:
        ratio = "-" if t["ok_ratio"] is None else f"{t['ok_ratio'] * 100:.0f}%"
        print(
            f"{t['coins']:>5}币 {t['both_ratio'] * 100:>7.0f}% "
            f"{fmt(t['points_best']):>10} {fmt(t['points_n'], 0):>6} "
            f"{fmt(t['coins_best']):>8} {fmt(t['coins_n'], 0):>6} "
            f"{fmt(t['per_coin'], 2):>16} {ratio:>14}"
        )
    print("说明：±1每币利润 = 两边都按该档盘口最优 ±1 挂、扣掉双边手续费后每币赚多少（未套均价护栏）。")


def print_fill(r: dict) -> None:
    print(f"\n=== 二、挂单成交速度（成交 {r['sold']} 张，提交记录 {r['submits']} 次）===")
    if not r["matched"]:
        print("还没有能对上提交记录的成交单。新逻辑跑几天后再看。")
        return
    print(f"对上提交记录的成交单 {r['matched']} 张")
    print(f"{'方向':<6} {'挂单时相对盘口':<10} {'张数':>4} {'成交耗时中位(分)':>16} {'均值(分)':>10}")
    for x in r["by_lead"]:
        print(f"{x['side']:<6} {x['label']:<12} {x['n']:>4} {fmt(x['median']):>16} {fmt(x['mean']):>10}")
    print(f"\n{'方向':<6} {'挂单时段':<8} {'张数':>4} {'成交耗时中位(分)':>16}")
    for x in r["by_slot"]:
        h = x["hour"]
        print(f"{x['side']:<6} {h:02d}-{h + 3:02d}点   {x['n']:>4} {fmt(x['median']):>16}")


def print_hourly(r: dict) -> None:
    print(f"\n=== 三、按小时成交（自己的单，共 {r['sold']} 张）===")
    if not r["sold"]:
        print("还没有成交记录。")
        return
    for key, name in (("weekday", "工作日"), ("weekend", "周末")):
        x = r[key]
        if not x["days"]:
            print(f"{name}：无数据")
            continue
        bar = " ".join(f"{h:02d}:{x['per_day'][h]:.1f}" for h in range(24))
        print(f"{name}（{x['days']} 天，每天平均张数）：{bar}")
        peaks = ", ".join(f"{h:02d}" for h in x["suggested_peaks"]) or "无明显高峰"
        print(f"  建议高峰小时（≥ 平均 {PEAK_RATIO} 倍）：{peaks}")
        if x.get("current_peaks"):
            print(f"  当前生效高峰小时：{', '.join(f'{h:02d}' for h in x['current_peaks'])}")


def main() -> None:
    p = argparse.ArgumentParser(description="分析分档盘口、成交速度、成交时段")
    p.add_argument("--days", type=int, default=14, help="看最近多少天，默认 14")
    args = p.parse_args()
    try:
        r = analyze(args.days)
    except NoDatabase as exc:
        raise SystemExit(str(exc))
    print(f"数据范围：{r['since']} 至今")
    print_tiers(r["tiers"])
    print_fill(r["fill"])
    print_hourly(r["hourly"])


if __name__ == "__main__":
    main()
