<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import Analysis from "./Analysis.vue";

const TOKEN_KEY = "jifen_token";
const LOG_KEEP = 400;

const overview = ref(null);
const logs = ref([]);
const logSeq = ref(0);
const running = ref(false);
const error = ref("");
const busy = ref(false);
const updatedAt = ref(null);
const now = ref(Date.now());

const token = ref(localStorage.getItem(TOKEN_KEY) || "");
const needLogin = ref(false);
const loginInput = ref("");
const loginError = ref("");

const modal = ref("");
const confirmStop = ref(false);
const showAllDays = ref(false);
const showTiers = ref(false);
const logFilter = ref("all");
const follow = ref(true);
const logBox = ref(null);

const view = ref(location.hash === "#analysis" ? "analysis" : "overview");

function onHash() {
  view.value = location.hash === "#analysis" ? "analysis" : "overview";
}

function goOverview() {
  history.pushState(null, "", location.pathname);
  view.value = "overview";
}

let timers = [];

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { ...(opts.headers || {}), "X-Token": token.value },
  });
  if (res.status === 401) {
    needLogin.value = true;
    throw new Error("unauthorized");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function login() {
  loginError.value = "";
  token.value = loginInput.value.trim();
  try {
    const r = await fetch("/api/auth", { headers: { "X-Token": token.value } }).then((x) => x.json());
    if (!r.ok) {
      loginError.value = "口令不对";
      return;
    }
    localStorage.setItem(TOKEN_KEY, token.value);
    needLogin.value = false;
    loginInput.value = "";
    logSeq.value = 0;
    await Promise.all([pullOverview(), pullLogs()]);
  } catch {
    loginError.value = "连不上服务器";
  }
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  token.value = "";
  needLogin.value = true;
}

async function pullOverview() {
  try {
    overview.value = await api("/api/overview");
    running.value = !!overview.value.bot?.running;
    updatedAt.value = Date.now();
    error.value = "";
  } catch (err) {
    if (err.message !== "unauthorized") error.value = "连不上控制台 API，稍后自动重试";
  }
}

async function pullLogs() {
  try {
    const l = await api(`/api/logs?since=${logSeq.value}`);
    const merged = l.reset ? l.lines : logs.value.concat(l.lines);
    logs.value = merged.slice(-LOG_KEEP);
    logSeq.value = l.seq;
    running.value = !!l.running;
  } catch {
    /* overview 会给出错误提示 */
  }
}

async function startBot() {
  busy.value = true;
  try {
    await api("/api/bot/start", { method: "POST" });
    await pullOverview();
  } catch {
    error.value = "启动失败";
  } finally {
    busy.value = false;
  }
}

async function stopBot() {
  confirmStop.value = false;
  busy.value = true;
  try {
    await api("/api/bot/stop", { method: "POST" });
    await pullOverview();
  } catch {
    error.value = "停止失败";
  } finally {
    busy.value = false;
  }
}

function fmt(n, digits) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  return digits == null
    ? v.toLocaleString("zh-CN")
    : v.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function clock(sec) {
  if (sec == null) return "";
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function ago(iso) {
  if (!iso) return "—";
  const sec = (now.value - new Date(iso.replace(" ", "T")).getTime()) / 1000;
  if (sec < 60) return "刚刚";
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

// ---- 概览 ----
const bot = computed(() => overview.value?.bot || {});
const avg = computed(() => overview.value?.avg || {});
const market = computed(() => overview.value?.market || null);
const strategy = computed(() => overview.value?.strategy || {});
const minProfit = computed(() => strategy.value.min_profit ?? 50);
const minPerCoin = computed(() => strategy.value.min_profit_per_coin ?? 5);
const frontDepth = computed(() => strategy.value.front_depth ?? 3);
const listCoins = computed(() => strategy.value.list_coins ?? 10);
const todayStats = computed(() => overview.value?.today_stats || {});
const todayLabel = computed(() => overview.value?.today || "");
const yday = computed(() => overview.value?.profit?.yesterday_row || null);

const nextIn = computed(() => {
  const at = bot.value.next_at;
  if (!at) return null;
  return (new Date(at).getTime() - now.value) / 1000;
});

const statusClass = computed(() => {
  if (!running.value) return "off";
  if (bot.value.state === "paused" || bot.value.state === "retry") return "warn";
  return "on";
});

const uptime = computed(() => {
  if (!running.value || !bot.value.started_at) return "";
  const sec = (now.value - new Date(bot.value.started_at).getTime()) / 1000;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h ? `已运行 ${h} 小时 ${m} 分` : `已运行 ${m} 分钟`;
});

const stale = computed(() => updatedAt.value && now.value - updatedAt.value > 20000);

// ---- 实盘 ----
const tierKey = computed(() => String(listCoins.value));
const live = computed(() => {
  const m = market.value;
  if (!m) return null;
  const t = tierKey.value;
  const pb = m.points_book?.[t] || {};
  const cb = m.coins_book?.[t] || {};
  const q = m.quote || {};
  return {
    ts: m.ts,
    money: m.money,
    coin: m.coin,
    points: {
      best: pb.best,
      second: pb.second,
      mine: m.mine?.sell_points?.[t] || 0,
      price: q.low_unit,
      floor: m.point_avg,
    },
    coins: {
      best: cb.best,
      second: cb.second,
      mine: m.mine?.sell_coin?.[t] || 0,
      price: q.high_unit,
      ceil: m.coin_avg,
    },
    profit: q.profit,
    coins_n: q.coins || listCoins.value,
    edge: m.tier_profit?.[t],
  };
});

const liveFee = computed(() => {
  const l = live.value;
  if (!l || l.points.price == null || l.coins.price == null) return null;
  const n = l.coins_n;
  const listed = l.points.price * n;
  const feeIn = Math.floor(listed * 0.05);
  const feeOut = n * 10;
  const earned = l.coins.price * n;
  return { listed, feeIn, feeOut, earned };
});

const liveOk = computed(() => live.value?.profit != null && live.value.profit >= minProfit.value);

const tiers = computed(() => {
  const m = market.value;
  if (!m) return [];
  const keys = new Set([...Object.keys(m.points_book || {}), ...Object.keys(m.coins_book || {})]);
  return [...keys]
    .map(Number)
    .sort((a, b) => a - b)
    .map((k) => ({
      coins: k,
      p: m.points_book?.[k],
      c: m.coins_book?.[k],
      edge: m.tier_profit?.[k],
    }));
});

// ---- 利润 ----
const allDays = computed(() => {
  const rows = overview.value?.profit?.days || [];
  return [...rows].sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
});
const days = computed(() => (showAllDays.value ? allDays.value : allDays.value.slice(0, 14)));

const monthProfit = computed(() => {
  const month = String(overview.value?.today || "").slice(0, 7);
  const rows = allDays.value.filter((d) => month && String(d.date || "").startsWith(month));
  return { month, profit: rows.reduce((s, d) => s + Number(d.profit || 0), 0), days: rows.length };
});

const totals = computed(() => {
  const rows = allDays.value;
  const profit = rows.reduce((s, d) => s + Number(d.profit || 0), 0);
  const pairs = rows.reduce((s, d) => s + Number(d.n_pair || 0), 0);
  const best = rows.reduce((b, d) => (b && b.profit >= d.profit ? b : d), null);
  return { profit, pairs, days: rows.length, avg: rows.length ? Math.round(profit / rows.length) : 0, best };
});

const chart = computed(() => {
  const rows = [...allDays.value].slice(0, 30).reverse();
  if (!rows.length) return null;
  const W = 720;
  const H = 120;
  const max = Math.max(1, ...rows.map((d) => Math.abs(Number(d.profit || 0))));
  const hasNeg = rows.some((d) => Number(d.profit) < 0);
  const base = hasNeg ? H * 0.75 : H;
  const scale = (hasNeg ? H * 0.75 : H - 4) / max;
  const step = W / rows.length;
  const bw = Math.max(2, step * 0.7);
  return {
    W,
    H,
    base,
    bars: rows.map((d, i) => {
      const v = Number(d.profit || 0);
      const h = Math.max(1, Math.abs(v) * scale);
      return {
        x: i * step + (step - bw) / 2,
        y: v >= 0 ? base - h : base,
        w: bw,
        h,
        neg: v < 0,
        tip: `${d.date}：${fmt(v)}（配对 ${d.n_pair ?? "—"}）`,
      };
    }),
    first: rows[0].date,
    last: rows[rows.length - 1].date,
  };
});

// ---- 今日明细弹窗 ----
const todayDetail = computed(() => overview.value?.today_detail || { listed: [], pairs: [], redeem: [] });
const listedRows = computed(() => todayDetail.value.listed || []);
const pairRows = computed(() => todayDetail.value.pairs || []);
const redeemRows = computed(() => todayDetail.value.redeem || []);
const modalTitle = computed(
  () => ({ listed: "今日已上明细", sold: "今日成交明细", profit: "今日利润来源" })[modal.value] || ""
);

function sideLabel(row) {
  return row.side || (row.kind === "sell_coin" ? "卖交易币" : "卖积分");
}

// ---- 日志 ----
function lineClass(line) {
  if (/异常|失败|错误|Traceback|Error|退出 code/.test(line)) return "l-bad";
  if (/验证码|暂停|重连|重新连接/.test(line)) return "l-warn";
  if (/上架成功|已挂|本轮已提交|结算/.test(line)) return "l-good";
  if (/后重新登录|秒后再/.test(line)) return "l-dim";
  return "";
}

const shownLogs = computed(() => {
  const f = logFilter.value;
  const rows = logs.value.map((text) => ({ text, cls: lineClass(text) }));
  if (f === "trade") return rows.filter((r) => /上架|报价|分档|盘口|利润|已挂|维持|不挂/.test(r.text));
  if (f === "issue") return rows.filter((r) => r.cls === "l-bad" || r.cls === "l-warn");
  return rows;
});

function onLogScroll() {
  const el = logBox.value;
  if (!el) return;
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
}

function toBottom() {
  follow.value = true;
  nextTick(() => {
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight;
  });
}

watch(shownLogs, () => {
  if (follow.value) toBottom();
});

watch(view, (v) => {
  if (v === "overview") toBottom();
});

// ---- 生命周期 ----
function onKey(ev) {
  if (ev.key === "Escape") {
    modal.value = "";
    confirmStop.value = false;
  }
}

function schedule() {
  timers.forEach((t) => window.clearInterval(t));
  timers = [];
  if (document.hidden) return;
  timers.push(window.setInterval(pullOverview, 5000));
  timers.push(window.setInterval(pullLogs, 2000));
  timers.push(window.setInterval(() => (now.value = Date.now()), 1000));
}

function onVisible() {
  if (!document.hidden) {
    now.value = Date.now();
    pullOverview();
    pullLogs();
  }
  schedule();
}

onMounted(() => {
  pullOverview();
  pullLogs();
  schedule();
  window.addEventListener("keydown", onKey);
  window.addEventListener("hashchange", onHash);
  document.addEventListener("visibilitychange", onVisible);
});

onUnmounted(() => {
  timers.forEach((t) => window.clearInterval(t));
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("hashchange", onHash);
  document.removeEventListener("visibilitychange", onVisible);
});
</script>

<template>
  <div v-if="needLogin" class="login">
    <form class="panel" @submit.prevent="login">
      <h2>积分商城上架台</h2>
      <p class="muted">输入 .env 里的 CONSOLE_TOKEN</p>
      <input v-model="loginInput" type="password" autocomplete="current-password" autofocus />
      <button class="primary" type="submit">进入</button>
      <p v-if="loginError" class="err">{{ loginError }}</p>
    </form>
  </div>

  <div v-else class="page">
    <header class="top">
      <div>
        <p class="kicker">list.darkrp.cn</p>
        <h1>积分商城上架台</h1>
      </div>
      <div class="top-right">
        <div class="status" :class="statusClass">
          <i class="dot" />
          <span>{{ running ? bot.label || "运行中" : "未运行" }}</span>
          <b v-if="running && nextIn != null && nextIn > 0">{{ clock(nextIn) }}</b>
        </div>
        <p class="meta">
          {{ uptime }}
          <template v-if="bot.restarts"> · 自动拉起 {{ bot.restarts }} 次</template>
          <template v-if="stale"> · <span class="bad">数据已超过 20 秒未刷新</span></template>
          <a v-if="token" href="#" @click.prevent="logout">退出</a>
        </p>
      </div>
    </header>

    <nav class="nav">
      <a href="#" :class="{ act: view === 'overview' }" @click.prevent="goOverview">总览</a>
      <a href="#analysis" :class="{ act: view === 'analysis' }">数据分析</a>
    </nav>

    <p v-if="error" class="err banner">{{ error }}</p>

    <Analysis v-if="view === 'analysis'" :api="api" :list-coins="listCoins" />

    <template v-else>
    <section class="stats">
      <article>
        <span>账户余额</span>
        <strong>{{ live ? fmt(live.money) : "—" }}</strong>
        <em>积分 · 交易币 {{ live ? fmt(live.coin) : "—" }}</em>
      </article>
      <article>
        <span>5 日均（积分 / 交易币）</span>
        <strong class="pair">
          {{ avg.point_avg != null ? fmt(avg.point_avg, 1) : "—" }}
          <small>/</small>
          {{ avg.coin_avg != null ? fmt(avg.coin_avg, 1) : "—" }}
        </strong>
        <em>{{ avg.date || "无缓存" }} · 卖积分不低于前者，卖币不高于后者</em>
      </article>
      <article>
        <span>实盘每套利润</span>
        <strong :class="live?.profit == null ? '' : liveOk ? 'good' : 'bad'">
          {{ live ? fmt(live.profit) : "—" }}
        </strong>
        <em>
          {{ live?.profit == null ? "等第一轮扫描" : liveOk ? `≥ ${minProfit}，可上架` : `< ${minProfit}，不上架` }}
        </em>
      </article>
      <article>
        <span>昨天利润</span>
        <strong :class="yday && yday.profit < 0 ? 'bad' : ''">{{ yday ? fmt(yday.profit) : "—" }}</strong>
        <em>{{ overview?.profit?.yesterday || "尚未结算" }}</em>
      </article>
    </section>

    <section class="stats">
      <button type="button" class="stat-card" @click="modal = 'listed'">
        <span>今日已上</span>
        <strong>{{ fmt(todayStats.listed || 0) }}</strong>
        <em>{{ todayLabel || "今天" }} · 点击看明细</em>
      </button>
      <button type="button" class="stat-card" @click="modal = 'sold'">
        <span>今日成交</span>
        <strong>{{ fmt(todayStats.sold || 0) }}</strong>
        <em>配对卖出 · 点击看明细</em>
      </button>
      <button type="button" class="stat-card" @click="modal = 'profit'">
        <span>今日利润</span>
        <strong :class="(todayStats.profit || 0) > 0 ? 'good' : (todayStats.profit || 0) < 0 ? 'bad' : ''">
          {{ fmt(todayStats.profit || 0) }}
        </strong>
        <em>点击看每对算式</em>
      </button>
      <article>
        <span>本月利润</span>
        <strong :class="monthProfit.profit > 0 ? 'good' : monthProfit.profit < 0 ? 'bad' : ''">
          {{ fmt(monthProfit.profit) }}
        </strong>
        <em>{{ monthProfit.month || "本月" }} · {{ monthProfit.days }} 天</em>
      </article>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>
          实时盘口 · {{ listCoins }} 币档
          <small v-if="live">{{ live.ts?.slice(11, 16) }} 扫描 · {{ ago(live.ts) }}</small>
        </h2>
        <template v-if="live">
          <div class="book">
            <div class="side">
              <p class="side-title">卖积分 <em>（积分/币，越高越靠前）</em></p>
              <dl>
                <dt>盘口第一</dt>
                <dd>{{ fmt(live.points.best) }}</dd>
                <dt>盘口第二</dt>
                <dd>{{ fmt(live.points.second) }}</dd>
                <dt>均价下限</dt>
                <dd>{{ fmt(live.points.floor, 1) }}</dd>
                <dt>本轮目标价</dt>
                <dd class="em">{{ fmt(live.points.price) }}</dd>
              </dl>
              <div class="depth" :title="`前排最多 ${frontDepth} 份`">
                <span>我在售</span>
                <i v-for="i in Math.max(frontDepth, live.points.mine)" :key="i" :class="{ on: i <= live.points.mine }" />
                <b>{{ live.points.mine }}/{{ frontDepth }}</b>
              </div>
            </div>
            <div class="side">
              <p class="side-title">卖交易币 <em>（积分/币，越低越靠前）</em></p>
              <dl>
                <dt>盘口第一</dt>
                <dd>{{ fmt(live.coins.best) }}</dd>
                <dt>盘口第二</dt>
                <dd>{{ fmt(live.coins.second) }}</dd>
                <dt>均价上限</dt>
                <dd>{{ fmt(live.coins.ceil, 1) }}</dd>
                <dt>本轮目标价</dt>
                <dd class="em">{{ fmt(live.coins.price) }}</dd>
              </dl>
              <div class="depth">
                <span>我在售</span>
                <i v-for="i in Math.max(frontDepth, live.coins.mine)" :key="i" :class="{ on: i <= live.coins.mine }" />
                <b>{{ live.coins.mine }}/{{ frontDepth }}</b>
              </div>
            </div>
          </div>
          <p v-if="liveFee" class="formula">
            卖币收 {{ fmt(liveFee.earned) }} − 卖积分挂 {{ fmt(liveFee.listed) }} − 费 {{ fmt(liveFee.feeIn) }} −
            费 {{ fmt(liveFee.feeOut) }} ≈ <b :class="liveOk ? 'good' : 'bad'">{{ fmt(live.profit) }}</b>
            <template v-if="live.edge && live.edge.profit > live.profit">
              ；若不受均价限制、两边只抢盘口 ±1，约 {{ fmt(live.edge.profit) }}
            </template>
          </p>
          <button type="button" class="link" @click="showTiers = !showTiers">
            {{ showTiers ? "收起" : "展开" }}其它数量档（{{ tiers.length }} 档，只观察）
          </button>
          <table v-if="showTiers" class="compact">
            <thead>
              <tr>
                <th>币数</th>
                <th>卖积分第一</th>
                <th>卖币第一</th>
                <th>±1 每币利润</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tiers" :key="t.coins" :class="{ cur: t.coins === listCoins }">
                <td>{{ t.coins }}</td>
                <td>{{ t.p ? fmt(t.p.best) : "—" }}</td>
                <td>{{ t.c ? fmt(t.c.best) : "—" }}</td>
                <td :class="t.edge ? (t.edge.per_coin >= minPerCoin ? 'good' : 'bad') : ''">
                  {{ t.edge ? fmt(t.edge.per_coin, 1) : "单边" }}
                </td>
              </tr>
            </tbody>
          </table>
        </template>
        <p v-else class="muted">还没有盘口快照。启动自动上架，跑完第一轮就会显示。</p>
      </div>

      <div class="panel">
        <h2>自动上架</h2>
        <div class="actions">
          <button class="primary" :disabled="busy || running" @click="startBot">启动</button>
          <button v-if="!confirmStop" :disabled="busy || !running" @click="confirmStop = true">停止</button>
          <template v-else>
            <button class="danger" :disabled="busy" @click="stopBot">确认停止</button>
            <button @click="confirmStop = false">取消</button>
          </template>
        </div>
        <p v-if="running && bot.next_at" class="hint">
          下一轮约 {{ new Date(bot.next_at).toLocaleTimeString("zh-CN", { hour12: false }) }}
        </p>
        <dl class="params">
          <dt>每套</dt>
          <dd>{{ listCoins }} 币，两边各挂 1 份/轮</dd>
          <dt>利润门槛</dt>
          <dd>每币 {{ minPerCoin }}，即每套 ≥ {{ minProfit }}</dd>
          <dt>前排深度</dt>
          <dd>同价最多 {{ frontDepth }} 份，不足时 2–3 分钟后补</dd>
          <dt>定价</dt>
          <dd>只在能排第一时挂；卖积分 ≥ 均价，卖币 ≤ 均价；不撤单</dd>
          <dt>工作日高峰</dt>
          <dd>12–15 点、17–24 点，每 10 分钟</dd>
          <dt>周末高峰</dt>
          <dd>0–1 点、10–24 点，每 10 分钟</dd>
          <dt>平峰</dt>
          <dd>每 30 分钟；一侧落后时 10 分钟后再看</dd>
          <dt>异常</dt>
          <dd>验证码连错 3 次暂停 10 分钟；进程意外退出 30 秒后自动拉起</dd>
        </dl>
      </div>
    </section>

    <section class="panel">
      <h2>
        每日利润
        <small v-if="totals.days">
          累计 {{ fmt(totals.profit) }} · {{ totals.days }} 天 · 日均 {{ fmt(totals.avg) }} · 配对 {{ fmt(totals.pairs) }} 套
          <template v-if="totals.best"> · 最好 {{ totals.best.date?.slice(5) }}（{{ fmt(totals.best.profit) }}）</template>
        </small>
      </h2>
      <svg v-if="chart" class="chart" :viewBox="`0 0 ${chart.W} ${chart.H}`" preserveAspectRatio="none">
        <line x1="0" :y1="chart.base" :x2="chart.W" :y2="chart.base" class="axis" />
        <rect
          v-for="(b, i) in chart.bars"
          :key="i"
          :x="b.x"
          :y="b.y"
          :width="b.w"
          :height="b.h"
          :class="b.neg ? 'neg' : 'pos'"
        >
          <title>{{ b.tip }}</title>
        </rect>
      </svg>
      <p v-if="chart" class="chart-legend">
        <span>{{ chart.first }}</span><span>近 30 天，鼠标悬停看数值</span><span>{{ chart.last }}</span>
      </p>
      <div v-if="days.length" class="scroll-x">
        <table>
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
              <td :class="d.profit > 0 ? 'good' : d.profit < 0 ? 'bad' : ''">{{ fmt(d.profit) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted">还没有利润记录</p>
      <button v-if="allDays.length > 14" type="button" class="link" @click="showAllDays = !showAllDays">
        {{ showAllDays ? "只看最近 14 天" : `展开全部 ${allDays.length} 天` }}
      </button>
    </section>

    <section class="panel log-panel">
      <h2>
        运行日志
        <span class="tabs">
          <button :class="{ act: logFilter === 'all' }" @click="logFilter = 'all'">全部</button>
          <button :class="{ act: logFilter === 'trade' }" @click="logFilter = 'trade'">交易</button>
          <button :class="{ act: logFilter === 'issue' }" @click="logFilter = 'issue'">异常</button>
        </span>
      </h2>
      <div class="log-wrap">
        <pre ref="logBox" class="log" @scroll="onLogScroll"><template v-if="shownLogs.length"><span
          v-for="(r, i) in shownLogs" :key="i" :class="r.cls">{{ r.text + "\n" }}</span></template><template v-else>暂无输出</template></pre>
        <button v-if="!follow" class="to-bottom" @click="toBottom">↓ 回到最新</button>
      </div>
    </section>
    </template>

    <div v-if="modal" class="mask" @click.self="modal = ''">
      <div class="sheet" role="dialog" :aria-label="modalTitle">
        <header>
          <h2>{{ modalTitle }}</h2>
          <button type="button" @click="modal = ''">关闭</button>
        </header>

        <div class="scroll-x">
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
                  <td>{{ row.kind === "sell_points" ? fmt(row.points) + " 积分" : fmt(row.coins) + " 币" }}</td>
                  <td>{{ row.kind === "sell_points" ? fmt(row.coins) + " 币" : fmt(row.points) + " 积分" }}</td>
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
              每对：卖币收款 − 对应卖积分挂出 − 卖积分费 − 卖币费。今日合计 {{ fmt(todayStats.profit || 0) }}
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
  </div>
</template>

<style scoped>
.page {
  max-width: 1120px;
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

.top-right {
  text-align: right;
}

.kicker {
  margin: 0 0 4px;
  color: var(--gold);
  letter-spacing: 0.12em;
  font-size: 12px;
}

h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 650;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  font-size: 13px;
}

.status b {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.status.on {
  color: var(--mint);
  border-color: var(--mint);
}

.status.on .dot {
  animation: pulse 2s infinite;
}

.status.warn {
  color: var(--warn);
  border-color: var(--warn);
}

.status.off {
  color: var(--muted);
}

@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}

.meta {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.meta a {
  margin-left: 10px;
  color: var(--muted);
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
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
  font-variant-numeric: tabular-nums;
}

.stats strong.pair {
  font-size: 22px;
}

.pair small {
  color: var(--muted);
  font-weight: 400;
  margin: 0 2px;
}

.grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.grid .panel {
  margin-bottom: 0;
}

.book {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.side {
  border: 1px solid var(--line);
  background: var(--bg-2);
  padding: 12px 14px;
}

.side-title {
  margin: 0 0 8px;
  font-size: 13px;
}

.side-title em {
  color: var(--muted);
  font-style: normal;
  font-size: 12px;
}

.side dl,
.params {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}

.side dt,
.params dt {
  color: var(--muted);
}

.side dd,
.params dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}

.side dd {
  text-align: right;
}

.side dd.em {
  color: var(--gold);
  font-weight: 600;
}

.depth {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
}

.depth span {
  margin-right: 4px;
}

.depth i {
  width: 14px;
  height: 14px;
  border: 1px solid var(--line);
}

.depth i.on {
  background: var(--mint);
  border-color: var(--mint);
}

.depth b {
  margin-left: auto;
  color: var(--text);
  font-weight: 500;
}

.formula,
.hint {
  color: var(--muted);
  font-size: 13px;
}

.formula {
  margin: 14px 0 8px;
  line-height: 1.6;
}

.actions {
  display: flex;
  gap: 8px;
  margin: 0 0 10px;
}

.params {
  margin-top: 12px;
  font-size: 12.5px;
}

button.primary {
  background: var(--gold);
  color: #1a1408;
  border-color: var(--gold);
}

button.danger {
  background: var(--bad);
  border-color: var(--bad);
}

button.link {
  background: none;
  border: none;
  padding: 6px 0 0;
  color: var(--gold);
  font-size: 12.5px;
}

.chart {
  width: 100%;
  height: 120px;
  display: block;
}

.chart .pos {
  fill: var(--mint);
  opacity: 0.8;
}

.chart .neg {
  fill: var(--bad);
}

.chart rect:hover {
  opacity: 1;
  fill: var(--gold);
}

.chart .axis {
  stroke: var(--line);
}

.chart-legend {
  display: flex;
  justify-content: space-between;
  margin: 4px 0 12px;
  font-size: 11.5px;
  color: var(--muted);
}

table.compact {
  margin-top: 8px;
  font-size: 12.5px;
}

.nav {
  display: flex;
  gap: 2px;
  margin: -8px 0 16px;
  border-bottom: 1px solid var(--line);
}

.nav a {
  padding: 8px 16px;
  color: var(--muted);
  text-decoration: none;
  font-size: 14px;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.nav a.act {
  color: var(--gold);
  border-bottom-color: var(--gold);
}

.tabs {
  margin-left: auto;
  display: inline-flex;
  gap: 4px;
}

.tabs button {
  padding: 3px 10px;
  font-size: 12px;
  color: var(--muted);
}

.tabs button.act {
  color: var(--gold);
  border-color: var(--gold);
}

.log-panel {
  margin-bottom: 0;
}

.log-wrap {
  position: relative;
}

.log {
  margin: 0;
  height: 380px;
  overflow: auto;
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 12px;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
}

.l-bad {
  color: var(--bad);
}

.l-warn {
  color: var(--warn);
}

.l-good {
  color: var(--mint);
}

.l-dim {
  color: var(--muted);
}

.to-bottom {
  position: absolute;
  right: 14px;
  bottom: 12px;
  padding: 4px 10px;
  font-size: 12px;
  border-color: var(--gold);
  color: var(--gold);
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

.login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.login form {
  width: min(340px, 100%);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.login h2 {
  margin: 0;
  font-size: 18px;
}

.login p {
  margin: 0;
}

input {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--line);
  padding: 8px 10px;
}

@media (max-width: 860px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .grid,
  .book {
    grid-template-columns: 1fr;
  }

  .top {
    flex-direction: column;
    align-items: flex-start;
  }

  .top-right {
    text-align: left;
  }

  .stats strong,
  .stat-card strong {
    font-size: 22px;
  }
}
</style>
