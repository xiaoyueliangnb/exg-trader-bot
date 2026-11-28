<script setup lang="ts">
import SectionCard from "@/components/SectionCard.vue";
import { useMarket } from "@/composables/useMarket";
import { pad } from "@/utils/format";
import { WEEKDAY_PEAKS, WEEKEND_PEAKS } from "@/utils/schedule";
import { computed } from "vue";

const { listCoins, minProfit, minPerCoin, frontDepth } = useMarket();

const strips = [
  { name: "工作日", peaks: WEEKDAY_PEAKS, text: "高峰 12–15、17–24 点，每 10 分钟一轮" },
  { name: "周末", peaks: WEEKEND_PEAKS, text: "高峰 0–1、10–24 点，每 10 分钟一轮" },
];

const rules = computed(() => [
  ["每套", `${listCoins.value} 币。每轮每侧最多提交 1 份`],
  ["利润门槛", `每币 ${minPerCoin.value} 积分，每套不低于 ${minProfit.value}`],
  ["前排深度", `同一前排价最多 ${frontDepth.value} 份。不足时 2–3 分钟后再补 1 份`],
  ["均价护栏", "卖积分单价不低于 5 日均，高于可以；卖交易币单价不高于 5 日均，低于可以"],
  ["只挂第一", "某一侧排不进盘口第一，这一侧本轮不新增"],
  ["不撤单", "已挂出的单不赎回。赎回手续费不退，也不计入配对利润"],
  ["平峰", "非高峰每 30 分钟一轮。有一侧落后且利润仍够门槛时，10 分钟后再看"],
  ["商店冷却", "提交后若处于冷却，等待 10–20 分钟"],
  ["验证码", "OCR 最多试 3 次，仍失败则暂停 10 分钟"],
  ["异常", "任何报错只重连，不退出。进程意外退出后 30 秒自动拉起"],
]);
</script>

<template>
  <section-card title="当前参数" sub="只读。修改要改服务器 .env 后重启服务">
    <dl class="params">
      <dt>每套币数</dt><dd>{{ listCoins }}</dd>
      <dt>每币最低利润</dt><dd>{{ minPerCoin }}</dd>
      <dt>每套最低利润</dt><dd>{{ minProfit }}</dd>
      <dt>前排深度</dt><dd>{{ frontDepth }}</dd>
    </dl>
  </section-card>

  <section-card title="轮询时段" sub="金色是高峰。和成交分布的对照在「分析」页">
    <div v-for="row in strips" :key="row.name" class="strip">
      <div class="head">
        <b>{{ row.name }}</b>
        <span>{{ row.text }}</span>
      </div>
      <div class="hours">
        <i v-for="h in 24" :key="h" :class="{ peak: row.peaks.includes(h - 1) }" :title="`${h - 1} 点`">{{ pad(h - 1) }}</i>
      </div>
    </div>
  </section-card>

  <section-card title="规则">
    <dl class="rules">
      <template v-for="[name, text] in rules" :key="name">
        <dt>{{ name }}</dt>
        <dd>{{ text }}</dd>
      </template>
    </dl>
  </section-card>
</template>

<style scoped>
.params, .rules {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 10px 16px;
  margin: 0;
  font-size: 13px;
}
dt { color: var(--muted); }
dd { margin: 0; }

.strip + .strip { margin-top: 16px; }
.head { display: flex; gap: 12px; align-items: baseline; margin-bottom: 8px; font-size: 13px; }
.head span { color: var(--muted); font-size: 12px; }
.hours { display: grid; grid-template-columns: repeat(24, minmax(0, 1fr)); gap: 3px; }
.hours i {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  border: 1px solid var(--line);
  border-radius: 3px;
  color: var(--muted);
  font-style: normal;
  font-size: 11px;
}
.hours i.peak { background: rgba(212, 176, 106, 0.22); color: var(--gold); border-color: rgba(212, 176, 106, 0.5); }

@media (max-width: 720px) {
  .params, .rules { grid-template-columns: 1fr; gap: 2px; }
  dd { margin-bottom: 8px; }
  .hours i { font-size: 9px; }
}
</style>
