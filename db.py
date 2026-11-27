#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MySQL 存储均价与每日利润；连不上库时回退读写 json。"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
AVG_CACHE_PATH = ROOT / "avg_cache.json"
PROFIT_CACHE_PATH = ROOT / "daily_profit.json"
DETAIL_CACHE_PATH = ROOT / "detail_cache.json"

_warned = False
_schema_ready = False


def load_dotenv(path: Optional[Path] = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


def today_str() -> str:
    return date.today().isoformat()


def mysql_configured() -> bool:
    return bool(os.environ.get("MYSQL_USER") and os.environ.get("MYSQL_DATABASE"))


def _ensure_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    dbname = os.environ.get("MYSQL_DATABASE") or "jifen"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='daily_profit' AND COLUMN_NAME='n_listed'",
            (dbname,),
        )
        row = cur.fetchone() or {}
        if int(row.get("n") or 0) == 0:
            cur.execute(
                "ALTER TABLE daily_profit ADD COLUMN n_listed INT NOT NULL DEFAULT 0"
            )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS day_detail ("
            "detail_date DATE NOT NULL,"
            "listed_json LONGTEXT NOT NULL,"
            "pairs_json LONGTEXT NOT NULL,"
            "redeem_json LONGTEXT NOT NULL,"
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "PRIMARY KEY (detail_date)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        for ddl in MARKET_DDL:
            cur.execute(ddl)
    _schema_ready = True


MARKET_DDL = (
    "CREATE TABLE IF NOT EXISTS market_snapshot ("
    "id BIGINT NOT NULL AUTO_INCREMENT,"
    "ts DATETIME NOT NULL,"
    "payload_json LONGTEXT NOT NULL,"
    "PRIMARY KEY (id), KEY idx_ts (ts)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS listing_submit ("
    "id BIGINT NOT NULL AUTO_INCREMENT,"
    "ts DATETIME NOT NULL,"
    "kind VARCHAR(16) NOT NULL,"
    "coins INT NOT NULL,"
    "points INT NOT NULL,"
    "rate INT NOT NULL,"
    "book_top DOUBLE NULL,"
    "book_second DOUBLE NULL,"
    "avg5 DOUBLE NULL,"
    "profit INT NOT NULL DEFAULT 0,"
    "money INT NULL,"
    "coin INT NULL,"
    "PRIMARY KEY (id), KEY idx_ts (ts)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS listing_track ("
    "listing_id BIGINT NOT NULL,"
    "kind VARCHAR(16) NOT NULL,"
    "coins INT NOT NULL,"
    "points INT NOT NULL,"
    "rate DOUBLE NOT NULL,"
    "first_seen DATETIME NULL,"
    "closed_at DATETIME NULL,"
    "status VARCHAR(16) NOT NULL DEFAULT 'open',"
    "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
    "PRIMARY KEY (listing_id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
)
MARKET_LOG_PATH = ROOT / "market_log.jsonl"


def _connect():
    if not mysql_configured():
        return None
    try:
        import pymysql
    except ImportError:
        _warn("未安装 pymysql，均价/利润改用 json")
        return None
    try:
        conn = pymysql.connect(
            host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ["MYSQL_USER"],
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ["MYSQL_DATABASE"],
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=5,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except Exception as exc:
        _warn(f"MySQL 连接失败（{exc}），均价/利润改用 json")
        return None
    try:
        _ensure_schema(conn)
    except Exception as exc:
        _warn(f"升级表结构失败（{exc}）")
    return conn


def _warn(msg: str) -> None:
    global _warned
    if not _warned:
        print(f"[db] {msg}")
        _warned = True


def _json_avg() -> dict:
    if not AVG_CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(AVG_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _json_profit() -> dict:
    if not PROFIT_CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(PROFIT_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_profit(cache: dict) -> None:
    PROFIT_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_json_avg(payload: dict) -> None:
    AVG_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _empty_detail(day: Optional[str] = None) -> dict:
    return {
        "date": day or today_str(),
        "listed": [],
        "pairs": [],
        "redeem": [],
    }


def _json_detail() -> dict:
    if not DETAIL_CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(DETAIL_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_detail(cache: dict) -> None:
    DETAIL_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_detail_row(row: dict, day: str) -> dict:
    payload = _empty_detail(day)
    for key in ("listed", "pairs", "redeem"):
        raw = row.get(f"{key}_json") if f"{key}_json" in row else row.get(key)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = []
        if isinstance(raw, list):
            payload[key] = raw
    return payload


def load_day_detail(day: Optional[str] = None) -> dict:
    want = day or today_str()
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT listed_json, pairs_json, redeem_json FROM day_detail "
                    "WHERE detail_date = %s",
                    (want,),
                )
                row = cur.fetchone()
            if row:
                return _parse_detail_row(row, want)
        except Exception as exc:
            _warn(f"读明细失败（{exc}）")
        finally:
            conn.close()
    cache = _json_detail()
    data = cache.get(want)
    if isinstance(data, dict):
        payload = _empty_detail(want)
        for key in ("listed", "pairs", "redeem"):
            if isinstance(data.get(key), list):
                payload[key] = data[key]
        return payload
    return _empty_detail(want)


def save_day_detail(payload: dict) -> None:
    day = str(payload.get("date") or today_str())
    listed = payload.get("listed") if isinstance(payload.get("listed"), list) else []
    pairs = payload.get("pairs") if isinstance(payload.get("pairs"), list) else []
    redeem = payload.get("redeem") if isinstance(payload.get("redeem"), list) else []
    body = {"date": day, "listed": listed, "pairs": pairs, "redeem": redeem}
    cache = _json_detail()
    cache[day] = body
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO day_detail (detail_date, listed_json, pairs_json, redeem_json) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE listed_json=VALUES(listed_json), "
                    "pairs_json=VALUES(pairs_json), redeem_json=VALUES(redeem_json)",
                    (
                        day,
                        json.dumps(listed, ensure_ascii=False),
                        json.dumps(pairs, ensure_ascii=False),
                        json.dumps(redeem, ensure_ascii=False),
                    ),
                )
        except Exception as exc:
            _warn(f"写明细失败（{exc}）")
        finally:
            conn.close()
    _write_json_detail(cache)


def _row_to_avg(row: dict) -> dict:
    return {
        "date": str(row["cache_date"]),
        "point_avg": float(row["point_avg"]),
        "coin_avg": float(row["coin_avg"]),
        "n_point": int(row["n_point"] or 5),
        "n_coin": int(row["n_coin"] or 5),
    }


def _row_to_profit(row: dict) -> dict:
    settled = row.get("settled_on")
    return {
        "date": str(row["profit_date"]),
        "n_coin": int(row["n_coin"] or 0),
        "n_pt": int(row["n_pt"] or 0),
        "n_pair": int(row["n_pair"] or 0),
        "n_redeem": int(row["n_redeem"] or 0),
        "coin_n": int(row["coin_n"] or 0),
        "coin_pts": int(row["coin_pts"] or 0),
        "fee_c": int(row["fee_c"] or 0),
        "pt_n": int(row["pt_n"] or 0),
        "pt_pts": int(row["pt_pts"] or 0),
        "fee_p": int(row["fee_p"] or 0),
        "redeem_fee": int(row["redeem_fee"] or 0),
        "net_coin": int(row["net_coin"] or 0),
        "profit": int(row["profit"] or 0),
        "n_listed": int(row.get("n_listed") or 0),
        "settled_on": str(settled) if settled else None,
    }


def load_daily_avg() -> Optional[dict]:
    """仅返回今天的均价（给 scan.py 决定要不要再拉走势图）。"""
    want = today_str()
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cache_date, point_avg, coin_avg, n_point, n_coin "
                    "FROM avg_cache WHERE cache_date = %s",
                    (want,),
                )
                row = cur.fetchone()
            if row:
                return _row_to_avg(row)
        except Exception as exc:
            _warn(f"读均价失败（{exc}）")
        finally:
            conn.close()
    data = _json_avg()
    if not data or data.get("date") != want:
        return None
    try:
        return {
            "date": want,
            "point_avg": float(data["point_avg"]),
            "coin_avg": float(data["coin_avg"]),
            "n_point": int(data.get("n_point") or 5),
            "n_coin": int(data.get("n_coin") or 5),
        }
    except (KeyError, TypeError, ValueError):
        return None


def load_avg_latest() -> dict:
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cache_date, point_avg, coin_avg, n_point, n_coin "
                    "FROM avg_cache ORDER BY cache_date DESC LIMIT 1"
                )
                row = cur.fetchone()
            if row:
                return _row_to_avg(row)
        except Exception as exc:
            _warn(f"读均价失败（{exc}）")
        finally:
            conn.close()
    return _json_avg()


def save_daily_avg(point_avg: float, coin_avg: float, n_point: int, n_coin: int) -> None:
    payload = {
        "date": today_str(),
        "point_avg": point_avg,
        "coin_avg": coin_avg,
        "n_point": n_point,
        "n_coin": n_coin,
    }
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO avg_cache (cache_date, point_avg, coin_avg, n_point, n_coin) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE point_avg=VALUES(point_avg), coin_avg=VALUES(coin_avg), "
                    "n_point=VALUES(n_point), n_coin=VALUES(n_coin)",
                    (
                        payload["date"],
                        payload["point_avg"],
                        payload["coin_avg"],
                        payload["n_point"],
                        payload["n_coin"],
                    ),
                )
        except Exception as exc:
            _warn(f"写均价失败（{exc}），改写 json")
        finally:
            conn.close()
    _write_json_avg(payload)


def load_profit() -> dict:
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profit_date, n_coin, n_pt, n_pair, n_redeem, coin_n, coin_pts, "
                    "fee_c, pt_n, pt_pts, fee_p, redeem_fee, net_coin, profit, n_listed, settled_on "
                    "FROM daily_profit ORDER BY profit_date"
                )
                rows = cur.fetchall() or []
                cur.execute("SELECT as_of, yesterday FROM profit_meta WHERE id = 1")
                meta = cur.fetchone() or {}
            days = {}
            for row in rows:
                item = _row_to_profit(row)
                days[item["date"]] = item
            as_of = str(meta["as_of"]) if meta.get("as_of") else None
            yesterday = str(meta["yesterday"]) if meta.get("yesterday") else None
            if not yesterday and days:
                yesterday = max(days)
            if not as_of:
                as_of = today_str()
            return {"days": days, "as_of": as_of, "yesterday": yesterday}
        except Exception as exc:
            _warn(f"读利润失败（{exc}）")
        finally:
            conn.close()
    cache = _json_profit()
    days = cache.get("days")
    if not isinstance(days, dict):
        days = {}
    return {
        "days": days,
        "as_of": cache.get("as_of"),
        "yesterday": cache.get("yesterday"),
    }


def save_day_profit(pnl: dict, *, mark_yesterday: bool = False) -> None:
    today = today_str()
    day = str(pnl.get("date") or today)
    row = dict(pnl)
    if mark_yesterday:
        row["settled_on"] = today
    cache = _json_profit()
    days = cache.get("days")
    if not isinstance(days, dict):
        days = {}
    prev = days.get(day) if isinstance(days.get(day), dict) else {}
    merged = dict(prev)
    merged.update(row)
    if "n_listed" not in merged:
        merged["n_listed"] = int(prev.get("n_listed") or 0)
    days[day] = merged
    cache["days"] = days
    cache["as_of"] = today
    if mark_yesterday:
        cache["yesterday"] = day

    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO daily_profit ("
                    "profit_date, n_coin, n_pt, n_pair, n_redeem, coin_n, coin_pts, fee_c, "
                    "pt_n, pt_pts, fee_p, redeem_fee, net_coin, profit, n_listed, settled_on"
                    ") VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
                    ") ON DUPLICATE KEY UPDATE "
                    "n_coin=VALUES(n_coin), n_pt=VALUES(n_pt), n_pair=VALUES(n_pair), "
                    "n_redeem=VALUES(n_redeem), coin_n=VALUES(coin_n), coin_pts=VALUES(coin_pts), "
                    "fee_c=VALUES(fee_c), pt_n=VALUES(pt_n), pt_pts=VALUES(pt_pts), "
                    "fee_p=VALUES(fee_p), redeem_fee=VALUES(redeem_fee), net_coin=VALUES(net_coin), "
                    "profit=VALUES(profit), n_listed=VALUES(n_listed), "
                    "settled_on=COALESCE(VALUES(settled_on), settled_on)",
                    (
                        day,
                        int(merged.get("n_coin") or 0),
                        int(merged.get("n_pt") or 0),
                        int(merged.get("n_pair") or 0),
                        int(merged.get("n_redeem") or 0),
                        int(merged.get("coin_n") or 0),
                        int(merged.get("coin_pts") or 0),
                        int(merged.get("fee_c") or 0),
                        int(merged.get("pt_n") or 0),
                        int(merged.get("pt_pts") or 0),
                        int(merged.get("fee_p") or 0),
                        int(merged.get("redeem_fee") or 0),
                        int(merged.get("net_coin") or 0),
                        int(merged.get("profit") or 0),
                        int(merged.get("n_listed") or 0),
                        merged.get("settled_on"),
                    ),
                )
                if mark_yesterday:
                    cur.execute(
                        "INSERT INTO profit_meta (id, as_of, yesterday) VALUES (1, %s, %s) "
                        "ON DUPLICATE KEY UPDATE as_of=VALUES(as_of), yesterday=VALUES(yesterday)",
                        (today, day),
                    )
                else:
                    cur.execute(
                        "INSERT INTO profit_meta (id, as_of, yesterday) VALUES (1, %s, NULL) "
                        "ON DUPLICATE KEY UPDATE as_of=VALUES(as_of)",
                        (today,),
                    )
        except Exception as exc:
            _warn(f"写利润失败（{exc}），改写 json")
        finally:
            conn.close()
    _write_json_profit(cache)


def save_yesterday_profit(pnl: dict) -> None:
    save_day_profit(pnl, mark_yesterday=True)


def bump_today_listed(n: int = 1, item: Optional[dict] = None) -> None:
    today = today_str()
    cache = _json_profit()
    days = cache.get("days")
    if not isinstance(days, dict):
        days = {}
    row = days.get(today)
    if not isinstance(row, dict):
        row = {"date": today}
    row["n_listed"] = int(row.get("n_listed") or 0) + n
    days[today] = row
    cache["days"] = days
    cache["as_of"] = today
    conn = _connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO daily_profit (profit_date, n_listed) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE n_listed = n_listed + %s",
                    (today, n, n),
                )
        except Exception as exc:
            _warn(f"写今日已上架数失败（{exc}）")
        finally:
            conn.close()
    _write_json_profit(cache)
    if item:
        detail = load_day_detail(today)
        listed = list(detail.get("listed") or [])
        listed.insert(0, item)
        detail["listed"] = listed
        save_day_detail(detail)


def _append_market_log(kind: str, row: dict) -> None:
    with MARKET_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": kind, **row}, ensure_ascii=False) + "\n")


def save_market_snapshot(ts: str, payload: dict) -> None:
    """每轮扫描的分档盘口快照，供以后算各档价差、成交速度。"""
    conn = _connect()
    if conn is None:
        _append_market_log("snapshot", {"ts": ts, **payload})
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO market_snapshot (ts, payload_json) VALUES (%s, %s)",
                (ts, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
    except Exception as exc:
        _warn(f"写盘口快照失败（{exc}）")
    finally:
        conn.close()


def save_listing_submit(row: dict) -> None:
    """提交上架那一刻的定价与盘口上下文。"""
    conn = _connect()
    if conn is None:
        _append_market_log("submit", row)
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO listing_submit (ts, kind, coins, points, rate, book_top, "
                "book_second, avg5, profit, money, coin) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    row["ts"],
                    row["kind"],
                    int(row["coins"]),
                    int(row["points"]),
                    int(row["rate"]),
                    row.get("book_top"),
                    row.get("book_second"),
                    row.get("avg5"),
                    int(row.get("profit") or 0),
                    row.get("money"),
                    row.get("coin"),
                ),
            )
    except Exception as exc:
        _warn(f"写上架记录失败（{exc}）")
    finally:
        conn.close()


def sync_listing_track(now: str, opened: list[dict], closed: list[dict]) -> None:
    """自己的单：首次在「正在上架」看到记 first_seen，成交/赎回记 closed_at。

    first_seen 只精确到扫描间隔，分析时会用 listing_submit 的提交时间校正。
    """
    conn = _connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            if opened:
                cur.executemany(
                    "INSERT IGNORE INTO listing_track "
                    "(listing_id, kind, coins, points, rate, first_seen, status) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'open')",
                    [
                        (int(x["id"]), x["kind"], x["coins"], x["points"], x["rate"], now)
                        for x in opened
                    ],
                )
            if closed:
                cur.executemany(
                    "INSERT INTO listing_track "
                    "(listing_id, kind, coins, points, rate, closed_at, status) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE closed_at=IFNULL(closed_at, VALUES(closed_at)), "
                    "status=VALUES(status)",
                    [
                        (
                            int(x["id"]),
                            x["kind"],
                            x["coins"],
                            x["points"],
                            x["rate"],
                            x["when"] or None,
                            x["status"],
                        )
                        for x in closed
                    ],
                )
    except Exception as exc:
        _warn(f"同步挂单跟踪失败（{exc}）")
    finally:
        conn.close()


def import_json_files() -> dict[str, Any]:
    """把现有 json 灌进 MySQL（部署用）。"""
    conn = _connect()
    if conn is None:
        raise SystemExit("MySQL 未配置或连不上，无法导入")
    avg = _json_avg()
    profit = _json_profit()
    imported_avg = 0
    imported_days = 0
    try:
        with conn.cursor() as cur:
            if avg.get("date") and avg.get("point_avg") is not None:
                cur.execute(
                    "INSERT INTO avg_cache (cache_date, point_avg, coin_avg, n_point, n_coin) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE point_avg=VALUES(point_avg), coin_avg=VALUES(coin_avg), "
                    "n_point=VALUES(n_point), n_coin=VALUES(n_coin)",
                    (
                        avg["date"],
                        float(avg["point_avg"]),
                        float(avg["coin_avg"]),
                        int(avg.get("n_point") or 5),
                        int(avg.get("n_coin") or 5),
                    ),
                )
                imported_avg = 1
            days = profit.get("days")
            if isinstance(days, dict):
                for key, row in days.items():
                    if not isinstance(row, dict):
                        continue
                    cur.execute(
                        "INSERT INTO daily_profit ("
                        "profit_date, n_coin, n_pt, n_pair, n_redeem, coin_n, coin_pts, fee_c, "
                        "pt_n, pt_pts, fee_p, redeem_fee, net_coin, profit, settled_on"
                        ") VALUES ("
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
                        ") ON DUPLICATE KEY UPDATE "
                        "n_coin=VALUES(n_coin), n_pt=VALUES(n_pt), n_pair=VALUES(n_pair), "
                        "n_redeem=VALUES(n_redeem), coin_n=VALUES(coin_n), coin_pts=VALUES(coin_pts), "
                        "fee_c=VALUES(fee_c), pt_n=VALUES(pt_n), pt_pts=VALUES(pt_pts), "
                        "fee_p=VALUES(fee_p), redeem_fee=VALUES(redeem_fee), net_coin=VALUES(net_coin), "
                        "profit=VALUES(profit), settled_on=VALUES(settled_on)",
                        (
                            row.get("date") or key,
                            int(row.get("n_coin") or 0),
                            int(row.get("n_pt") or 0),
                            int(row.get("n_pair") or 0),
                            int(row.get("n_redeem") or 0),
                            int(row.get("coin_n") or 0),
                            int(row.get("coin_pts") or 0),
                            int(row.get("fee_c") or 0),
                            int(row.get("pt_n") or 0),
                            int(row.get("pt_pts") or 0),
                            int(row.get("fee_p") or 0),
                            int(row.get("redeem_fee") or 0),
                            int(row.get("net_coin") or 0),
                            int(row.get("profit") or 0),
                            row.get("settled_on"),
                        ),
                    )
                    imported_days += 1
            cur.execute(
                "INSERT INTO profit_meta (id, as_of, yesterday) VALUES (1, %s, %s) "
                "ON DUPLICATE KEY UPDATE as_of=VALUES(as_of), yesterday=VALUES(yesterday)",
                (profit.get("as_of") or today_str(), profit.get("yesterday")),
            )
    finally:
        conn.close()
    return {"avg": imported_avg, "days": imported_days}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--import-json", action="store_true")
    args = parser.parse_args()
    if args.import_json:
        result = import_json_files()
        print(f"已导入均价 {result['avg']} 条、利润 {result['days']} 天")
    else:
        print("avg", load_avg_latest())
        print("profit", load_profit())
