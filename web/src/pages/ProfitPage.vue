<script setup lang="ts">
import ChartBox from "@/components/ChartBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import Money from "@/components/Money.vue";
import SectionCard from "@/components/SectionCard.vue";
import { COLOR, categoryAxis, tip, valueAxis } from "@/charts/theme";
import { useOverviewStore } from "@/stores/overview";
import { fmt } from "@/utils/format";
import { dayFee, groupByMonth, movingAverage, summarizeDays, type MonthBucket } from "@/utils/profit";
import type { DayProfit } from "@/api/types";
import type { EChartsOption } from "echarts";
import { NButton, NDataTable, type DataTableColumns } from "naive-ui";
import { computed, h, ref } from "vue";

const overview = useOverviewStore();
const range = ref<"30" | "90" | "all">("30");
const days = computed(() => overview.data?.profit.days ?? []);
const chrono = computed(() => [...days.value].sort((a, b) => a.date.localeCompare(b.date)));
const totals = computed(() => summarizeDays(days.value));
const months = computed(() => groupByMonth(days.value));

const shown = computed(() => {
  if (range.value === "all") return chrono.value;
  return chrono.value.slice(-Number(range.value));
});

const option = computed<EChartsOption>(() => {
  const rows = shown.value;
  const fullMa = movingAverage(chrono.value.map((d) => d.profit), 7);
  const ma = fullMa.slice(chrono.value.length - rows.length);
  return {
    grid: { left: 56, right: 16, top: 28, bottom: rows.length > 20 ? 58 : 28 },
    tooltip: tip({ trigger: "axis" }),
    legend: { data: ["日利润", "7 日均"], textStyle: { color: COLOR.muted }, top: 0 },
    xAxis: categoryAxis(rows.map((d) => d.date.slice(5))),
    yAxis: valueAxis(),
    dataZoom: rows.length > 20 ? [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }] : undefined,
    series: [
      {
        name: "日利润",
        type: "bar",
        data: rows.map((d) => ({
          value: d.profit,
          itemStyle: { color: d.profit < 0 ? COLOR.bad : COLOR.mint },
        })),
      },
      {
        name: "7 日均",
        type: "line",
        data: ma,
        smooth: true,
        symbol: "none",
        connectNulls: false,
        lineStyle: { color: COLOR.gold, width: 2 },
      },
    ],
  };
});

const dayColumns: DataTableColumns<DayProfit> = [
  { title: "日期", key: "date", sorter: "default", defaultSortOrder: "descend" },
  { title: "卖币笔/量", key: "n_coin", render: (row) => `${row.n_coin} / ${row.coin_n}` },
  { title: "卖积分笔/量", key: "n_pt", render: (row) => `${row.n_pt} / ${row.pt_n}` },
  { title: "收款", key: "coin_pts", render: (row) => fmt(row.coin_pts) },
  { title: "挂出", key: "pt_pts", render: (row) => fmt(row.pt_pts) },
  { title: "手续费", key: "fee", render: (row) => fmt(dayFee(row)) },
  {
    title: "利润",
    key: "profit",
    sorter: (a, b) => a.profit - b.profit,
    render: (row) => h(Money, { value: row.profit, colored: true }),
  },
];

const monthColumns: DataTableColumns<MonthBucket> = [
  { title: "月份", key: "month" },
  { title: "天数", key: "days" },
  { title: "配对", key: "pairs", render: (row) => fmt(row.pairs) },
  { title: "手续费", key: "fee", render: (row) => fmt(row.fee) },
  { title: "利润", key: "profit", render: (row) => h(Money, { value: row.profit, colored: true }) },
];

const summary = computed(() => {
  if (!totals.value.days) return "";
  const worst = totals.value.worst ? `最差 ${totals.value.worst.date.slice(5)}（${fmt(totals.value.worst.profit)}）` : "";
  return `${totals.value.days} 天 · ${worst}`;
});

function exportCsv() {
  const header = ["日期", "卖币笔", "卖币量", "卖积分笔", "卖积分量", "收款", "挂出", "手续费", "利润", "赎回笔", "赎回费"];
  const lines = [header.join(",")];
  for (const d of chrono.value) {
    lines.push(
      [d.date, d.n_coin, d.coin_n, d.n_pt, d.pt_n, d.coin_pts, d.pt_pts, dayFee(d), d.profit, d.n_redeem, d.redeem_fee].join(","),
    );
  }
  const blob = new Blob([`\uFEFF${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "利润明细.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
</script>

<template>
  <section-card title="累计" :sub="summary">
    <div v-if="totals.days" class="sum">
      <div><span>累计利润</span><strong><money :value="totals.profit" colored /></strong></div>
      <div><span>日均</span><strong><money :value="totals.avg" colored /></strong></div>
      <div><span>配对</span><strong class="num">{{ fmt(totals.pairs) }} 套</strong></div>
      <div>
        <span>最好一天</span>
        <strong class="num">{{ totals.best?.date.slice(5) }} <money :value="totals.best?.profit" colored /></strong>
      </div>
    </div>
    <empty-state v-else text="还没有利润记录" />
  </section-card>

  <section-card title="趋势">
    <template #extra>
      <div class="seg">
        <n-button size="small" :type="range === '30' ? 'primary' : 'default'" @click="range = '30'">30 天</n-button>
        <n-button size="small" :type="range === '90' ? 'primary' : 'default'" @click="range = '90'">90 天</n-button>
        <n-button size="small" :type="range === 'all' ? 'primary' : 'default'" @click="range = 'all'">全部</n-button>
      </div>
    </template>
    <chart-box :option="option" height="320px" :empty="!shown.length" />
  </section-card>

  <section-card title="按月">
    <n-data-table
      v-if="months.length"
      size="small"
      :bordered="false"
      :columns="monthColumns"
      :data="months"
      :pagination="false"
    />
    <empty-state v-else text="还没有按月数据" />
  </section-card>

  <section-card title="每日明细">
    <template #extra>
      <n-button size="small" :disabled="!days.length" @click="exportCsv">导出 CSV</n-button>
    </template>
    <n-data-table
      v-if="days.length"
      size="small"
      :bordered="false"
      :columns="dayColumns"
      :data="days"
      :pagination="{ pageSize: 20 }"
      :scroll-x="760"
    />
    <empty-state v-else text="还没有利润记录" />
  </section-card>
</template>

<style scoped>
.sum { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.sum span { display: block; color: var(--muted); font-size: 12px; }
.sum strong { display: block; margin-top: 6px; font-size: 22px; font-weight: 650; }
.seg { display: flex; gap: 6px; }

@media (max-width: 800px) {
  .sum { grid-template-columns: 1fr 1fr; }
}
</style>
