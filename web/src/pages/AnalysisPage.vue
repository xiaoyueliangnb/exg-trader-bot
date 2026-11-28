<script setup lang="ts">
import ChartBox from "@/components/ChartBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import SectionCard from "@/components/SectionCard.vue";
import { ApiError } from "@/api/client";
import { getAnalysis } from "@/api/endpoints";
import type { Analysis, HourlyGroup, TierStat } from "@/api/types";
import { COLOR, categoryAxis, tip, valueAxis } from "@/charts/theme";
import { useOverviewStore } from "@/stores/overview";
import { fmt, hourBands, hourRanges, pad, pct, peakDiff } from "@/utils/format";
import { MIN_FILL_SAMPLE } from "@/utils/schedule";
import { useLocalStorage } from "@vueuse/core";
import type { EChartsOption } from "echarts";
import { NButton, NDataTable, NRadioButton, NRadioGroup, NSpin, NTag, type DataTableColumns } from "naive-ui";
import { computed, h, onMounted, ref, watch } from "vue";

const overview = useOverviewStore();
const days = useLocalStorage("jifen_analysis_days", 14);
const data = ref<Analysis | null>(null);
const loading = ref(false);
const error = ref("");
const fillSide = ref<"sell_points" | "sell_coin">("sell_points");
const ranges = [7, 14, 30, 60];

const listCoins = computed(() => overview.data?.strategy.list_coins ?? 10);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await getAnalysis(Number(days.value) || 14);
  } catch (err) {
    error.value = err instanceof ApiError && err.status === 503 ? "数据库连不上，分析需要 MySQL 里的快照数据" : "加载失败";
  } finally {
    loading.value = false;
  }
}

watch(days, () => void load());
onMounted(load);

const groups = computed(() => {
  const hourly = data.value?.hourly;
  if (!hourly) return [];
  return [
    { key: "weekday", name: "工作日", ...hourly.weekday },
    { key: "weekend", name: "周末", ...hourly.weekend },
  ].map((group) => {
    const diff = peakDiff(group.current_peaks || [], group.suggested_peaks || []);
    return { ...group, ...diff, total: group.per_day.reduce((s, v) => s + v, 0) };
  });
});

function hourlyOption(group: HourlyGroup): EChartsOption {
  const sug = new Set(group.suggested_peaks);
  const bands = hourBands(group.current_peaks || []);
  return {
    grid: { left: 36, right: 8, top: 16, bottom: 28 },
    tooltip: {
      ...tip({ trigger: "axis" }),
      formatter(params: unknown) {
        const p = (Array.isArray(params) ? params[0] : params) as { dataIndex?: number };
        const h = p?.dataIndex ?? 0;
        return `${pad(h)}:00–${pad(h + 1)}:00<br/>每天平均 ${fmt(group.per_day[h] ?? 0, 1)} 张`;
      },
    },
    xAxis: categoryAxis(Array.from({ length: 24 }, (_, h) => pad(h))),
    yAxis: valueAxis(),
    series: [
      {
        type: "bar",
        data: group.per_day.map((v, h) => ({
          value: Number(v.toFixed(2)),
          itemStyle: { color: sug.has(h) ? COLOR.gold : COLOR.mint, opacity: sug.has(h) ? 1 : 0.55 },
        })),
        markArea: bands.length
          ? {
              silent: true,
              itemStyle: { color: "rgba(212, 176, 106, 0.12)" },
              data: bands.map(([a, b]) => [{ xAxis: pad(a) }, { xAxis: pad(Math.max(a, b - 1)) }]),
            }
          : undefined,
      },
    ],
  };
}

const sideCount = computed(() => {
  const out = { sell_points: 0, sell_coin: 0 };
  for (const row of data.value?.fill.by_lead ?? []) {
    if (row.kind === "sell_points" || row.kind === "sell_coin") out[row.kind] += row.n;
  }
  return out;
});

watch(sideCount, (count) => {
  const other = fillSide.value === "sell_points" ? "sell_coin" : "sell_points";
  if (!count[fillSide.value] && count[other]) fillSide.value = other;
});

const leadRows = computed(() => (data.value?.fill.by_lead ?? []).filter((row) => row.kind === fillSide.value));

const slotRows = computed(() => {
  const rows = (data.value?.fill.by_slot ?? []).filter((row) => row.kind === fillSide.value);
  const map = new Map(rows.map((row) => [row.hour, row]));
  return [0, 3, 6, 9, 12, 15, 18, 21].map((hour) => ({ hour, row: map.get(hour) ?? null }));
});

function barOption(labels: string[], values: Array<number | null>, color: string): EChartsOption {
  return {
    grid: { left: 78, right: 36, top: 8, bottom: 24 },
    tooltip: tip({ trigger: "axis" }),
    xAxis: valueAxis("分钟"),
    yAxis: { ...categoryAxis(labels), inverse: true },
    series: [
      {
        type: "bar",
        data: values,
        itemStyle: { color },
        label: { show: true, position: "right", color: COLOR.muted },
      },
    ],
  };
}

const leadOption = computed(() =>
  barOption(
    leadRows.value.map((row) => row.label),
    leadRows.value.map((row) => (row.median == null ? null : Number(row.median.toFixed(1)))),
    COLOR.gold,
  ),
);

const slotOption = computed(() =>
  barOption(
    slotRows.value.map((row) => `${pad(row.hour)}–${pad(row.hour + 3)}`),
    slotRows.value.map((row) => (row.row?.median == null ? null : Number(row.row.median.toFixed(1)))),
    COLOR.mint,
  ),
);

const tierRows = computed(() => {
  const rows = data.value?.tiers.tiers ?? [];
  const min = data.value?.min_profit_per_coin ?? 5;
  return rows
    .map((row) => ({
      ...row,
      candidate: row.both_ratio >= 0.5 && row.per_coin != null && row.per_coin >= min,
    }))
    .sort((a, b) => b.both_ratio - a.both_ratio || a.coins - b.coins);
});

const tierColumns = computed<DataTableColumns<(typeof tierRows.value)[number]>>(() => [
  { title: "档位", key: "coins", render: (row) => `${row.coins} 币` },
  {
    title: "两边都有盘",
    key: "both_ratio",
    render: (row) =>
      h("span", [
        h("i", { class: "ratio-track" }, [h("i", { style: { width: `${row.both_ratio * 100}%` } })]),
        pct(row.both_ratio),
      ]),
  },
  {
    title: "卖积分第一",
    key: "points_best",
    render: (row) => `${fmt(row.points_best, 1)} · 出现 ${pct(row.points_seen)}`,
  },
  {
    title: "卖币第一",
    key: "coins_best",
    render: (row) => `${fmt(row.coins_best, 1)} · 出现 ${pct(row.coins_seen)}`,
  },
  {
    title: "±1 每币利润",
    key: "per_coin",
    render: (row) => {
      if (row.per_coin == null) return "单边";
      const cls = data.value && row.per_coin >= data.value.min_profit_per_coin ? "good" : "bad";
      return h("span", { class: cls }, fmt(row.per_coin, 2));
    },
  },
  { title: "达标占比", key: "ok_ratio", render: (row) => pct(row.ok_ratio) },
  {
    title: "",
    key: "tag",
    render: (row) => {
      if (row.coins === listCoins.value) return h(NTag, { size: "small", bordered: false }, { default: () => "在做" });
      if (row.candidate) return h(NTag, { size: "small", type: "success", bordered: false }, { default: () => "可考虑开放" });
      return "";
    },
  },
]);

function tierClass(row: TierStat) {
  return row.coins === listCoins.value ? "is-current" : "";
}
</script>

<template>
  <div class="toolbar">
    <n-radio-group v-model:value="days" size="small">
      <n-radio-button v-for="n in ranges" :key="n" :value="n">近 {{ n }} 天</n-radio-button>
    </n-radio-group>
    <span v-if="data" class="muted">{{ data.since }} 至今 · 生成于 {{ data.generated_at.slice(11, 16) }}</span>
    <n-button size="small" :loading="loading" @click="load">刷新</n-button>
  </div>

  <p v-if="error" class="banner">{{ error }}</p>

  <n-spin :show="loading && !data">
    <div v-if="data" class="stack">
      <section-card title="成交时段" :sub="`自己的单按成交时间统计，共 ${data.hourly.sold} 张 · 柱高为每天平均张数`">
        <div class="legend">
          <span><i class="sw gold" />建议高峰（≥ 平均 {{ data.peak_ratio }} 倍）</span>
          <span><i class="sw mint" />其它小时</span>
          <span><i class="sw area" />当前按高峰轮询</span>
        </div>
        <div v-for="group in groups" :key="group.key" class="block">
          <div class="head">
            <b>{{ group.name }}</b>
            <span class="muted">{{ group.days }} 天样本 · 日均 {{ fmt(group.total, 1) }} 张</span>
          </div>
          <chart-box v-if="group.days" :option="hourlyOption(group)" height="220px" />
          <empty-state v-else text="没有数据" />
          <p v-if="group.days" class="verdict">
            当前高峰：{{ hourRanges(group.current_peaks || []) }} 点；建议高峰：{{ hourRanges(group.suggested_peaks) }} 点。
            <span v-if="!group.add.length && !group.drop.length" class="good">完全一致，不用改。</span>
            <template v-else>
              <span v-if="group.add.length">建议加为高峰 <b>{{ group.add.map(pad).join("、") }}</b> 点；</span>
              <span v-if="group.drop.length">成交偏少可降为平峰 <b>{{ group.drop.map(pad).join("、") }}</b> 点。</span>
              <span class="muted">相差 2 个小时以上再改，见 PLAN.md。</span>
            </template>
          </p>
        </div>
      </section-card>

      <section-card
        title="成交速度"
        :sub="`挂出到成交的分钟数 · 对上提交记录 ${data.fill.matched} 张 / 期间成交 ${data.fill.sold} 张`"
      >
        <template #extra>
          <n-radio-group v-model:value="fillSide" size="small">
            <n-radio-button value="sell_points">卖积分（{{ sideCount.sell_points }}）</n-radio-button>
            <n-radio-button value="sell_coin">卖交易币（{{ sideCount.sell_coin }}）</n-radio-button>
          </n-radio-group>
        </template>
        <p v-if="data.fill.matched < MIN_FILL_SAMPLE" class="note">
          样本只有 {{ data.fill.matched }} 张（新采集 2026-11-28 开始），{{ MIN_FILL_SAMPLE }} 张以上再据此调价。
        </p>
        <div v-if="leadRows.length" class="speed">
          <div>
            <p class="sub">按挂单时相对盘口第一（领先 = 比别人更优）</p>
            <chart-box :option="leadOption" :height="`${Math.max(160, leadRows.length * 36)}px`" />
          </div>
          <div>
            <p class="sub">按挂单时段（中位分钟）</p>
            <chart-box :option="slotOption" height="280px" />
          </div>
        </div>
        <empty-state v-else text="这个方向还没有能对上提交记录的成交单。" />
      </section-card>

      <section-card title="分档盘口" :sub="`快照 ${data.tiers.snapshots} 次 · 数值为期间中位数`">
        <p class="note">
          开放条件（PLAN.md）：两边同时有盘 ≥ 50%，且 ±1 每币利润中位 ≥ {{ data.min_profit_per_coin }}。
          ±1 每币利润 = 两边都按该档盘口第一 ±1 挂、扣双边手续费后每币赚多少（未套均价护栏）。
        </p>
        <n-data-table
          v-if="tierRows.length"
          size="small"
          :bordered="false"
          :columns="tierColumns"
          :data="tierRows"
          :pagination="false"
          :row-class-name="tierClass"
          :scroll-x="920"
        />
        <empty-state v-else text="还没有快照。自动上架每轮扫描会记一次。" />
      </section-card>
    </div>
  </n-spin>
</template>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.toolbar .muted { margin-left: auto; font-size: 12px; }
.stack { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 12px; margin-bottom: 8px; }
.sw { display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: -1px; }
.sw.gold { background: var(--gold); }
.sw.mint { background: var(--mint); opacity: 0.7; }
.sw.area { background: rgba(212, 176, 106, 0.18); border: 1px dashed rgba(212, 176, 106, 0.6); }
.block + .block { margin-top: 18px; }
.head { display: flex; gap: 12px; align-items: baseline; margin-bottom: 4px; font-size: 13px; }
.verdict { margin: 8px 0 0; font-size: 13px; line-height: 1.7; }
.verdict b { color: var(--gold); }
.note { margin: 0 0 12px; color: var(--warn); font-size: 12.5px; line-height: 1.6; }
.speed { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.sub { margin: 0 0 8px; color: var(--muted); font-size: 12px; }
:deep(.is-current td) { color: var(--gold); }

@media (max-width: 900px) {
  .speed { grid-template-columns: 1fr; }
  .toolbar .muted { margin-left: 0; }
}
</style>
