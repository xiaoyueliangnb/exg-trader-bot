<script setup lang="ts">
import BookPanel from "@/components/BookPanel.vue";
import EmptyState from "@/components/EmptyState.vue";
import Money from "@/components/Money.vue";
import SectionCard from "@/components/SectionCard.vue";
import { useMarket } from "@/composables/useMarket";
import { useClockStore } from "@/stores/clock";
import { useOverviewStore } from "@/stores/overview";
import { ago, fmt } from "@/utils/format";
import { dayFee, sideLabel } from "@/utils/profit";
import type { ListedRow, PairRow } from "@/api/types";
import { NDataTable, NTabPane, NTabs, type DataTableColumns } from "naive-ui";
import { computed, h } from "vue";
import { useRoute, useRouter } from "vue-router";

const overview = useOverviewStore();
const clock = useClockStore();
const route = useRoute();
const router = useRouter();
const { live, listCoins, tiers, minPerCoin, snapOld } = useMarket();

const detail = computed(() => overview.data?.today_detail);
const stats = computed(() => overview.data?.today_stats);
const tabs = ["listed", "sold", "profit", "redeem"] as const;

const tab = computed({
  get() {
    const q = String(route.query.tab || "listed");
    return (tabs as readonly string[]).includes(q) ? q : "listed";
  },
  set(value: string) {
    void router.replace({ query: { tab: value } });
  },
});

const bookSub = computed(() => {
  if (!live.value) return snapOld.value ? "快照较旧" : "";
  return `${live.value.ts.slice(11, 16)} 扫描 · ${ago(live.value.ts, clock.now)}`;
});

const tierColumns = computed<DataTableColumns<(typeof tiers.value)[number]>>(() => [
  { title: "币数", key: "coins", render: (row) => `${row.coins} 币` },
  { title: "卖积分第一", key: "points", render: (row) => fmt(row.points?.best) },
  { title: "卖币第一", key: "coinsBook", render: (row) => fmt(row.coinsBook?.best) },
  {
    title: "±1 每币利润",
    key: "edge",
    render: (row) => {
      if (!row.edge) return "单边";
      const cls = row.edge.per_coin >= minPerCoin.value ? "good" : "bad";
      return h("span", { class: cls }, fmt(row.edge.per_coin, 1));
    },
  },
]);

function rowClass(row: { coins: number }) {
  return row.coins === listCoins.value ? "is-current" : "";
}

const listedColumns: DataTableColumns<ListedRow> = [
  { title: "时间", key: "when", render: (row) => row.when || "—" },
  { title: "方向", key: "side", render: (row) => sideLabel(row) },
  {
    title: "数量",
    key: "qty",
    render: (row) => (row.kind === "sell_points" ? `${fmt(row.points)} 积分` : `${fmt(row.coins)} 币`),
  },
  {
    title: "标价",
    key: "price",
    render: (row) => (row.kind === "sell_points" ? `${fmt(row.coins)} 币` : `${fmt(row.points)} 积分`),
  },
  { title: "单价", key: "rate", render: (row) => (row.rate == null ? "—" : String(row.rate)) },
  { title: "状态", key: "status", render: (row) => row.status || "—" },
  { title: "单号", key: "id", render: (row) => row.id || "—" },
];

const pairColumns: DataTableColumns<PairRow> = [
  { title: "卖币时间", key: "coin_when", render: (row) => row.coin_when || "—" },
  { title: "币量", key: "coins", render: (row) => fmt(row.coins) },
  { title: "卖币收款", key: "earn", render: (row) => fmt(row.earn) },
  { title: "对应卖积分", key: "cost", render: (row) => fmt(row.cost) },
  { title: "手续费", key: "fee", render: (row) => fmt(dayFee(row)) },
  {
    title: "利润",
    key: "profit",
    render: (row) => h(Money, { value: row.profit, colored: true }),
  },
  {
    title: "单号",
    key: "ids",
    render: (row) => `币 ${row.coin_id || "—"} / 积分 ${row.pt_id || "—"}`,
  },
];

const formulaColumns: DataTableColumns<PairRow> = [
  { title: "币量", key: "coins", render: (row) => fmt(row.coins) },
  { title: "卖币收款", key: "earn", render: (row) => fmt(row.earn) },
  { title: "卖积分成本", key: "cost", render: (row) => fmt(row.cost) },
  { title: "卖积分费", key: "fee_p", render: (row) => fmt(row.fee_p) },
  { title: "卖币费", key: "fee_c", render: (row) => fmt(row.fee_c) },
  { title: "利润", key: "profit", render: (row) => h(Money, { value: row.profit, colored: true }) },
  { title: "算式", key: "formula", ellipsis: { tooltip: true }, render: (row) => row.formula || "—" },
];

const listedEmpty = computed(() =>
  stats.value?.listed
    ? `计数已有 ${fmt(stats.value.listed)} 份，逐笔明细会在下次扫到「我的上架历史」或再成功挂单后补齐。`
    : "今天还没有上架记录。跑一轮扫描或成功挂单后会出现。",
);
const soldEmpty = computed(() =>
  stats.value?.sold
    ? `计数已有 ${fmt(stats.value.sold)} 份配对，逐笔明细会在下次扫到上架历史后补齐。`
    : "今天还没有配对成交。卖积分和卖交易币对上之后才会进这里。",
);
</script>

<template>
  <section-card :title="`实时盘口 · ${listCoins} 币档`" :sub="bookSub">
    <book-panel />
  </section-card>

  <section-card title="其它数量档" sub="当前这一轮快照，只观察">
    <n-data-table
      v-if="tiers.length"
      size="small"
      :bordered="false"
      :columns="tierColumns"
      :data="tiers"
      :pagination="false"
      :row-class-name="rowClass"
      :scroll-x="640"
    />
    <empty-state v-else text="还没有分档数据" />
  </section-card>

  <section-card title="今日明细" :sub="overview.data?.today || ''">
    <n-tabs v-model:value="tab" type="line" animated>
      <n-tab-pane name="listed" tab="已上">
        <n-data-table
          v-if="detail?.listed.length"
          size="small"
          :bordered="false"
          :columns="listedColumns"
          :data="detail.listed"
          :pagination="{ pageSize: 10 }"
          :scroll-x="760"
        />
        <empty-state v-else :text="listedEmpty" />
      </n-tab-pane>
      <n-tab-pane name="sold" tab="成交配对">
        <n-data-table
          v-if="detail?.pairs.length"
          size="small"
          :bordered="false"
          :columns="pairColumns"
          :data="detail.pairs"
          :pagination="{ pageSize: 10 }"
          :scroll-x="860"
        />
        <empty-state v-else :text="soldEmpty" />
      </n-tab-pane>
      <n-tab-pane name="profit" tab="利润算式">
        <p class="formula">
          每对：卖币收款 − 对应卖积分挂出 − 卖积分费 − 卖币费。今日合计
          <money :value="stats?.profit ?? 0" colored />
        </p>
        <n-data-table
          v-if="detail?.pairs.length"
          size="small"
          :bordered="false"
          :columns="formulaColumns"
          :data="detail.pairs"
          :pagination="{ pageSize: 10 }"
          :scroll-x="860"
        />
        <empty-state
          v-else
          :text="stats?.profit ? `合计利润 ${fmt(stats.profit)}，逐笔算式会在下次扫到上架历史后列出。` : '今天还没有利润来源。配对成交后按上面算式逐笔列出。'"
        />
        <p v-if="detail?.redeem.length" class="muted note">
          另有自己赎回 {{ detail.redeem.length }} 笔，手续费不退，未计入利润。
        </p>
      </n-tab-pane>
      <n-tab-pane name="redeem" tab="赎回">
        <n-data-table
          v-if="detail?.redeem.length"
          size="small"
          :bordered="false"
          :columns="listedColumns"
          :data="detail.redeem"
          :pagination="{ pageSize: 10 }"
          :scroll-x="760"
        />
        <empty-state v-else text="今天没有自己赎回的单。" hint="赎回手续费不退，不计入配对利润。" />
      </n-tab-pane>
    </n-tabs>
  </section-card>
</template>

<style scoped>
.formula { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.note { margin: 10px 0 0; font-size: 12px; }
:deep(.is-current td) { color: var(--gold); }
</style>
