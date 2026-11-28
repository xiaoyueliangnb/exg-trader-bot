import { useClockStore } from "@/stores/clock";
import { useOverviewStore } from "@/stores/overview";
import { parseTime } from "@/utils/format";
import { roundProfit } from "@/utils/profit";
import { computed } from "vue";

export function useMarket() {
  const overview = useOverviewStore();
  const clock = useClockStore();
  const data = computed(() => overview.data);
  const strategy = computed(() => data.value?.strategy);
  const listCoins = computed(() => strategy.value?.list_coins ?? 10);
  const minProfit = computed(() => strategy.value?.min_profit ?? 50);
  const minPerCoin = computed(() => strategy.value?.min_profit_per_coin ?? 5);
  const frontDepth = computed(() => strategy.value?.front_depth ?? 3);
  const market = computed(() => data.value?.market ?? null);
  const tierKey = computed(() => String(listCoins.value));

  const live = computed(() => {
    const m = market.value;
    if (!m) return null;
    const t = tierKey.value;
    const q = m.quote;
    return {
      ts: m.ts,
      money: m.money,
      coin: m.coin,
      points: {
        best: m.points_book?.[t]?.best ?? null,
        second: m.points_book?.[t]?.second ?? null,
        mine: m.mine?.sell_points?.[t] ?? 0,
        price: q?.low_unit ?? null,
        guard: m.point_avg,
      },
      coins: {
        best: m.coins_book?.[t]?.best ?? null,
        second: m.coins_book?.[t]?.second ?? null,
        mine: m.mine?.sell_coin?.[t] ?? 0,
        price: q?.high_unit ?? null,
        guard: m.coin_avg,
      },
      profit: q?.profit ?? null,
      coinsN: q?.coins ?? listCoins.value,
    };
  });

  const parts = computed(() => {
    const row = live.value;
    if (!row || row.points.price == null || row.coins.price == null) return null;
    return roundProfit(row.points.price, row.coins.price, row.coinsN);
  });

  const edge = computed(() => market.value?.tier_profit?.[tierKey.value] ?? null);
  const showEdge = computed(
    () => edge.value != null && live.value?.profit != null && edge.value.profit > live.value.profit,
  );
  const liveOk = computed(() => live.value?.profit != null && live.value.profit >= minProfit.value);

  const snapMinutes = computed(() => {
    const ts = market.value?.ts;
    if (!ts) return null;
    return (clock.now - parseTime(ts)) / 60000;
  });
  const snapOld = computed(() => snapMinutes.value != null && snapMinutes.value > 40);

  const tiers = computed(() => {
    const m = market.value;
    if (!m) return [];
    const keys = new Set([...Object.keys(m.points_book || {}), ...Object.keys(m.coins_book || {})]);
    return [...keys]
      .map(Number)
      .sort((a, b) => a - b)
      .map((coins) => ({
        coins,
        points: m.points_book?.[String(coins)] ?? null,
        coinsBook: m.coins_book?.[String(coins)] ?? null,
        edge: m.tier_profit?.[String(coins)] ?? null,
      }));
  });

  return {
    data,
    strategy,
    listCoins,
    minProfit,
    minPerCoin,
    frontDepth,
    market,
    live,
    parts,
    edge,
    showEdge,
    liveOk,
    snapOld,
    tiers,
  };
}
