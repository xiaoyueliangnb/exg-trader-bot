<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const overview = ref(null);
const logs = ref([]);
const running = ref(false);
const error = ref("");
const busy = ref(false);
let timer = 0;

const quote = computed(() => overview.value?.quote || null);
const avg = computed(() => overview.value?.avg || {});
const days = computed(() => {
  const rows = overview.value?.profit?.days || [];
  return [...rows].sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
});
const yday = computed(() => overview.value?.profit?.yesterday_row || null);
const canList = computed(() => overview.value?.can_list === true);
const todayStats = computed(() => overview.value?.today_stats || {});
const monthProfit = computed(() => {
  const today = String(overview.value?.today || "");
  const month = today.slice(0, 7);
  const rows = (overview.value?.profit?.days || []).filter(
    (d) => month && String(d.date || "").startsWith(month)
  );
  const profit = rows.reduce((sum, d) => sum + Number(d.profit || 0), 0);
  return { month, profit, days: rows.length };
});
const todayLabel = computed(() => overview.value?.today || "");
const todayDetail = computed(() => overview.value?.today_detail || { listed: [], pairs: [], redeem: [] });
const listedRows = computed(() => todayDetail.value.listed || []);
const pairRows = computed(() => todayDetail.value.pairs || []);
const redeemRows = computed(() => todayDetail.value.redeem || []);
const modal = ref("");

const modalTitle = computed(() => {
  if (modal.value === "listed") return "今日已上明细";
  if (modal.value === "sold") return "今日成交明细";
  if (modal.value === "profit") return "今日利润来源";
  return "";
});

function openDetail(kind) {
  modal.value = kind;
}

function closeDetail() {
  modal.value = "";
}

function onKey(ev) {
  if (ev.key === "Escape") closeDetail();
}

function sideLabel(row) {
  return row.side || (row.kind === "sell_coin" ? "卖交易币" : "卖积分");
}

function fmt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("zh-CN");
}

async function pull() {
  try {
    const [o, l] = await Promise.all([
      fetch("/api/overview").then((r) => r.json()),
      fetch("/api/logs").then((r) => r.json()),
    ]);
    overview.value = o;
    logs.value = l.lines || [];
    running.value = !!(o.bot?.running || l.running);
    error.value = "";
  } catch (err) {
    error.value = "连不上本地 API。先运行 python api.py";
  }
}

async function startBot() {
  busy.value = true;
  try {
    await fetch("/api/bot/start", { method: "POST" });
    await pull();
  } catch (err) {
    error.value = "启动失败";
  } finally {
    busy.value = false;
  }
}

async function stopBot() {
  busy.value = true;
  try {
    await fetch("/api/bot/stop", { method: "POST" });
    await pull();
  } catch (err) {
    error.value = "停止失败";
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  pull();
  timer = window.setInterval(pull, 1500);
  window.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  window.clearInterval(timer);
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div class="page">
    <header class="top">
      <div>
        <p class="kicker">list.darkrp.cn</p>
        <h1>积分商城上架台</h1>
      </div>
      <div class="status" :class="running ? 'on' : 'off'">
        {{ running ? "自动上架运行中" : "未运行" }}
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>

    <section class="stats">
      <article>
        <span>买积分 5 日均</span>
        <strong>{{ avg.point_avg != null ? avg.point_avg.toFixed(1) : "—" }}</strong>
        <em>{{ avg.date || "无缓存" }}</em>
      </article>
      <article>
        <span>买交易币 5 日均</span>
        <strong>{{ avg.coin_avg != null ? avg.coin_avg.toFixed(1) : "—" }}</strong>
        <em>越低越划算</em>
      </article>
      <article>
        <span>两边成交利润</span>
        <strong :class="canList ? 'good' : 'bad'">{{
          quote ? fmt(quote.profit) : "—"
        }}</strong>
        <em>{{ canList ? "达到 50，可上架" : "小于 50，不上架" }}</em>
      </article>
      <article>
        <span>昨天利润</span>
        <strong>{{ yday ? fmt(yday.profit) : "—" }}</strong>
        <em>{{ overview?.profit?.yesterday || "尚未结算" }}</em>
      </article>
    </section>

    <section class="stats today-stats">
      <button type="button" class="stat-card" @click="openDetail('listed')">
        <span>今日已上</span>
        <strong>{{ fmt(todayStats.listed || 0) }}</strong>
        <em>点击查看明细 · {{ todayLabel || "今天" }}</em>
      </button>
      <button type="button" class="stat-card" @click="openDetail('sold')">
        <span>今日成交</span>
        <strong>{{ fmt(todayStats.sold || 0) }}</strong>
        <em>点击查看明细 · 配对卖出</em>
      </button>
      <button type="button" class="stat-card" @click="openDetail('profit')">
        <span>今日利润</span>
        <strong :class="(todayStats.profit || 0) > 0 ? 'good' : ''">{{
          fmt(todayStats.profit || 0)
        }}</strong>
        <em>点击查看来源 · 卖币 − 卖积分 − 费</em>
      </button>
      <article>
        <span>本月利润</span>
        <strong :class="monthProfit.profit > 0 ? 'good' : monthProfit.profit < 0 ? 'bad' : ''">{{
          fmt(monthProfit.profit)
        }}</strong>
        <em>{{ monthProfit.month || "本月" }} · {{ monthProfit.days }} 天合计</em>
      </article>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>本轮报价</h2>
        <template v-if="quote">
          <div class="quote">
            <div>
              <p>卖积分</p>
              <h3>{{ fmt(quote.points_listed) }} 积分标 {{ quote.coins }} 币</h3>
              <p class="sub">{{ quote.low_unit }}/币 · 费 {{ fmt(quote.fee_in) }}</p>
            </div>
            <div>
              <p>卖交易币</p>
              <h3>{{ quote.coins }} 币标 {{ fmt(quote.earned) }}</h3>
              <p class="sub">{{ quote.high_unit }}/币 · 费 {{ fmt(quote.fee_out) }}</p>
            </div>
          </div>
          <p class="formula">
            {{ fmt(quote.earned) }} − {{ fmt(quote.points_listed) }} −
            {{ fmt(quote.fee_in) }} − {{ fmt(quote.fee_out) }} =
            {{ fmt(quote.profit) }}
          </p>
        </template>
        <p v-else class="muted">
          控制台这里显示 5 日均参考价。卖积分不低于均价，卖交易币不高于均价；排不进第一的一侧不新增。先跑 scan / --auto。
        </p>
      </div>

      <div class="panel">
        <h2>自动上架</h2>
        <div class="actions">
          <button class="primary" :disabled="busy || running" @click="startBot">
            启动 --auto
          </button>
          <button :disabled="busy || !running" @click="stopBot">停止</button>
        </div>
        <p class="hint">
          两轮间隔按时段自动：高峰 10 分钟，平峰 30 分钟。工作日高峰是中午 12–14 和晚上 18–24；周末 10:00–24:00 都算高峰。
          卖积分不低于 5 日均，高于均价可以抢排序；卖交易币不高于 5 日均，低于均价可以抢排序。排不进第一不新增。前排同一价最多 2 份，不足就补 1 份，2–3 分钟后再补第二份；满 2 份才按高峰 10 分钟、平峰 30 分钟等。
          有一侧落后且利润仍够 50 时，10 分钟后再看。冷却 10–20 分钟；利润小于 50 不挂。
        </p>
      </div>
    </section>

    <section class="panel">
      <h2>每日利润</h2>
      <table v-if="days.length">
        <thead>
          <tr>
            <th>日期</th>
            <th>卖币笔/量</th>
            <th>卖积分笔/量</th>
            <th>收款</th>
            <th>挂出</th>
            <th>手续费</th>
            <th>利润</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in days" :key="d.date">
            <td>{{ d.date }}</td>
            <td>{{ d.n_coin }} / {{ d.coin_n }}</td>
            <td>{{ d.n_pt }} / {{ d.pt_n }}</td>
            <td>{{ fmt(d.coin_pts) }}</td>
            <td>{{ fmt(d.pt_pts) }}</td>
            <td>{{ fmt((d.fee_c || 0) + (d.fee_p || 0)) }}</td>
            <td :class="d.profit > 0 ? 'good' : 'bad'">{{ fmt(d.profit) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">还没有利润记录</p>
    </section>

    <section class="panel log-panel">
      <h2>运行日志</h2>
      <pre class="log">{{ logs.length ? logs.join("\n") : "暂无输出" }}</pre>
    </section>

    <div v-if="modal" class="mask" @click.self="closeDetail">
      <div class="sheet" role="dialog" :aria-label="modalTitle">
        <header>
          <h2>{{ modalTitle }}</h2>
          <button type="button" @click="closeDetail">关闭</button>
        </header>

        <template v-if="modal === 'listed'">
          <table v-if="listedRows.length">
            <thead>
              <tr>
                <th>时间</th>
                <th>方向</th>
                <th>数量</th>
                <th>标价</th>
                <th>单价</th>
                <th>状态</th>
                <th>单号</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in listedRows" :key="row.id || i">
                <td>{{ row.when || "—" }}</td>
                <td>{{ sideLabel(row) }}</td>
                <td>
                  {{ row.kind === "sell_points" ? fmt(row.points) + " 积分" : fmt(row.coins) + " 币" }}
                </td>
                <td>
                  {{ row.kind === "sell_points" ? fmt(row.coins) + " 币" : fmt(row.points) + " 积分" }}
                </td>
                <td>{{ row.rate != null ? row.rate : "—" }}</td>
                <td>{{ row.status || "—" }}</td>
                <td>{{ row.id || "—" }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">
            {{
              todayStats.listed
                ? `计数已有 ${fmt(todayStats.listed)} 份，逐笔明细会在下次扫到「我的上架历史」或再成功挂单后补齐。`
                : "今天还没有上架记录。跑一轮扫描或成功挂单后会出现。"
            }}
          </p>
        </template>

        <template v-else-if="modal === 'sold'">
          <table v-if="pairRows.length">
            <thead>
              <tr>
                <th>卖币时间</th>
                <th>币量</th>
                <th>卖币收款</th>
                <th>对应卖积分</th>
                <th>手续费</th>
                <th>利润</th>
                <th>单号</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in pairRows" :key="row.coin_id || i">
                <td>{{ row.coin_when || "—" }}</td>
                <td>{{ fmt(row.coins) }}</td>
                <td>{{ fmt(row.earn) }}</td>
                <td>{{ fmt(row.cost) }}</td>
                <td>{{ fmt((row.fee_c || 0) + (row.fee_p || 0)) }}</td>
                <td :class="row.profit > 0 ? 'good' : 'bad'">{{ fmt(row.profit) }}</td>
                <td>币 {{ row.coin_id || "—" }} / 积分 {{ row.pt_id || "—" }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">
            {{
              todayStats.sold
                ? `计数已有 ${fmt(todayStats.sold)} 份配对，逐笔明细会在下次扫到上架历史后补齐。`
                : "今天还没有配对成交。卖积分和卖交易币对上之后才会进这里。"
            }}
          </p>
        </template>

        <template v-else>
          <p class="formula">
            每对：卖币收款 − 对应卖积分挂出 − 卖积分费 − 卖币费。今日合计
            {{ fmt(todayStats.profit || 0) }}
          </p>
          <table v-if="pairRows.length">
            <thead>
              <tr>
                <th>币量</th>
                <th>卖币收款</th>
                <th>卖积分成本</th>
                <th>卖积分费</th>
                <th>卖币费</th>
                <th>利润</th>
                <th>算式</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in pairRows" :key="'p' + i">
                <td>{{ fmt(row.coins) }}</td>
                <td>{{ fmt(row.earn) }}</td>
                <td>{{ fmt(row.cost) }}</td>
                <td>{{ fmt(row.fee_p) }}</td>
                <td>{{ fmt(row.fee_c) }}</td>
                <td :class="row.profit > 0 ? 'good' : 'bad'">{{ fmt(row.profit) }}</td>
                <td>{{ row.formula }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">
            {{
              todayStats.profit
                ? `合计利润 ${fmt(todayStats.profit)}，逐笔算式会在下次扫到上架历史后列出。`
                : "今天还没有利润来源。配对成交后按上面算式逐笔列出。"
            }}
          </p>
          <p v-if="redeemRows.length" class="hint">
            另有自己赎回 {{ redeemRows.length }} 笔，手续费不退，未计入利润。
          </p>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 20px 48px;
}

.top {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 22px;
}

.kicker {
  margin: 0 0 4px;
  color: var(--gold);
  letter-spacing: 0.12em;
  font-size: 12px;
  text-transform: lowercase;
}

h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 650;
}

.status {
  padding: 6px 12px;
  border: 1px solid var(--line);
  font-size: 13px;
}

.status.on {
  color: var(--mint);
  border-color: var(--mint);
}

.status.off {
  color: var(--muted);
}

.err {
  color: var(--bad);
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.today-stats {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: -4px;
}

.stats article,
.stat-card {
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 14px 16px;
}

.stat-card {
  width: 100%;
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.stat-card:hover {
  border-color: var(--gold);
}

.mask {
  position: fixed;
  inset: 0;
  background: rgba(8, 10, 8, 0.72);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 48px 16px 24px;
  z-index: 20;
  overflow: auto;
}

.sheet {
  width: min(960px, 100%);
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 16px 18px 20px;
}

.sheet header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.sheet header h2 {
  margin: 0;
}

.sheet .formula {
  margin: 0 0 12px;
}

.stats span,
.stats em,
.stat-card span,
.stat-card em {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.stats strong,
.stat-card strong {
  display: block;
  margin: 8px 0 4px;
  font-size: 26px;
  font-weight: 650;
}

.good {
  color: var(--mint);
}

.bad {
  color: var(--bad);
}

.grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 16px 18px 18px;
  margin-bottom: 12px;
}

h2 {
  margin: 0 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--gold);
}

.quote {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.quote p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.quote h3 {
  margin: 6px 0 4px;
  font-size: 18px;
  font-weight: 600;
}

.sub,
.formula,
.hint,
.muted {
  color: var(--muted);
  font-size: 13px;
}

.formula {
  margin: 16px 0 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}

input {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--line);
  padding: 8px 10px;
}

.actions {
  display: flex;
  gap: 8px;
  margin: 14px 0 10px;
}

button {
  background: var(--bg-2);
  color: var(--text);
  border: 1px solid var(--line);
  padding: 8px 14px;
  cursor: pointer;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

button.primary {
  background: var(--gold);
  color: #1a1408;
  border-color: var(--gold);
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th,
td {
  text-align: left;
  padding: 8px 6px;
  border-bottom: 1px solid var(--line);
}

th {
  color: var(--muted);
  font-weight: 500;
}

.log-panel {
  margin-bottom: 0;
}

.log {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

@media (max-width: 860px) {
  .stats,
  .today-stats,
  .grid,
  .quote {
    grid-template-columns: 1fr;
  }
}
</style>
