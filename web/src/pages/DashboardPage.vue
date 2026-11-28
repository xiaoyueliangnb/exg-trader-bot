<script setup lang="ts">
import BookPanel from "@/components/BookPanel.vue";
import ChartBox from "@/components/ChartBox.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiCard from "@/components/KpiCard.vue";
import Money from "@/components/Money.vue";
import SectionCard from "@/components/SectionCard.vue";
import { COLOR, categoryAxis, tip, valueAxis } from "@/charts/theme";
import { useMarket } from "@/composables/useMarket";
import { useClockStore } from "@/stores/clock";
import { useLogsStore } from "@/stores/logs";
import { useOverviewStore } from "@/stores/overview";
import { ago, fmt, fmtSigned } from "@/utils/format";
import { logClass, matchLogFilter } from "@/utils/logLine";
import { summarizeDays } from "@/utils/profit";
import { NSkeleton } from "naive-ui";
import { computed } from "vue";
import type { EChartsOption } from "echarts";

const overview = useOverviewStore();
const logs = useLogsStore();
const clock = useClockStore();
const { live, listCoins, minProfit, liveOk } = useMarket();

const data = computed(() => overview.data);
const days = computed(() => data.value?.profit.days ?? []);
const today = computed(() => data.value?.today ?? "");
const todayStats = computed(() => data.value?.today_stats);
const yday = computed(() => data.value?.profit.yesterday_row);
const avg = computed(() => data.value?.avg);
const redeemN = computed(() => data.value?.today_detail.redeem.length ?? 0);

const month = computed(() => {
  const key = today.value.slice(0, 7);
  const rows = days.value.filter((d) => key && d.date.startsWith(key));
  return { key, ...summarizeDays(rows) };
});

const delta = computed(() => {
  if (!yday.value || !todayStats.value) return null;
  return todayStats.value.profit - yday.value.profit;
});

const recent = computed(() =>
  logs.lines.filter((line) => matchLogFilter(line, "trade") || matchLogFilter(line, "issue")).slice(-8),
);

const spark = computed<EChartsOption>(() => {
  const rows = [...days.value].sort((a, b) => a.date.localeCompare(b.date)).slice(-7);
  return {
    grid: { left: 4, right: 4, top: 12, bottom: 4 },
    tooltip: tip({
      trigger: "axis",
      formatter(params: unknown) {
        const p = (Array.isArray(params) ? params[0] : params) as { dataIndex?: number; value?: number };
        const row = rows[p?.dataIndex ?? 0];
        return row ? `${row.date}<br/>${fmt(row.profit)}` : "";
      },
    }),
    xAxis: { ...categoryAxis(rows.map((d) => d.date.slice(5))), show: false },
    yAxis: { ...valueAxis(), show: false },
    series: [
      {
        type: "line",
        data: rows.map((d) => d.profit),
        smooth: true,
        symbol: "none",
        lineStyle: { color: COLOR.gold, width: 2 },
        areaStyle: { color: "rgba(212, 176, 106, 0.16)" },
      },
    ],
  };
});

const bookSub = computed(() => (live.value ? `${live.value.ts.slice(11, 16)} 扫描 · ${ago(live.value.ts, clock.now)}` : ""));
</script>

<template>
  <error-state v-if="!data && overview.error" :text="overview.error" @retry="overview.pull()" />
  <div v-else-if="!data" class="grid">
    <n-skeleton v-for="i in 4" :key="i" height="96px" :sharp="false" />
  </div>
  <template v-else>
    <div class="grid">
      <kpi-card label="今日利润" :to="{ path: '/trade', query: { tab: 'profit' } }">
        <money :value="todayStats?.profit ?? 0" colored />
        <template #hint>
          <template v-if="yday">昨日 <money :value="yday.profit" colored />（较昨日全天 {{ fmtSigned(delta) }}）</template>
          <template v-else>昨日尚未结算</template>
        </template>
      </kpi-card>
      <kpi-card label="本月利润" to="/profit">
        <money :value="month.profit" colored />
        <template #hint>{{ month.key || "本月" }} · {{ month.days }} 天</template>
      </kpi-card>
      <kpi-card label="实盘每套利润" to="/trade">
        <money :value="live?.profit ?? null" colored />
        <template #hint>
          <template v-if="live?.profit == null">等第一轮扫描</template>
          <template v-else-if="liveOk">≥ {{ minProfit }}，可上架</template>
          <template v-else>&lt; {{ minProfit }}，不上架</template>
        </template>
      </kpi-card>
      <kpi-card label="账户余额">
        {{ live ? fmt(live.money) : "—" }}
        <template #hint>积分 · 交易币 {{ live ? fmt(live.coin) : "—" }}</template>
      </kpi-card>
    </div>

    <div class="mid">
      <section-card title="今日" :sub="today">
        <div class="trio">
          <router-link :to="{ path: '/trade', query: { tab: 'listed' } }">
            <span>已上</span><strong>{{ fmt(todayStats?.listed ?? 0) }}</strong>
          </router-link>
          <router-link :to="{ path: '/trade', query: { tab: 'sold' } }">
            <span>成交</span><strong>{{ fmt(todayStats?.sold ?? 0) }}</strong>
          </router-link>
          <router-link :to="{ path: '/trade', query: { tab: 'redeem' } }">
            <span>赎回</span><strong>{{ fmt(redeemN) }}</strong>
          </router-link>
        </div>
      </section-card>
      <section-card title="5 日均" :sub="avg?.date || '无缓存'">
        <p class="avg num">
          {{ avg?.point_avg != null ? fmt(avg.point_avg, 1) : "—" }}
          <small>/</small>
          {{ avg?.coin_avg != null ? fmt(avg.coin_avg, 1) : "—" }}
        </p>
        <p class="muted hint">卖积分不低于前者，卖交易币不高于后者</p>
      </section-card>
      <section-card title="近 7 天利润">
        <template #extra><router-link class="more" to="/profit">查看</router-link></template>
        <chart-box :option="spark" height="92px" :empty="days.length === 0" />
      </section-card>
    </div>

    <div class="mid lower">
      <section-card :title="`实时盘口 · ${listCoins} 币档`" :sub="bookSub">
        <template #extra><router-link class="more" to="/trade">详情</router-link></template>
        <book-panel compact />
      </section-card>
      <section-card title="最近日志">
        <template #extra><router-link class="more" to="/logs">全部</router-link></template>
        <div v-if="recent.length" class="mini-log">
          <p v-for="(line, i) in recent" :key="i" :class="logClass(line)">{{ line }}</p>
        </div>
        <p v-else class="muted">暂无交易或异常日志</p>
      </section-card>
    </div>
  </template>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.mid { display: grid; grid-template-columns: 1.05fr 0.95fr 1.15fr; gap: 12px; }
.lower { grid-template-columns: 1.4fr 1fr; }

.trio { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.trio a {
  display: block;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg-2);
}
.trio a:hover { border-color: var(--gold); }
.trio span { display: block; color: var(--muted); font-size: 12px; }
.trio strong { display: block; margin-top: 4px; font-size: 22px; font-variant-numeric: tabular-nums; }

.avg { margin: 0; font-size: 26px; font-weight: 650; }
.avg small { color: var(--muted); font-weight: 400; margin: 0 4px; }
.hint { margin: 8px 0 0; font-size: 12px; }
.more { color: var(--gold); font-size: 12px; }

.mini-log {
  max-height: 220px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
}
.mini-log p { margin: 0 0 4px; word-break: break-all; }

@media (max-width: 1024px) {
  .grid, .mid, .lower { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 720px) {
  .grid, .mid, .lower { grid-template-columns: 1fr; }
}
</style>
