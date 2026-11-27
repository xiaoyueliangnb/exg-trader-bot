<script setup>
import { computed, onMounted, ref, watch } from "vue";

const props = defineProps({
  api: { type: Function, required: true },
  listCoins: { type: Number, default: 10 },
});

const RANGES = [7, 14, 30, 60];
const MIN_SAMPLE = 30;

const days = ref(Number(localStorage.getItem("jifen_analysis_days")) || 14);
const data = ref(null);
const loading = ref(false);
const error = ref("");
const fillSide = ref("sell_points");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await props.api(`/api/analysis?days=${days.value}`);
  } catch (err) {
    error.value = err.message === "HTTP 503" ? "数据库连不上，分析需要 MySQL 里的快照数据" : "加载失败";
  } finally {
    loading.value = false;
  }
}

watch(days, (v) => {
  localStorage.setItem("jifen_analysis_days", String(v));
  load();
});

onMounted(load);

function num(x, d = 1) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  return Number(x).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function pct(x) {
  return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`;
}

function hh(h) {
  return String(h).padStart(2, "0");
}

function ranges(hours) {
  const out = [];
  for (const h of [...hours].sort((a, b) => a - b)) {
    const last = out[out.length - 1];
    if (last && last[1] === h) last[1] = h + 1;
    else out.push([h, h + 1]);
  }
  return out.map(([a, b]) => `${a}–${b}`).join("、") || "无";
}

// ---- 成交时段 ----
const hourly = computed(() => {
  const h = data.value?.hourly;
  if (!h) return [];
  return [
    { key: "weekday", name: "工作日", ...h.weekday },
    { key: "weekend", name: "周末", ...h.weekend },
  ].map((x) => {
    const max = Math.max(0.1, ...x.per_day);
    const sug = new Set(x.suggested_peaks);
    const cur = new Set(x.current_peaks || []);
    const add = [...sug].filter((v) => !cur.has(v));
    const drop = [...cur].filter((v) => !sug.has(v));
    return {
      ...x,
      bars: x.per_day.map((v, i) => ({
        hour: i,
        v,
        h: (v / max) * 100,
        sug: sug.has(i),
        cur: cur.has(i),
      })),
      add,
      drop,
      total: x.per_day.reduce((s, v) => s + v, 0),
    };
  });
});

// ---- 成交速度 ----
const fill = computed(() => data.value?.fill || null);
const leadRows = computed(() => {
  const rows = (fill.value?.by_lead || []).filter((r) => r.kind === fillSide.value);
  const max = Math.max(1, ...rows.map((r) => r.median || 0));
  return rows.map((r) => ({ ...r, w: ((r.median || 0) / max) * 100 }));
});
const slotRows = computed(() => {
  const rows = (fill.value?.by_slot || []).filter((r) => r.kind === fillSide.value);
  const map = new Map(rows.map((r) => [r.hour, r]));
  const max = Math.max(1, ...rows.map((r) => r.median || 0));
  return Array.from({ length: 8 }, (_, i) => {
    const r = map.get(i * 3);
    return { hour: i * 3, r, w: r ? ((r.median || 0) / max) * 100 : 0 };
  });
});
const sideCount = computed(() => {
  const out = { sell_points: 0, sell_coin: 0 };
  for (const r of fill.value?.by_lead || []) out[r.kind] = (out[r.kind] || 0) + r.n;
  return out;
});

watch(sideCount, (c) => {
  const other = fillSide.value === "sell_points" ? "sell_coin" : "sell_points";
  if (!c[fillSide.value] && c[other]) fillSide.value = other;
});

// ---- 分档 ----
const tiers = computed(() => {
  const t = data.value?.tiers;
  if (!t) return [];
  const th = data.value.min_profit_per_coin;
  return t.tiers
    .map((x) => ({
      ...x,
      candidate: x.both_ratio >= 0.5 && x.per_coin != null && x.per_coin >= th,
    }))
    .sort((a, b) => b.both_ratio - a.both_ratio || a.coins - b.coins);
});
</script>

<template>
  <div class="analysis">
    <div class="toolbar">
      <div class="seg">
        <button v-for="d in RANGES" :key="d" :class="{ act: days === d }" @click="days = d">近 {{ d }} 天</button>
      </div>
      <span class="muted">
        <template v-if="data">{{ data.since }} 至今 · 生成于 {{ data.generated_at.slice(11, 16) }}</template>
      </span>
      <button :disabled="loading" @click="load">{{ loading ? "计算中…" : "刷新" }}</button>
    </div>

    <p v-if="error" class="err banner">{{ error }}</p>

    <template v-if="data">
      <!-- 成交时段 -->
      <section class="panel">
        <h2>
          成交时段
          <small>自己的单按成交时间统计，共 {{ data.hourly.sold }} 张 · 每小时为「每天平均张数」</small>
        </h2>
        <div class="legend">
          <span><i class="sw sug" />建议高峰（≥ 平均 {{ data.peak_ratio }} 倍）</span>
          <span><i class="sw plain" />其它小时</span>
          <span><i class="sw cur" />当前按高峰轮询（10 分钟一轮）</span>
        </div>
        <div v-for="g in hourly" :key="g.key" class="hour-block">
          <div class="hour-head">
            <b>{{ g.name }}</b>
            <span class="muted">
              {{ g.days }} 天样本 · 日均 {{ num(g.total) }} 张
            </span>
          </div>
          <div v-if="g.days" class="hours">
            <div
              v-for="b in g.bars"
              :key="b.hour"
              class="hcol"
              :class="{ cur: b.cur }"
              :title="`${hh(b.hour)}:00–${hh(b.hour + 1)}:00 每天平均 ${num(b.v)} 张${b.sug ? ' · 建议高峰' : ''}${b.cur ? ' · 当前高峰' : ''}`"
            >
              <span class="hval">{{ b.v >= 0.05 ? num(b.v) : "" }}</span>
              <div class="hbar" :class="{ sug: b.sug }" :style="{ height: b.h + '%' }" />
              <span class="hlabel">{{ hh(b.hour) }}</span>
            </div>
          </div>
          <p v-else class="muted">没有数据</p>
          <p v-if="g.days" class="verdict">
            当前高峰：{{ ranges(g.current_peaks || []) }} 点；建议高峰：{{ ranges(g.suggested_peaks) }} 点。
            <template v-if="!g.add.length && !g.drop.length"><span class="good">完全一致，不用改。</span></template>
            <template v-else>
              <span v-if="g.add.length">建议加为高峰 <b>{{ g.add.map(hh).join("、") }}</b> 点；</span>
              <span v-if="g.drop.length">成交偏少可降为平峰 <b>{{ g.drop.map(hh).join("、") }}</b> 点。</span>
              <span class="muted">（相差 2 个小时以上再改，见 PLAN.md）</span>
            </template>
          </p>
        </div>
      </section>

      <!-- 成交速度 -->
      <section class="panel">
        <h2>
          成交速度
          <small>
            挂出到成交的分钟数 · 对上提交记录 {{ fill.matched }} 张 / 期间成交 {{ fill.sold }} 张
          </small>
          <span class="seg small">
            <button :class="{ act: fillSide === 'sell_points' }" @click="fillSide = 'sell_points'">
              卖积分（{{ sideCount.sell_points }}）
            </button>
            <button :class="{ act: fillSide === 'sell_coin' }" @click="fillSide = 'sell_coin'">
              卖交易币（{{ sideCount.sell_coin }}）
            </button>
          </span>
        </h2>
        <p v-if="fill.matched < MIN_SAMPLE" class="note">
          样本只有 {{ fill.matched }} 张（新采集 2026-11-28 开始），{{ MIN_SAMPLE }} 张以上再据此调价。
        </p>
        <div v-if="leadRows.length" class="speed-grid">
          <div>
            <p class="sub-title">按挂单时相对盘口第一（领先 = 比别人更优）</p>
            <div v-for="r in leadRows" :key="r.label" class="hrow">
              <span class="hrow-label">{{ r.label }}</span>
              <div class="hrow-track">
                <div class="hrow-bar" :style="{ width: r.w + '%' }" />
              </div>
              <span class="hrow-val">
                中位 <b>{{ num(r.median) }}</b> 分 · 均 {{ num(r.mean) }} · {{ r.n }} 张
              </span>
            </div>
          </div>
          <div>
            <p class="sub-title">按挂单时段（中位分钟）</p>
            <div v-for="s in slotRows" :key="s.hour" class="hrow">
              <span class="hrow-label">{{ hh(s.hour) }}–{{ hh(s.hour + 3) }}</span>
              <div class="hrow-track">
                <div v-if="s.r" class="hrow-bar alt" :style="{ width: s.w + '%' }" />
              </div>
              <span class="hrow-val">
                <template v-if="s.r"><b>{{ num(s.r.median) }}</b> 分 · {{ s.r.n }} 张</template>
                <template v-else>—</template>
              </span>
            </div>
          </div>
        </div>
        <p v-else class="muted">这个方向还没有能对上提交记录的成交单。</p>
      </section>

      <!-- 分档盘口 -->
      <section class="panel">
        <h2>
          分档盘口
          <small>快照 {{ data.tiers.snapshots }} 次 · 数值为期间中位数</small>
        </h2>
        <p class="note">
          开放条件（PLAN.md）：两边同时有盘 ≥ 50%，且 ±1 每币利润中位 ≥ {{ data.min_profit_per_coin }}。
          ±1 每币利润 = 两边都按该档盘口第一 ±1 挂、扣双边手续费后每币赚多少（未套均价护栏）。
        </p>
        <div v-if="tiers.length" class="scroll-x">
          <table>
            <thead>
              <tr>
                <th>档位</th>
                <th>两边都有盘</th>
                <th>卖积分第一</th>
                <th>卖币第一</th>
                <th>±1 每币利润</th>
                <th>达标占比</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tiers" :key="t.coins" :class="{ cur: t.coins === listCoins }">
                <td>{{ t.coins }} 币</td>
                <td>
                  <div class="mini">
                    <div class="mini-bar" :style="{ width: t.both_ratio * 100 + '%' }" />
                  </div>
                  {{ pct(t.both_ratio) }}
                </td>
                <td>
                  {{ num(t.points_best) }}
                  <span class="muted">· 出现 {{ pct(t.points_seen) }}</span>
                </td>
                <td>
                  {{ num(t.coins_best) }}
                  <span class="muted">· 出现 {{ pct(t.coins_seen) }}</span>
                </td>
                <td :class="t.per_coin == null ? '' : t.per_coin >= data.min_profit_per_coin ? 'good' : 'bad'">
                  {{ t.per_coin == null ? "单边" : num(t.per_coin, 2) }}
                </td>
                <td>{{ pct(t.ok_ratio) }}</td>
                <td>
                  <span v-if="t.coins === listCoins" class="tag">在做</span>
                  <span v-else-if="t.candidate" class="tag good">可考虑开放</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted">还没有快照。自动上架每轮扫描会记一次。</p>
      </section>
    </template>
    <p v-else-if="loading" class="muted">计算中…</p>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.toolbar .muted {
  margin-left: auto;
}

.seg {
  display: inline-flex;
}

.seg button {
  padding: 6px 12px;
  font-size: 13px;
  color: var(--muted);
}

.seg button + button {
  border-left: none;
}

.seg button.act {
  color: #1a1408;
  background: var(--gold);
  border-color: var(--gold);
}

.seg.small {
  margin-left: auto;
}

.seg.small button {
  padding: 3px 10px;
  font-size: 12px;
}

.note {
  margin: -4px 0 14px;
  font-size: 12.5px;
  color: var(--warn);
  line-height: 1.6;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}

.sw {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: 6px;
  vertical-align: -1px;
}

.sw.sug {
  background: var(--gold);
}

.sw.plain {
  background: var(--mint);
  opacity: 0.55;
}

.sw.cur {
  background: rgba(212, 176, 106, 0.14);
  border: 1px dashed rgba(212, 176, 106, 0.5);
}

.hour-block + .hour-block {
  margin-top: 18px;
}

.hour-head {
  display: flex;
  gap: 12px;
  align-items: baseline;
  margin-bottom: 6px;
  font-size: 13px;
}

.hours {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  gap: 3px;
  height: 150px;
}

.hcol {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: stretch;
  min-width: 0;
  padding: 0 1px;
}

.hcol.cur {
  background: rgba(212, 176, 106, 0.1);
  box-shadow: inset 0 -1px 0 rgba(212, 176, 106, 0.5);
}

.hval {
  font-size: 10px;
  color: var(--muted);
  text-align: center;
  height: 14px;
  overflow: hidden;
}

.hbar {
  background: var(--mint);
  opacity: 0.55;
  min-height: 1px;
}

.hbar.sug {
  background: var(--gold);
  opacity: 1;
}

.hcol:hover .hbar {
  opacity: 1;
}

.hlabel {
  margin-top: 4px;
  font-size: 10.5px;
  color: var(--muted);
  text-align: center;
}

.verdict {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.7;
}

.verdict b {
  color: var(--gold);
}

.speed-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.sub-title {
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--muted);
}

.hrow {
  display: grid;
  grid-template-columns: 70px 1fr 190px;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  margin-bottom: 7px;
}

.hrow-label {
  color: var(--text);
}

.hrow-track {
  height: 12px;
  background: var(--bg);
  border: 1px solid var(--line);
}

.hrow-bar {
  height: 100%;
  background: var(--gold);
}

.hrow-bar.alt {
  background: var(--mint);
}

.hrow-val {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.hrow-val b {
  color: var(--text);
  font-weight: 600;
}

.mini {
  display: inline-block;
  width: 60px;
  height: 6px;
  margin-right: 8px;
  background: var(--bg);
  border: 1px solid var(--line);
  vertical-align: middle;
}

.mini-bar {
  height: 100%;
  background: var(--mint);
}

.tag {
  font-size: 11.5px;
  padding: 2px 6px;
  border: 1px solid var(--line);
  color: var(--gold);
}

.tag.good {
  border-color: var(--mint);
}

@media (max-width: 860px) {
  .speed-grid {
    grid-template-columns: 1fr;
  }

  .hours {
    height: 120px;
  }

  .hval {
    display: none;
  }

  .hlabel {
    font-size: 9px;
  }

  .hrow {
    grid-template-columns: 60px 1fr;
  }

  .hrow-val {
    grid-column: 1 / -1;
  }
}
</style>
