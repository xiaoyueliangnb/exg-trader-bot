<script setup lang="ts">
import { useMarket } from "@/composables/useMarket";
import { fmt } from "@/utils/format";
import DepthBlocks from "./DepthBlocks.vue";
import EmptyState from "./EmptyState.vue";
import Money from "./Money.vue";

defineProps<{ compact?: boolean }>();

const { live, parts, frontDepth, showEdge, edge, liveOk, snapOld, minProfit } = useMarket();
</script>

<template>
  <template v-if="live">
    <div class="book">
      <div class="side">
        <header>
          <b>卖积分</b>
          <em>越高越靠前</em>
        </header>
        <dl v-if="!compact">
          <dt>盘口第一</dt><dd>{{ fmt(live.points.best) }}</dd>
          <dt>盘口第二</dt><dd>{{ fmt(live.points.second) }}</dd>
          <dt>均价下限</dt><dd>{{ fmt(live.points.guard, 1) }}</dd>
          <dt>本轮目标价</dt><dd class="em">{{ fmt(live.points.price) }}</dd>
        </dl>
        <p v-else class="line">
          盘口 <b>{{ fmt(live.points.best) }}</b>
          · 目标 <b class="em">{{ fmt(live.points.price) }}</b>
        </p>
        <depth-blocks :count="live.points.mine" :max="frontDepth" />
      </div>
      <div class="side">
        <header>
          <b>卖交易币</b>
          <em>越低越靠前</em>
        </header>
        <dl v-if="!compact">
          <dt>盘口第一</dt><dd>{{ fmt(live.coins.best) }}</dd>
          <dt>盘口第二</dt><dd>{{ fmt(live.coins.second) }}</dd>
          <dt>均价上限</dt><dd>{{ fmt(live.coins.guard, 1) }}</dd>
          <dt>本轮目标价</dt><dd class="em">{{ fmt(live.coins.price) }}</dd>
        </dl>
        <p v-else class="line">
          盘口 <b>{{ fmt(live.coins.best) }}</b>
          · 目标 <b class="em">{{ fmt(live.coins.price) }}</b>
        </p>
        <depth-blocks :count="live.coins.mine" :max="frontDepth" />
      </div>
    </div>
    <p v-if="parts" class="formula">
      卖币收 {{ fmt(parts.earned) }} − 卖积分挂 {{ fmt(parts.listed) }} − 费 {{ fmt(parts.feeIn) }} − 费
      {{ fmt(parts.feeOut) }} =
      <money :value="live.profit" colored />
      <template v-if="!liveOk">（低于门槛 {{ minProfit }}，不上架）</template>
      <template v-if="showEdge && edge">
        ；若不受均价限制、两边只抢盘口 ±1，约 {{ fmt(edge.profit) }}
      </template>
    </p>
    <p v-if="snapOld" class="warn old">快照已超过 40 分钟，可能不是最新盘口。</p>
  </template>
  <empty-state v-else text="还没有盘口快照" hint="启动自动上架，跑完第一轮就会显示。" />
</template>

<style scoped>
.book { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

.side {
  border: 1px solid var(--line);
  background: var(--bg-2);
  border-radius: 6px;
  padding: 12px 14px;
}

header { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-size: 13px; }
em { color: var(--muted); font-style: normal; font-size: 12px; }

dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}

dt { color: var(--muted); }
dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
.em, dd.em { color: var(--gold); font-weight: 650; }

.line { margin: 0; font-size: 13px; color: var(--muted); }
.line b { color: var(--text); font-weight: 600; }

.formula { margin: 14px 0 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.old { margin: 8px 0 0; font-size: 12px; }

@media (max-width: 720px) {
  .book { grid-template-columns: 1fr; }
}
</style>
