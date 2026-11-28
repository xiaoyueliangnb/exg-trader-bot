# EXG 积分 / 交易币自动挂单

CS2 EXG 市场扫描、自动挂单和 Web 控制台。账号写在 `.env`，不要提交。

## 搭建

需要 Python 3.10+。MySQL 可选，不配则用本地 JSON。

```bash
git clone git@github.com:xiaoyueliangnb/exg-trader-bot.git
cd exg-trader-bot
cp .env.example .env   # 填 STEAM_ID、MENU_PASSWORD、SAFE_CODE
mysql -u root -p < schema.sql
sudo bash deploy.sh
```

`deploy.sh` 会建虚拟环境、安装 Python 依赖，并注册 `jifen.service`（默认 `ubuntu` 用户，监听 `127.0.0.1:8787`）。用 Nginx 或 1Panel 反代到这个地址。

公网访问时在 `.env` 设置 `CONSOLE_TOKEN`。`BOT_AUTOSTART=1` 时服务启动会自动跑挂单。

## 运行

```bash
systemctl status jifen.service
sudo systemctl restart jifen.service
journalctl -u jifen.service -f

.venv/bin/python scan.py              # 只看盘口
.venv/bin/python scan.py --auto       # 自动挂单
.venv/bin/python analyze_market.py --days 14
```

控制台可启停自动挂单，查看盘口、利润、分析和日志。

## 挂单规则

- 只做 10 币档。卖积分不得低于 5 日均价，卖交易币不得高于 5 日均价。
- 定价后必须严格排第一才上架。已有挂单不撤。每轮每侧最多新挂 1 份，同一前排价最多 `FRONT_DEPTH` 份（默认 3）。
- 每币利润低于 `MIN_PROFIT_PER_COIN`（默认 5）则本轮两边都不挂。
- 工作日 12–15、17–24 点，周末 0–1、10–24 点，间隔 10 分钟；其余 30 分钟。前排没满时 2–3 分钟补一次。
- 验证码 OCR 最多 3 次，失败后停 10 分钟。`--auto` 遇错不退出。
