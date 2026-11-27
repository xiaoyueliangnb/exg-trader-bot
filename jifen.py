#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易币 / 积分 利润计算。

上架规则来自抓包确认框：
  卖交易币：10 积分 / 币（赎回不退）
  卖积分：上架积分数量的 5%（赎回不退，按截断取整）
"""

# 上架交易币：10 积分 / 币
LISTING_FEE_PER_COIN = 10
MIN_LIST_COINS = 10

# 上架积分：数量的 5%
LIST_POINTS_FEE_RATE = 0.05
MIN_LIST_POINTS = 5000
LIST_COINS = 10  # 商家每套上架数量；单价按 5 日均取整
MIN_LIST_PROFIT = 50  # 两边成交利润低于这个数不上架
FRONT_DEPTH = 2  # 同一前排价最多留这么多份，给大户连买，卖不掉也不再堆


def listing_fee_coins(trade_coins, fee_per_coin=LISTING_FEE_PER_COIN):
    return trade_coins * fee_per_coin


def listing_fee_points(points_listed, fee_rate=LIST_POINTS_FEE_RATE):
    """上架积分手续费。6450 * 5% 站点收 322，用整数截断而不是四舍五入。"""
    if fee_rate == LIST_POINTS_FEE_RATE:
        return points_listed * 5 // 100
    return int(points_listed * fee_rate)


def listing_fee(trade_coins, fee_per_coin=LISTING_FEE_PER_COIN):
    return listing_fee_coins(trade_coins, fee_per_coin)


def instant_roundtrip_profit(points_spent, points_earned):
    """吃两边已有挂单：用积分买币，再用币买积分。即时成交无上架费。"""
    return points_earned - points_spent


def maker_list_coins_profit(points_spent, list_price, trade_coins, fee_per_coin=LISTING_FEE_PER_COIN):
    """买币后自己上架卖出。利润 = 标价 - 买入花费 - 10*币数。"""
    return list_price - points_spent - listing_fee_coins(trade_coins, fee_per_coin)


def maker_list_profit(points_spent, list_price, trade_coins, fee_per_coin=LISTING_FEE_PER_COIN):
    return maker_list_coins_profit(points_spent, list_price, trade_coins, fee_per_coin)


def maker_list_points_for_coins(
    points_listed,
    coins_asked,
    market_buy_rate,
    fee_rate=LIST_POINTS_FEE_RATE,
):
    """
    挂积分换币：上架 points_listed 积分，标价 coins_asked 个币。

    相对「直接去买交易币」：
      市场买币花费 = coins_asked * market_buy_rate
      自己挂积分花费 = 上架积分 + 5% 手续费
      利润 = 市场买币花费 - 自己总花费（省下的积分；负值表示更亏）
    """
    fee = listing_fee_points(points_listed, fee_rate)
    total_spent = points_listed + fee
    market_cost = coins_asked * market_buy_rate
    profit = market_cost - total_spent
    effective_rate = (total_spent / coins_asked) if coins_asked else 0.0
    list_rate = (points_listed / coins_asked) if coins_asked else 0.0
    return {
        "points_listed": points_listed,
        "coins_asked": coins_asked,
        "list_rate": list_rate,
        "fee": fee,
        "total_spent": total_spent,
        "effective_rate": effective_rate,
        "market_buy_rate": market_buy_rate,
        "market_cost": market_cost,
        "profit": profit,
    }


def vs_avg(price, avg):
    """现价相对均价，正数表示高于均价。"""
    return price - avg


def list_unit_from_avg(avg5):
    return int(round(avg5))


def align_points_lot(list_rate, coins=MIN_LIST_COINS, min_points=MIN_LIST_POINTS):
    points = int(round(list_rate * coins))
    if points < min_points:
        points = ((min_points + coins - 1) // coins) * coins
    return points, coins


def merchant_list_cycle(points_listed, coins, coin_list_price):
    """
    商家上架闭环（抓包实走，不是吃零售盘）：
      卖积分：上架 points_listed 积分，标价 coins 个交易币，手续费 5%
      卖交易币：上架 coins 个币，标价 coin_list_price 积分，手续费 10/币

    利润 = 卖币标价 - (卖积分本体 + 卖积分*5% + 10*币)
    抓包：6450 换 10 币、10 币换 6950 → 6950 - (6450 + 322 + 100) = 78
    """
    fee_in = listing_fee_points(points_listed)
    fee_out = listing_fee_coins(coins)
    spent = points_listed + fee_in
    profit = coin_list_price - spent - fee_out
    return {
        "coins": coins,
        "points_listed": points_listed,
        "coin_list_price": coin_list_price,
        "low_rate": points_listed / coins if coins else 0.0,
        "high_rate": coin_list_price / coins if coins else 0.0,
        "fee_in": fee_in,
        "fee_out": fee_out,
        "spent": spent,
        "earned": coin_list_price,
        "in_effective": spent / coins if coins else 0.0,
        "out_effective": (coin_list_price - fee_out) / coins if coins else 0.0,
        "profit": profit,
    }


def listing_quotes_from_avg(point_avg, coin_avg, coins=LIST_COINS):
    """实际上架价 = 两侧 5 日均取整。卖积分跟买积分均价，卖交易币跟买交易币均价。"""
    low_unit = list_unit_from_avg(point_avg)
    high_unit = list_unit_from_avg(coin_avg)
    points_listed = max(low_unit * coins, MIN_LIST_POINTS)
    cycle = merchant_list_cycle(points_listed, coins, high_unit * coins)
    cycle["low_unit"] = low_unit
    cycle["high_unit"] = high_unit
    cycle["point_avg"] = point_avg
    cycle["coin_avg"] = coin_avg
    cycle["price_mode"] = "avg5"
    cycle["low_note"] = "5日均取整"
    cycle["high_note"] = "5日均取整"
    return cycle


def _rate_counts(my_rates) -> dict[int, int]:
    counts: dict[int, int] = {}
    for rate in my_rates or []:
        if rate is None:
            continue
        key = int(round(float(rate)))
        counts[key] = counts.get(key, 0) + 1
    return counts


def decide_list_side(market_rate, my_rates, avg5, *, direction):
    """
    卖积分不低于 5 日均（更高可以），卖交易币不高于 5 日均（更低可以）。
    排不进第一就本轮不新增。
    前排同一价最多留 FRONT_DEPTH 份：不足就本轮补 1 份，满了才维持。
    返回 (unit, note, skip_reason, behind, depth_short)。
    depth_short 表示本轮挂完后前排仍不足 2 份，应很快再补。
    """
    avg_u = list_unit_from_avg(avg5) if avg5 is not None else None
    counts = _rate_counts(my_rates)

    def pack(unit, note, skip, behind, have):
        adding = 0 if skip else 1
        short = (not behind) and (have + adding < FRONT_DEPTH)
        return unit, note, skip, behind, short

    if market_rate is None:
        if avg_u is None:
            return None, "无盘口也无均价", "无定价", False, False
        have = counts.get(avg_u, 0)
        if have >= FRONT_DEPTH:
            return pack(
                avg_u,
                f"无盘口，前排已有{have}份@{avg_u}，维持",
                f"已有{have}份@{avg_u}，维持",
                False,
                have,
            )
        if have:
            return pack(avg_u, f"无盘口，仅{have}份@{avg_u}，再补1份", "", False, have)
        return pack(avg_u, f"无盘口，用5日均{avg_u}，先挂1份", "", False, 0)

    top = int(round(float(market_rate)))
    have_top = counts.get(top, 0)
    # 自己已在第一，且这个价没有越过均价限制，才在原价上补到 2 份。
    top_allowed = True
    if avg_u is not None:
        top_allowed = top >= avg_u if direction == "over" else top <= avg_u
    if have_top and top_allowed:
        if have_top >= FRONT_DEPTH:
            return pack(
                top,
                f"盘口最优 {top} 已有{have_top}份，维持",
                f"已有{have_top}份@{top}，维持",
                False,
                have_top,
            )
        return pack(top, f"盘口最优 {top} 仅{have_top}份，再补1份", "", False, have_top)

    if direction == "under":
        raw = max(top - 1, 1)
        note = f"盘口最优 {top}，抢排序 {raw}（-1）"
        if avg_u is not None and raw > avg_u:
            note = f"{note}，高于5日均{avg_u}→改挂{avg_u}"
            unit = avg_u
        else:
            unit = raw
        in_front = unit < top
    else:
        raw = top + 1
        note = f"盘口最优 {top}，抢排序 {raw}（+1）"
        if avg_u is not None and raw < avg_u:
            note = f"{note}，低于5日均{avg_u}→改挂{avg_u}"
            unit = avg_u
        else:
            unit = raw
        in_front = unit > top

    have = counts.get(unit, 0)
    if not in_front:
        why = "现挂落后，本轮不新增" if counts else "排不进第一，本轮不新增"
        return unit, f"{note}；{why}", why, True, False
    if have >= FRONT_DEPTH:
        return pack(unit, f"{note}；已有{have}份@{unit}，维持", f"已有{have}份@{unit}，维持", False, have)
    if have:
        return pack(unit, f"{note}；仅{have}份，再补1份", "", False, have)
    return pack(unit, f"{note}；先挂1份", "", False, 0)


def listing_quotes_competitive(
    point_avg,
    coin_avg,
    market_point_rate,
    market_coin_rate,
    my_point_rates=None,
    my_coin_rates=None,
    coins=LIST_COINS,
):
    """
    先按盘口 ±1，再用 5 日均卡住亏的那一侧：
      卖积分不低于均价（更高可以），卖交易币不高于均价（更低可以）
      改完仍排不进第一则该侧不新增
      前排同一价不足 2 份则补 1 份，满 2 份才维持
    """
    low_unit, low_note, skip_points, behind_points, short_points = decide_list_side(
        market_point_rate,
        my_point_rates,
        point_avg,
        direction="over",
    )
    high_unit, high_note, skip_coins, behind_coins, short_coins = decide_list_side(
        market_coin_rate,
        my_coin_rates,
        coin_avg,
        direction="under",
    )
    if low_unit is None or high_unit is None:
        return None
    points_listed = max(low_unit * coins, MIN_LIST_POINTS)
    cycle = merchant_list_cycle(points_listed, coins, high_unit * coins)
    cycle["low_unit"] = low_unit
    cycle["high_unit"] = high_unit
    cycle["point_avg"] = point_avg
    cycle["coin_avg"] = coin_avg
    cycle["market_point_rate"] = (
        float(market_point_rate) if market_point_rate is not None else None
    )
    cycle["market_coin_rate"] = (
        float(market_coin_rate) if market_coin_rate is not None else None
    )
    cycle["price_mode"] = "market"
    cycle["low_note"] = low_note
    cycle["high_note"] = high_note
    cycle["skip_points"] = skip_points or ""
    cycle["skip_coins"] = skip_coins or ""
    cycle["behind_points"] = bool(behind_points)
    cycle["behind_coins"] = bool(behind_coins)
    cycle["depth_short_points"] = bool(short_points)
    cycle["depth_short_coins"] = bool(short_coins)
    # 兼容旧字段：有跳过原因即视为 hold
    cycle["hold_points"] = bool(skip_points)
    cycle["hold_coins"] = bool(skip_coins)
    return cycle


def low_high_maker_cycle(low_rate, high_rate, coins=MIN_LIST_COINS):
    return listing_quotes_from_avg(low_rate, high_rate, coins)


def calc_profit_by_rates(
    trade_coins,
    buy_rate,
    sell_rate,
    listing=False,
    fee_per_coin=LISTING_FEE_PER_COIN,
):
    points_spent = trade_coins * buy_rate
    points_earned = trade_coins * sell_rate
    fee = listing_fee_coins(trade_coins, fee_per_coin) if listing else 0
    profit = points_earned - points_spent - fee
    return {
        "trade_coins": trade_coins,
        "buy_rate": buy_rate,
        "sell_rate": sell_rate,
        "points_spent": points_spent,
        "points_earned": points_earned,
        "listing_fee": fee,
        "profit": profit,
    }


if __name__ == "__main__":
    avg = listing_quotes_from_avg(637.6, 691.4, LIST_COINS)
    print(
        f"实际上架价（5日均）：卖积分 {avg['points_listed']} 积分标 {avg['coins']} 币（{avg['low_unit']}/币），"
        f"卖交易币 {avg['coins']} 币标 {avg['earned']}（{avg['high_unit']}/币），"
        f"手续费 {avg['fee_in']}+{avg['fee_out']}，利润 {avg['profit']}"
    )
