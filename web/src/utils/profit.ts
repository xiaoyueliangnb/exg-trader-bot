export interface RoundParts {
  listed: number;
  feeIn: number;
  feeOut: number;
  earned: number;
  profit: number;
}

/** 卖积分费 = 挂出积分 × 5% 向下取整；卖币费 = 每币 10。 */
export function roundProfit(pointUnit: number, coinUnit: number, coins: number): RoundParts {
  const listed = pointUnit * coins;
  const feeIn = Math.floor(listed * 0.05);
  const feeOut = coins * 10;
  const earned = coinUnit * coins;
  return { listed, feeIn, feeOut, earned, profit: earned - listed - feeIn - feeOut };
}

export function movingAverage(values: number[], window: number): (number | null)[] {
  if (window <= 0) return values.map(() => null);
  return values.map((_, i) => {
    if (i < window - 1) return null;
    let sum = 0;
    for (let j = i - window + 1; j <= i; j += 1) sum += values[j] ?? 0;
    return sum / window;
  });
}

export interface DayLike {
  date: string;
  profit: number;
  n_pair: number;
  fee_c?: number;
  fee_p?: number;
}

export interface DaySummary<T> {
  profit: number;
  pairs: number;
  days: number;
  avg: number;
  best: T | null;
  worst: T | null;
}

export function summarizeDays<T extends DayLike>(days: T[]): DaySummary<T> {
  const profit = days.reduce((s, d) => s + Number(d.profit || 0), 0);
  const pairs = days.reduce((s, d) => s + Number(d.n_pair || 0), 0);
  let best: T | null = null;
  let worst: T | null = null;
  for (const d of days) {
    if (!best || d.profit > best.profit) best = d;
    if (!worst || d.profit < worst.profit) worst = d;
  }
  return {
    profit,
    pairs,
    days: days.length,
    avg: days.length ? Math.round(profit / days.length) : 0,
    best,
    worst,
  };
}

export interface MonthBucket {
  month: string;
  days: number;
  pairs: number;
  fee: number;
  profit: number;
}

export function groupByMonth<T extends DayLike>(days: T[]): MonthBucket[] {
  const map = new Map<string, MonthBucket>();
  for (const d of days) {
    const month = d.date.slice(0, 7);
    const row = map.get(month) ?? { month, days: 0, pairs: 0, fee: 0, profit: 0 };
    row.days += 1;
    row.pairs += Number(d.n_pair || 0);
    row.fee += Number(d.fee_c || 0) + Number(d.fee_p || 0);
    row.profit += Number(d.profit || 0);
    map.set(month, row);
  }
  return [...map.values()].sort((a, b) => b.month.localeCompare(a.month));
}

export function dayFee(row: { fee_c?: number; fee_p?: number }): number {
  return Number(row.fee_c || 0) + Number(row.fee_p || 0);
}

export function sideLabel(row: { side?: string; kind?: string }): string {
  return row.side || (row.kind === "sell_coin" ? "卖交易币" : "卖积分");
}
