export interface AuthResp {
  required: boolean;
  ok: boolean;
}

export interface AvgQuote {
  coins: number;
  points_listed: number;
  coin_list_price: number;
  low_unit: number;
  high_unit: number;
  low_rate: number;
  high_rate: number;
  fee_in: number;
  fee_out: number;
  spent: number;
  earned: number;
  profit: number;
  min_profit: number;
  point_avg: number;
  coin_avg: number;
  in_effective: number;
  out_effective: number;
  low_note: string;
  high_note: string;
  price_mode: string;
}

export interface ListedRow {
  id: string;
  kind: "sell_points" | "sell_coin" | string;
  side?: string;
  coins: number;
  points: number;
  rate: number | null;
  open?: boolean;
  status?: string;
  when?: string;
  text?: string;
}

export interface PairRow {
  coins: number;
  earn: number;
  cost: number;
  fee_c: number;
  fee_p: number;
  profit: number;
  coin_id?: string;
  pt_id?: string;
  coin_when?: string;
  pt_when?: string;
  formula?: string;
}

export interface DayProfit {
  date: string;
  n_coin: number;
  n_pt: number;
  n_pair: number;
  n_redeem: number;
  coin_n: number;
  coin_pts: number;
  fee_c: number;
  pt_n: number;
  pt_pts: number;
  fee_p: number;
  redeem_fee: number;
  net_coin: number;
  profit: number;
  n_listed: number;
  settled_on: string | null;
}

export interface BookLevel {
  best: number;
  second: number | null;
  n: number;
}

export interface MarketSnapshot {
  ts: string;
  hour: number;
  weekday: number;
  money: number;
  coin: number;
  point_avg: number;
  coin_avg: number;
  points_book: Record<string, BookLevel>;
  coins_book: Record<string, BookLevel>;
  mine: { sell_points: Record<string, number>; sell_coin: Record<string, number> };
  tier_profit: Record<string, { profit: number; per_coin: number }>;
  quote: { coins: number; low_unit: number; high_unit: number; profit: number } | null;
}

export interface Overview {
  today: string;
  avg: {
    date: string | null;
    point_avg: number | null;
    coin_avg: number | null;
    n_point: number;
    n_coin: number;
  };
  quote: AvgQuote | null;
  can_list: boolean;
  today_stats: { listed: number; sold: number; profit: number };
  today_detail: { date: string; listed: ListedRow[]; pairs: PairRow[]; redeem: ListedRow[] };
  profit: {
    as_of: string | null;
    yesterday: string | null;
    yesterday_row: DayProfit | null;
    days: DayProfit[];
  };
  market: MarketSnapshot | null;
  bot: {
    running: boolean;
    started_at: string | null;
    restarts: number;
    last_exit: number | null;
    autostart: boolean;
    state: string;
    label: string;
    next_at: string | null;
  };
  strategy: {
    list_coins: number;
    min_profit: number;
    min_profit_per_coin: number;
    front_depth: number;
  };
}

export interface LogsResp {
  running: boolean;
  seq: number;
  reset: boolean;
  lines: string[];
}

export interface BotActionResp {
  ok: boolean;
  state: string;
  running: boolean;
}

export interface TierStat {
  coins: number;
  both_ratio: number;
  points_seen: number;
  coins_seen: number;
  points_best: number | null;
  points_n: number | null;
  coins_best: number | null;
  coins_n: number | null;
  per_coin: number | null;
  ok_ratio: number | null;
}

export interface FillLead {
  kind: string;
  side: string;
  lead: number | null;
  label: string;
  n: number;
  median: number | null;
  mean: number | null;
}

export interface FillSlot {
  kind: string;
  side: string;
  hour: number;
  n: number;
  median: number | null;
  mean: number | null;
}

export interface HourlyGroup {
  days: number;
  per_day: number[];
  mean: number;
  suggested_peaks: number[];
  current_peaks: number[];
}

export interface Analysis {
  days: number;
  since: string;
  generated_at: string;
  min_profit_per_coin: number;
  peak_ratio: number;
  tiers: { snapshots: number; first: string | null; last: string | null; tiers: TierStat[] };
  fill: { sold: number; submits: number; matched: number; by_lead: FillLead[]; by_slot: FillSlot[] };
  hourly: { sold: number; weekday: HourlyGroup; weekend: HourlyGroup };
}
