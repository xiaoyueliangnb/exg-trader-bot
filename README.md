# EXG 交易市场自动挂单与控制台

基于 WebSocket 协议的 CS2 EXG 积分 / 交易币市场扫描、自动做市挂单与 Web 控制台，支持 5 日均价护栏、动态时段调度、验证码 OCR 识别、FIFO 利润核算以及 MySQL 持久化。

---

## 目录结构

```text
.
├── scan.py                     # 核心机器人：登录、拉盘口/走势图/历史、定价下单、自动循环
├── jifen.py                    # 利润模型、手续费公式与双边定价策略
├── api.py                      # FastAPI 控制台后端（托管前端、启停自动挂单、输出日志与统计）
├── db.py                       # MySQL 读写层（无库时自动回退本地 JSON 缓存）
├── ocr_captcha.py              # 验证码 OCR 识别（基于 ddddocr，支持自定义训练模型）
├── prepare_captcha_dataset.py  # 验证码训练样本整理脚本
├── analyze_market.py           # 分档盘口 / 成交速度 / 成交时段分析（只读）
├── schema.sql                  # MySQL 建表脚本
├── deploy.sh                   # Ubuntu/Debian + systemd 一键部署脚本
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── CAPTCHA_TRAIN.md            # 自定义验证码模型训练说明
└── web/                        # Vue 3 + Vite 控制台前端
```

---

## 主体交易策略

### 1. 商业闭环与利润模型

单笔固定做 **10 交易币**档位（`LIST_COINS = 10`），通过双边挂单赚取买卖价差：

- **卖积分（进币）**：挂出积分，标价 10 交易币；手续费为上架积分的 **5%**（整数截断，赎回不退）。
- **卖交易币（回积分）**：挂出 10 交易币，标价积分；手续费为 **10 积分 / 币**（共 100 积分，赎回不退）。
- **单套理论利润**：
  $$\text{利润} = \text{卖币标价} - (\text{卖积分挂出} + \lfloor \text{卖积分挂出} \times 5\% \rfloor + 10 \times \text{币数})$$
- **最低利润门槛**：按每币计算，`MIN_PROFIT_PER_COIN = 5`（可在 `.env` 配置），即 10 币一套门槛 50。若双边目标价算出的理论利润低于门槛，本轮双边均不上架。

### 2. 定价规则（盘口抢排序 + 5 日均价护栏）

每天首次运行时拉取「买积分 / 买交易币」走势图计算 5 日均价（四舍五入取整）并缓存，后续每轮仅拉实时盘口与挂单历史：

| 方向 | 抢排序方式 | 5 日均价护栏 | 含义 |
| --- | --- | --- | --- |
| **卖积分**（高价优先） | 盘口最优 `+1` | **不得低于** 5 日均价（高于均价允许） | 防止低价白送积分，允许适当加价抢第一 |
| **卖交易币**（低价优先） | 盘口最优 `-1` | **不得高于** 5 日均价（低于均价允许） | 防止高价卖不出去，允许适当降价抢第一 |

**排队与风控约束**：
- **不排第一不新增**：按上述规则定价后，若仍无法严格排到盘口第一（卖积分 `目标价 > 盘口最优`，卖交易币 `目标价 < 盘口最优`），该侧本轮跳过，避免无效堆单。
- **不主动撤单**：由于赎回不退手续费，已有落后挂单不撤回，仅自然等待成交。
- **前排深度上限**：同一前排价最多保留 `FRONT_DEPTH = 3` 份自己的 10 币挂单（可在 `.env` 配置）：
  - 前排已满且未越过均价护栏 → 维持现挂，不再新增；
  - 前排不足 → 本轮先补 1 份（受商店冷却限制，每轮每侧最多提交 1 份）。

### 3. 轮询间隔与补单节奏

自动模式（`--auto`）每轮结束后先断开 WebSocket，按当前北京时间动态等待后再重连登录：

- **常规时段**：
  - **工作日**：`12:00–15:00`、`17:00–24:00` 为高峰（**10 分钟**），其余时段平峰（**30 分钟**）。
  - **周末**：`00:00–01:00`、`10:00–24:00` 为高峰（**10 分钟**），`01:00–10:00` 为平峰（**30 分钟**）。
  - 时段依据自己历史成交单的小时分布，可用 `analyze_market.py` 定期复核。
- **前排补齐（最高优先）**：若本轮实际可挂且挂完后前排仍不足 `FRONT_DEPTH` 份、利润达到门槛，缩短至 **2–3 分钟**随机等待后再补（若因余额不足跳过则不触发）。
- **落后快检**：若有一侧排不进第一、但利润仍 `≥ 50`，最长等待不超过 **10 分钟**。
- **跨日结算**：临近 `00:00` 时会自动卡点唤醒，结算昨日 FIFO 配对利润。

### 4. 验证码与断线容错

- **登录协议**：先通过 `/Account/Csrf` + `/Account/Login` 获取登录 Cookie，再强制 HTTP/1.1 握手连接 `wss://<host>/Client/Ws`。
- **验证码处理**：自动调用 `ocr_captcha.py` 识别，最多连续重试 **3 次**；全部失败或服务端提示验证码频繁时，暂停 **10 分钟**后重新登录。识别错误的图片会自动归档到 `captcha_wrong/`，通过的样本归档到 `captcha_ok/`，便于后续微调模型（参见 `CAPTCHA_TRAIN.md`）。
- **异常自愈**：`--auto` 模式下遇到网络抖动、握手被拒或协议异常不会退出，自动关闭连接并短等重连。

### 5. 利润核算（FIFO）

每日统计与控制台「每日利润 / 今日成交 / 本月利润」均按 **FIFO（先进先出）** 将已成交的卖积分单与卖交易币单配对计算实际净利润；自己赎回的单据单独统计手续费，不计入配对利润。

### 6. 数据采集与分析（`analyze_market.py`）

自动模式每轮扫描会额外记录三类数据（只读，不影响下单）：

| 表 | 内容 |
| --- | --- |
| `market_snapshot` | 每轮全部数量档的盘口：每档最优价、次优价、挂单数、自己在售份数、两边 ±1 抢第一后的理论每币利润 |
| `listing_submit` | 每次提交上架时的价格、当时该档盘口最优/次优、5 日均价、余额 |
| `listing_track` | 自己每张单的生命周期：首次看到在售、成交或赎回时间 |

运行日志里每轮会多一行 `分档 …`，显示各数量档的盘口概况。攒够数据后运行：

```bash
.venv/bin/python analyze_market.py --days 14
```

输出三部分：
1. **分档盘口**：各数量档两边同时有盘的比例、最优价中位数、±1 抢第一的每币利润，用来判断要不要开其它数量档；
2. **成交速度**：按「挂单时领先/落后盘口几价」「几点挂」分组统计成交耗时，用来决定让价幅度；
3. **按小时成交**：工作日 / 周末每小时平均成交张数，并给出建议高峰小时，用来校正轮询时段。

---

## 搭建流程

### 环境要求

- Linux（推荐 Ubuntu 22.04+ / Debian 12+）
- Python 3.10+（含 `python3-venv`、`python3-pip`）
- Node.js 18+ / npm（仅构建前端时需要）
- MySQL 8.0+（可选；未配置时自动退回本地 JSON 文件存储）

### 第一步：拉取代码并配置环境变量

```bash
git clone git@github.com:xiaoyueliangnb/exg-trader-bot.git
cd exg-trader-bot
cp .env.example .env
```

编辑 `.env`，填入账号与数据库信息：

```ini
STEAM_ID=你的Steam好友代码
MENU_PASSWORD=你的菜单登录密码
SAFE_CODE=你的安全码（与登录密码一致时可留空）
WS_HOST=list.darkrp.cn:6514
SCAN_TOP=8

# 控制台监听地址（建议仅监听本机，配合 Nginx / 1Panel 反向代理对外）
HOST=127.0.0.1
PORT=8787

# MySQL 配置（如不使用可留空 MYSQL_USER / MYSQL_DATABASE）
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=jifen
MYSQL_PASSWORD=你的数据库密码
MYSQL_DATABASE=jifen

# 策略参数（可选）
FRONT_DEPTH=3            # 同一前排价最多挂几份
MIN_PROFIT_PER_COIN=5    # 每币最低利润，10 币一套即 50

# 控制台（可选）
CONSOLE_TOKEN=           # 控制台口令，留空则不鉴权（公网访问务必设置）
BOT_AUTOSTART=1          # 服务启动时自动拉起挂单进程
```

### 第二步：初始化 MySQL（推荐）

在 MySQL 中创建数据库、用户并导入表结构：

```bash
mysql -u root -p < schema.sql
```

随后按 `.env` 中的 `MYSQL_USER` / `MYSQL_PASSWORD` 为该用户授予 `jifen.*` 权限。

### 第三步：安装依赖并启动服务

#### 方式 A：使用一键部署脚本（推荐，自动配置 systemd）

```bash
sudo bash deploy.sh
```

脚本会自动完成：
1. 创建 `.venv` 并安装 `requirements.txt` 依赖；
2. 如未构建前端，自动在 `web/` 下执行 `npm install && npm run build`；
3. 生成并启用 `jifen.service`（默认监听 `127.0.0.1:8787`）。

> 注意：`deploy.sh` 里 `systemd` 服务默认运行用户为 `ubuntu`，若服务器用户名不同，请先修改脚本中的 `User=` / `Group=`。

#### 方式 B：手动安装与前台运行

```bash
# 1. Python 虚拟环境
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

# 2. 构建前端静态资源
cd web && npm install && npm run build && cd ..

# 3. 启动 Web 控制台
.venv/bin/python api.py
```

### 第四步：配置反向代理（可选）

在 Nginx 或 1Panel 中新建反向代理站点，将外部端口转发至 `http://127.0.0.1:8787` 即可通过浏览器访问控制台。

---

## 使用方法

### 1. Web 控制台（推荐）

浏览器打开反代地址（或本地 `http://127.0.0.1:8787`）：

- 账户余额、5 日均价、实盘每套利润、今日已上 / 成交 / 利润、昨日与本月利润；
- **实时盘口**：10 币档两侧盘口第一 / 第二、均价护栏、本轮目标价、自己在售份数，可展开查看其它数量档；
- 顶部状态显示当前阶段（扫描中 / 等待下一轮 / 商店冷却 / 验证码暂停）和下一轮倒计时；
- 每日利润近 30 天柱状图与累计、日均统计；
- 点击指标卡片可弹窗查看今日挂单明细、FIFO 成交配对与逐笔利润算式；
- **启动 / 停止**（停止需二次确认）控制后台 `scan.py --auto`；日志按成功 / 告警 / 错误着色，可筛选。

> 服务启动时会自动拉起挂单进程（`BOT_AUTOSTART=0` 可关闭）；进程意外退出 30 秒后自动重启；日志按天保存在 `logs/`。
>
> 控制台对公网开放时，务必在 `.env` 设置 `CONSOLE_TOKEN`，浏览器首次访问需输入该口令。

后续计划与待办见 [`PLAN.md`](PLAN.md)。

### 2. 命令行运行（`scan.py`）

```bash
# 仅扫描一次盘口与理论利润（不下真实单）
.venv/bin/python scan.py

# 预演上架计划（不提交）
.venv/bin/python scan.py --list

# 强制刷新今日 5 日均价缓存
.venv/bin/python scan.py --list --refresh-avg

# 单轮交互式真实上架（每轮结束询问是否继续）
.venv/bin/python scan.py --list --execute

# 无人值守自动循环挂单（与控制台「启动」一致）
.venv/bin/python scan.py --auto

# 仅挂单侧（可选 both / coins / points）
.venv/bin/python scan.py --auto --side points

# 开启详细协议调试日志
SCAN_VERBOSE=1 .venv/bin/python scan.py
```

### 3. 常用运维命令

```bash
# 查看服务状态
systemctl status jifen.service

# 重启控制台服务
sudo systemctl restart jifen.service

# 查看服务日志
journalctl -u jifen.service -f
```

---

## 免责声明

本项目仅用于个人学习与交易数据监控，请妥善保管 `.env` 凭证文件，切勿将密码或敏感配置提交至公开仓库。
