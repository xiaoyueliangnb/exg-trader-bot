# 控制台前端重构方案

> 给执行重构的 AI / 开发者。先通读全文，再按「六、分阶段计划」逐阶段做，每阶段结束都要能部署、能用。
> 用户使用简体中文，界面文案和回复都用简体中文。

---

## 零、必读约束（违反会出事）

1. **只动前端**：`web/` 目录。后端 `api.py` 只允许做第五节列出的「可选接口补充」，且不能改变现有接口的返回字段。**绝不改** `scan.py`、`jifen.py`、`db.py` 的交易逻辑。
2. **机器人在跑真钱交易**。前端构建只替换 `web/dist`，**不需要也不要重启服务**。只有改了 `api.py` 才需要重启，并且必须等机器人空闲（见第七节）。
3. **不要在这台云主机上执行 `npm install`、`npm run build`、`vue-tsc`、`vite build`。** 机器内存不够，编译会把系统卡死。源码推到 GitHub 后，在自己的电脑上编译，再把 `web/dist` 传回主机。
4. **不要碰** `.env`、数据库数据、`jifen.service`、git 配置。提交用 `git -c user.name=... -c user.email=...`（见第七节）。
5. 交易规则在界面上的描述必须准确（见第四节「业务口径」），不能为了好看改写意思。
6. 每个阶段完成后，旧功能一个都不能少（第三节的功能清单逐项核对）。

---

## 一、现状与问题

| 项 | 现状 |
| --- | --- |
| 技术栈 | Vue 3.5 + Vite 6，纯 JS，无路由、无状态管理、无 UI 库、无类型 |
| 文件 | `src/App.vue` 约 1300 行（总览 + 弹窗 + 日志 + 登录 + 轮询全塞在一起）；`src/Analysis.vue` 约 550 行；`src/style.css` 全局样式 |
| 路由 | 用 `location.hash === "#analysis"` 手工切页 |
| 数据 | 组件里直接 `fetch`，轮询逻辑、401 处理、错误提示散落各处 |
| 图表 | 手写 SVG / div 柱状图，无坐标轴、无 tooltip，不好扩展 |
| 样式 | scoped + 全局混用，颜色只有几个 CSS 变量，间距字号靠手填 |
| 质量 | 无 TypeScript、无 ESLint、无测试 |

主要痛点：信息堆在一页、层级不清；新增功能只能继续往 `App.vue` 里塞；图表简陋；移动端将就。

---

## 二、目标技术栈

| 用途 | 选型 | 理由 |
| --- | --- | --- |
| 语言 | **TypeScript**（strict） | 接口字段多，类型能挡住大部分低级错 |
| 框架 | Vue 3.5 `<script setup lang="ts">` | 保持现有技术栈 |
| 构建 | Vite 6 | 保持 |
| 路由 | **vue-router 4**，`createWebHistory()` | `api.py` 已对非 `/api` 路径回落到 `index.html`，history 模式可用。旧链接 `/#analysis` 要重定向到新地址 |
| 状态 | **Pinia** | 集中管理轮询数据、登录口令、机器人状态 |
| UI 组件 | **Naive UI**（暗色主题 + `zhCN` 语言包） | 中文友好，表格 / 弹窗 / 标签页 / 骨架屏齐全，按需引入，TS 支持好 |
| 图表 | **ECharts 6 + vue-echarts**，从 `echarts/core` 按需注册 | 柱状、折线、热力图都要；tooltip、缩放开箱即用 |
| 工具 | `@vueuse/core`（`useIntervalFn`、`useDocumentVisibility`、`useLocalStorage`、`useBreakpoints`） | 少写样板代码 |
| 规范 | ESLint（`@vue/eslint-config-typescript`）+ Prettier；`vue-tsc --noEmit` 进构建 | |
| 测试 | Vitest：只测纯函数（格式化、利润计算、时段解析） | 不追求覆盖率 |

服务器环境：Node 20.20、npm 10.8，`registry.npmjs.org` 可直连。

**体积要求**：生产包 gzip 后 JS 总量 ≤ 400 KB。ECharts 必须按需引入（`echarts/core` + 用到的 chart/component/renderer），Naive UI 按需引入（`unplugin-vue-components` + `NaiveUiResolver`）。

---

## 三、现有功能清单（重构后必须全部保留）

### 全局
- [ ] 口令登录：后端设置了 `CONSOLE_TOKEN` 时任何 `/api/*` 返回 401 → 显示登录页；口令存 `localStorage["jifen_token"]`，请求头 `X-Token`；`GET /api/auth` 校验；可退出
- [ ] 顶部机器人状态：阶段标签（扫描中 / 等待下一轮 / 商店冷却 / 验证码暂停 / 等待重连 / 等 0 点结算 / 未运行）、下一轮倒计时（按 `bot.next_at` 每秒刷新）、已运行时长、自动拉起次数
- [ ] 启动 / 停止机器人；**停止要二次确认**
- [ ] 数据超过 20 秒没刷新时提示；API 连不上时提示并自动重试
- [ ] 标签页隐藏时暂停轮询，回来立即刷新一次

### 总览
- [ ] 账户余额（积分、交易币）
- [ ] 5 日均（积分 / 交易币）+ 日期
- [ ] 实盘每套利润（`market.quote.profit`），≥ 门槛绿色「可上架」，否则红色
- [ ] 昨天利润、今日已上、今日成交、今日利润、本月利润
- [ ] 今日已上 / 今日成交 / 今日利润三张卡片可点开明细（逐笔表格，见 `today_detail`）；利润明细末尾提示自己赎回笔数
- [ ] 实时盘口（10 币档）：两侧盘口第一 / 第二、均价下限 / 上限、本轮目标价、我在售份数 vs 前排深度、利润算式；仅当「±1 利润」大于实盘利润时才显示该对比
- [ ] 其它数量档列表（只观察）
- [ ] 策略参数展示（每套币数、利润门槛、前排深度、定价规则、工作日 / 周末高峰、平峰、异常处理）

### 利润
- [ ] 近 30 天柱状图（负数红色），累计 / 天数 / 日均 / 配对套数 / 最好一天
- [ ] 每日表格（日期、卖币笔/量、卖积分笔/量、收款、挂出、手续费、利润），默认 14 天可展开；利润正绿负红零中性

### 日志
- [ ] 增量拉取 `GET /api/logs?since=<seq>`（`reset=true` 时整表替换），前端最多保留 400 行
- [ ] 着色：错误红（异常/失败/错误/Traceback/退出 code）、告警橙（验证码/暂停/重连）、成功绿（上架成功/已挂/本轮已提交/结算）、等待灰
- [ ] 筛选：全部 / 交易 / 异常
- [ ] 自动跟随到底；用户上翻时停止跟随并显示「回到最新」

### 数据分析
- [ ] 统计天数 7 / 14 / 30 / 60，记住上次选择
- [ ] 成交时段：工作日、周末各 24 小时柱状图（每天平均张数），区分「建议高峰」与「当前高峰」，下方给出加 / 减建议
- [ ] 成交速度：按领先盘口幅度、按 3 小时时段；卖积分 / 卖交易币切换，默认选有数据的一侧；样本 < 30 张提示
- [ ] 分档盘口表：两边都有盘比例、两侧最优价及出现率、±1 每币利润、达标占比、「在做」/「可考虑开放」标签

---

## 四、信息架构与页面设计

### 4.1 布局

```
┌──────────────────────────────────────────────────────────┐
│ 顶栏：Logo「积分商城上架台」 | 机器人状态胶囊+倒计时 | 启动/停止 | 退出 │
├────────┬─────────────────────────────────────────────────┤
│ 侧边栏 │  页面内容（最大宽 1280，栅格 12 列）              │
│ 总览   │                                                 │
│ 交易   │                                                 │
│ 利润   │                                                 │
│ 分析   │                                                 │
│ 日志   │                                                 │
│ 策略   │                                                 │
└────────┴─────────────────────────────────────────────────┘
```

- ≥ 1024px：左侧固定侧边栏（可折叠成图标）。
- < 768px：侧边栏改为底部 5 个 Tab（总览 / 交易 / 利润 / 分析 / 日志），「策略」放进顶栏菜单；顶栏只保留状态胶囊和启停按钮。
- 机器人状态胶囊点击后弹出抽屉：最近 20 行日志 + 启停按钮，方便任何页面快速看一眼。

### 4.2 路由

| 路径 | 页面 | 主要数据 |
| --- | --- | --- |
| `/` | 总览 Dashboard | overview |
| `/trade` | 交易：实时盘口 + 今日挂单 / 成交明细 | overview.market、overview.today_detail |
| `/profit` | 利润：趋势图 + 日表 + 月汇总 | overview.profit |
| `/analysis` | 数据分析 | `/api/analysis?days=` |
| `/logs` | 日志（全屏） | `/api/logs` |
| `/strategy` | 策略参数与规则说明（只读） | overview.strategy |
| `/login` | 口令登录 | `/api/auth` |

- 旧地址 `/#analysis` → 重定向 `/analysis`。
- 未知路径 → `/`。

### 4.3 各页内容

**总览 `/`**（一屏看清「赚没赚、在不在跑、现在能不能挂」）
1. KPI 行（4 张）：今日利润（含较昨日同期涨跌）、本月利润、实盘每套利润（含门槛判断）、账户余额（积分 + 交易币）。
2. 第二行：「今日」小卡（已上 / 成交 / 赎回，点击跳 `/trade`）+ 近 7 天利润迷你折线（点击跳 `/profit`）。
3. 实时盘口精简版（两侧：盘口第一、目标价、在售 x/3），右上角「详情 →」跳 `/trade`。
4. 最近 8 行日志（只看交易 + 异常），「全部 →」跳 `/logs`。

**交易 `/trade`**
1. 实时盘口完整版：两侧卡片（盘口第一/第二、均价护栏、目标价、在售份数方块）、利润算式、快照时间（「x 分钟前」）。快照超过 40 分钟标黄提示「数据较旧」。
2. 其它数量档表（默认展开，10 币档高亮）。
3. 今日明细 Tabs：已上 / 成交配对 / 利润算式 / 赎回。替代原来的弹窗。

**利润 `/profit`**
1. 汇总条：累计、天数、日均、配对套数、最好一天、最差一天。
2. ECharts 图：日利润柱状 + 7 日滑动均值折线；可切换 30 / 90 天 / 全部；dataZoom。
3. 按月汇总表（月份、天数、配对、手续费、利润）。
4. 每日明细表：分页 20 行，可按日期倒序 / 利润排序；可导出 CSV（前端生成）。

**数据分析 `/analysis`**：功能同现有 `Analysis.vue`，图表换 ECharts：
- 成交时段：工作日、周末两张 24 柱图，`markArea` 画当前高峰区间，建议高峰柱用金色；或合成一张 7×24 热力图（周一~周日 × 小时）作为第二视图（需后端补接口，见第五节，可选）。
- 成交速度：横向条形图 + 表格。
- 分档盘口：表格 + 「两边都有盘」进度条。

**日志 `/logs`**：全高日志查看器；筛选（全部 / 交易 / 异常）+ 关键字搜索（前端过滤）+ 暂停滚动 + 复制可见内容；行数 > 400 时虚拟滚动（`n-virtual-list` 或 `vue-virtual-scroller`）。

**策略 `/strategy`**：用描述列表展示 `overview.strategy` 和第四节「业务口径」里的规则文字；轮询时段用 24 格时间条可视化（工作日、周末各一条，高峰金色）。目前只读。

### 4.4 视觉规范

保留现有暗绿色金色风格，统一成设计令牌（放 `src/styles/tokens.css`，同时映射进 Naive UI `themeOverrides`）：

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--bg` | `#10140f` | 页面背景 |
| `--bg-2` | `#171d15` | 次级背景 / 输入框 |
| `--panel` | `#1c2419` | 卡片 |
| `--line` | `#2c3826` | 边框 / 分割线 |
| `--text` | `#e7eadf` | 主文字 |
| `--muted` | `#8b947c` | 次要文字 |
| `--gold` | `#d4b06a` | 品牌色 / 强调 / 主按钮 |
| `--mint` | `#8fbf7a` | 正向（盈利、成功、运行中） |
| `--warn` | `#d08a5a` | 告警（暂停、数据旧） |
| `--bad` | `#c45c4a` | 负向（亏损、错误） |

- 间距 4 的倍数（4/8/12/16/24/32）；圆角统一 6px（现在是直角，可以改）；卡片内边距 16。
- 字号：KPI 数字 28 / 卡片标题 13 / 正文 14 / 辅助 12。数字一律 `font-variant-numeric: tabular-nums`。
- 涨跌色：利润 > 0 绿，< 0 红，= 0 中性。**全站统一用 `<Money>` 组件渲染金额**，不要各处手写 class。
- 状态：每个数据块都要有 加载（骨架屏）/ 空数据（说明文字 + 下一步提示）/ 出错（重试按钮）三态。

### 4.5 业务口径（文案必须准确）

| 名词 | 含义 |
| --- | --- |
| 卖积分 | 挂出积分换交易币。单价 = 积分/币，**越高越靠前**。手续费 = 挂出积分 × 5%（向下取整） |
| 卖交易币 | 挂出交易币换积分。单价 = 积分/币，**越低越靠前**。手续费 = 每币 10 积分 |
| 每套利润 | 卖币收款 − 卖积分挂出 − 卖积分费 − 卖币费 |
| 均价护栏 | 卖积分单价 **不低于** 5 日均；卖交易币单价 **不高于** 5 日均 |
| 只挂第一 | 某侧排不进盘口第一就不新增 |
| 前排深度 | 同一前排价最多保留 N 份（`strategy.front_depth`） |
| 利润门槛 | 每币 `strategy.min_profit_per_coin`，每套 `strategy.min_profit` |
| 配对 | 已成交的卖积分单与卖交易币单按 FIFO 一一配对后算利润 |
| 赎回 | 自己撤下的单，手续费不退，不计入配对利润 |
| 不撤单 | 机器人从不主动赎回 |

---

## 五、接口契约

所有接口在 `src/api/` 下用类型化函数封装；组件里**禁止**直接 `fetch`。

### 5.1 现有接口（不得改字段）

```ts
// 通用：请求头 X-Token；401 => 跳 /login

// GET /api/auth
interface AuthResp { required: boolean; ok: boolean }

// GET /api/overview  （约 17KB，建议 5 秒轮询）
interface Overview {
  today: string;                         // "2026-11-28"
  avg: { date: string; point_avg: number | null; coin_avg: number | null; n_point: number; n_coin: number };
  quote: AvgQuote | null;                // 按 5 日均算的理论报价（旧口径，新界面以 market.quote 为准）
  can_list: boolean;
  today_stats: { listed: number; sold: number; profit: number };
  today_detail: {
    date: string;
    listed: ListedRow[];
    pairs: PairRow[];
    redeem: ListedRow[];
  };
  profit: {
    as_of: string | null;
    yesterday: string | null;
    yesterday_row: DayProfit | null;
    days: DayProfit[];                   // 全部历史，按日期倒序
  };
  market: MarketSnapshot | null;         // 最近一轮扫描
  bot: {
    running: boolean;
    started_at: string | null;           // ISO
    restarts: number;
    last_exit: number | null;
    autostart: boolean;
    state: "stopped" | "working" | "waiting" | "paused" | "retry";
    label: string;                       // 中文阶段名
    next_at: string | null;              // ISO，下一轮预计时间
  };
  strategy: { list_coins: number; min_profit: number; min_profit_per_coin: number; front_depth: number };
}

interface AvgQuote {
  coins: number; points_listed: number; coin_list_price: number;
  low_unit: number; high_unit: number; low_rate: number; high_rate: number;
  fee_in: number; fee_out: number; spent: number; earned: number; profit: number;
  min_profit: number; point_avg: number; coin_avg: number;
  in_effective: number; out_effective: number;
  low_note: string; high_note: string; price_mode: string;
}

interface ListedRow {
  id: string; kind: "sell_points" | "sell_coin"; side: string;
  coins: number; points: number; rate: number;
  open: boolean; status: string; when: string; text: string;
}

interface PairRow {
  coins: number; earn: number; cost: number; fee_c: number; fee_p: number; profit: number;
  coin_id: string; pt_id: string; coin_when: string; pt_when: string; formula: string;
}

interface DayProfit {
  date: string;
  n_coin: number; n_pt: number; n_pair: number; n_redeem: number;
  coin_n: number; coin_pts: number; fee_c: number;
  pt_n: number; pt_pts: number; fee_p: number;
  redeem_fee: number; net_coin: number; profit: number; n_listed: number;
  settled_on: string | null;
}

interface BookLevel { best: number; second: number | null; n: number }

interface MarketSnapshot {
  ts: string;                            // "2026-11-28 01:28:56"
  hour: number; weekday: number;
  money: number;                         // 积分余额
  coin: number;                          // 交易币余额
  point_avg: number; coin_avg: number;
  points_book: Record<string, BookLevel>;   // 键 = 币数档位
  coins_book: Record<string, BookLevel>;
  mine: { sell_points: Record<string, number>; sell_coin: Record<string, number> };  // 自己在售份数
  tier_profit: Record<string, { profit: number; per_coin: number }>;              // 两边 ±1 的理论利润
  quote: { coins: number; low_unit: number; high_unit: number; profit: number };  // 本轮实际目标价与每套利润
}

// GET /api/logs?since=<seq>
interface LogsResp { running: boolean; seq: number; reset: boolean; lines: string[] }
// 每行形如 "[01:23:41] 文本"

// POST /api/bot/start | /api/bot/stop
interface BotActionResp { ok: boolean; state: string; running: boolean }

// GET /api/analysis?days=14  （后端缓存 60 秒；503 = 数据库不可用）
interface Analysis {
  days: number; since: string; generated_at: string;
  min_profit_per_coin: number; peak_ratio: number;
  tiers: {
    snapshots: number; first: string | null; last: string | null;
    tiers: {
      coins: number; both_ratio: number; points_seen: number; coins_seen: number;
      points_best: number | null; points_n: number | null;
      coins_best: number | null; coins_n: number | null;
      per_coin: number | null; ok_ratio: number | null;
    }[];
  };
  fill: {
    sold: number; submits: number; matched: number;
    by_lead: { kind: string; side: string; lead: number | null; label: string; n: number; median: number | null; mean: number | null }[];
    by_slot: { kind: string; side: string; hour: number; n: number; median: number | null; mean: number | null }[];
  };
  hourly: {
    sold: number;
    weekday: HourlyGroup; weekend: HourlyGroup;
  };
}
interface HourlyGroup { days: number; per_day: number[]; mean: number; suggested_peaks: number[]; current_peaks: number[] }
```

执行前先用 `curl http://127.0.0.1:8787/api/overview` 等核对一遍实际返回，有出入以实际为准并更新本节。

### 5.2 可选接口补充（需要才加，加了要在本节登记）

只允许**新增**只读接口，放在 `api.py`，数据从现有表读：

| 接口 | 用途 | 数据来源 |
| --- | --- | --- |
| `GET /api/listings/open` | 当前在售单列表（交易页） | `listing_track` where `status='open'` |
| `GET /api/fills/heatmap?days=` | 7×24 成交热力图 | `listing_track` where `status='sold'` |
| `GET /api/market/history?hours=24` | 10 币档两侧盘口第一价格走势 | `market_snapshot` |

改完 `api.py` 要按第七节流程安全重启。

---

## 六、分阶段计划

每阶段：本地 `npm run build` 通过 → 部署 → 浏览器验收 → 提交推送。

### 阶段 1：脚手架（功能与现在一模一样）
- 改 TS：`vue-tsc`、`tsconfig.json`、`env.d.ts`；装 vue-router、pinia、naive-ui、@vueuse/core、eslint、prettier、vitest。
- 目录结构：

```
web/src/
├── main.ts
├── App.vue                 # 只放 <n-config-provider> + <RouterView>
├── router/index.ts
├── api/
│   ├── client.ts           # fetch 封装：X-Token、401、超时、错误归一
│   ├── types.ts            # 第五节类型
│   └── endpoints.ts        # getOverview / getLogs / startBot / ...
├── stores/
│   ├── auth.ts             # 口令
│   ├── overview.ts         # 5s 轮询、stale 判断
│   ├── logs.ts             # 2s 增量轮询、seq
│   └── clock.ts            # 1s 的 now，倒计时共用
├── composables/
│   ├── usePolling.ts       # 可见性暂停 + 回来立即刷新
│   └── useBotPhase.ts
├── utils/
│   ├── format.ts           # 金额、百分比、时间、倒计时、「x 分钟前」
│   ├── profit.ts           # 手续费、每套利润算式
│   └── logLine.ts          # 日志着色与筛选规则
├── layouts/AppLayout.vue
├── components/             # Money、KpiCard、StatusPill、DepthBlocks、EmptyState、ChartBox...
├── pages/                  # Dashboard、Trade、Profit、Analysis、Logs、Strategy、Login
└── styles/tokens.css
```

- 把现有 `App.vue` 逻辑先**原样**搬进 stores / utils，页面暂时用一个 `LegacyDashboard.vue` 承载，保证可用。
- 验收：第三节清单全部可用；`npm run build`（含 `vue-tsc --noEmit`）零错误。

### 阶段 2：布局与设计系统
- `AppLayout`（侧边栏 + 顶栏 + 移动端底部 Tab），顶栏状态胶囊 + 启停 + 倒计时。
- Naive UI 暗色主题 + `themeOverrides` 对齐令牌；`zhCN`、`dateZhCN`。
- 基础组件：`Money`、`KpiCard`、`StatusPill`、`DepthBlocks`、`EmptyState`、`ErrorState`、`SectionCard`。
- 验收：1440 / 1024 / 390 三种宽度截图无溢出、无横向滚动（表格除外）。

### 阶段 3：页面拆分
- 按 4.2 / 4.3 实现六个页面 + 登录页，删除 `LegacyDashboard.vue`、旧 `Analysis.vue`。
- 今日明细从弹窗改为交易页 Tabs。
- 验收：第三节清单逐项打勾；`/#analysis` 能跳到 `/analysis`。

### 阶段 4：图表
- ECharts 按需引入，统一 `ChartBox` 组件（暗色主题、自适应、空数据占位）。
- 利润趋势（柱 + 7 日均线 + dataZoom）、成交时段（markArea 标当前高峰）、成交速度条形图、近 7 天迷你折线。
- 验收：JS gzip ≤ 400 KB；图表 tooltip 中文、数字带千分位。

### 阶段 5：体验打磨
- 骨架屏 / 空态 / 错误重试三态全覆盖。
- 日志页：关键字搜索、复制、虚拟滚动。
- 利润页 CSV 导出。
- 可访问性：按钮有文字或 `aria-label`；弹层 Esc 关闭；焦点可见。
- 验收：Chrome Lighthouse（桌面）Performance ≥ 90、Accessibility ≥ 90。

### 阶段 6：质量
- Vitest 覆盖 `utils/`（format、profit、logLine、倒计时解析）。
- `npm run lint`、`npm run typecheck`、`npm run test` 三个脚本；README 的「前端开发」小节更新。
- 验收：三个脚本全绿。

（可选）阶段 7：按 5.2 补接口，做在售单列表、热力图、盘口走势。

---

## 七、开发、部署与回滚

**在自己的电脑上编译**（不要在云主机上跑）：

```bash
git pull
cd web
npm install
npm run build          # 产物在 web/dist
```

`npm run dev` 也可以在自己电脑上跑，`/api` 代理的是本机 8787。要对着云主机的接口开发时，把 `web/vite.config.ts` 里的代理临时改成云主机地址，改完不要提交。

**把产物传回云主机**（不重启服务，刷新浏览器即可）：

```bash
rsync -av --delete web/dist/ ubuntu@43.142.117.241:/home/ubuntu/server/exg/jifen/web/dist/
```

线上地址：`http://43.142.117.241:8788/`（1Panel 反代到 `127.0.0.1:8787`）。`web/dist` 不进 Git。

**改了 `api.py` 才需要重启**，且必须等机器人空闲：

```bash
cd /home/ubuntu/server/exg/jifen
.venv/bin/python -m py_compile api.py
curl -s http://127.0.0.1:8787/api/logs | .venv/bin/python -c 'import sys,json;print(json.load(sys.stdin)["lines"][-1])'
# 最后一行含「重新登录」或「等待 N 秒」才执行：
sudo systemctl restart jifen.service    # 机器人随服务自动拉起
```

**不要**用 `pkill -f api.py` 之类的命令清理测试进程，会误杀线上服务；测试实例请记下 PID 再 `kill <PID>`。

**提交推送**（服务器走 SSH，不要改 git config）：

```bash
cd /home/ubuntu/server/exg/jifen
git add -A && git status -s     # 确认没有 .env、node_modules、dist
git -c user.name="xiaoyueliangnb" -c user.email="xiaoyueliangnb@users.noreply.github.com" commit -m "refactor(web): ..."
git push
```

**回滚**：`git revert <commit>` 后在自己电脑上重新 `npm run build`，再把 `web/dist` 传回主机。不要在云主机上编译。

---

## 八、验收总表

- [ ] 第三节功能清单全部保留
- [ ] 6 个页面 + 登录页可用，旧 `/#analysis` 可跳转
- [ ] 1440 / 1024 / 390 三种宽度布局正常
- [ ] 口令开启时（临时在测试实例设 `CONSOLE_TOKEN`）登录 / 退出 / 401 跳转正常
- [ ] 标签页隐藏时网络面板无轮询请求
- [ ] JS gzip ≤ 400 KB；`vue-tsc`、ESLint、Vitest 全绿
- [ ] 过程中线上机器人未中断（日志无非预期的「进程退出」）
- [ ] `PLAN.md` 的 UI 项状态和变更记录已更新
