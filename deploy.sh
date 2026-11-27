# 服务器上一键安装并启动（Ubuntu/Debian + 1Panel）
# 用法：解压后在项目目录执行  sudo bash deploy.sh
# 服务听 127.0.0.1:8787，由 1Panel 网站反向代理对外，不要指到开发机。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"
SERVICE_NAME="${SERVICE_NAME:-jifen}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令：$1"
    exit 1
  }
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "请先安装 Python 3.10+：sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip"
  exit 1
fi

if [ ! -f "$ROOT/.env" ]; then
  echo "没有 .env，已从 .env.example 复制，请填入 STEAM_ID / MENU_PASSWORD / SAFE_CODE"
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -U pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"

if [ -f "$ROOT/schema.sql" ] && grep -q '^MYSQL_DATABASE=' "$ROOT/.env" 2>/dev/null; then
  "$ROOT/.venv/bin/python" "$ROOT/db.py" --import-json || echo "json 导入跳过（先建好 MySQL 表）"
fi

if [ ! -f "$ROOT/web/dist/index.html" ]; then
  need npm
  (cd "$ROOT/web" && npm install && npm run build)
fi

cat > "$ROOT/jifen.service" <<EOF
[Unit]
Description=jifen listing console
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT
User=ubuntu
Group=ubuntu
Environment=HOST=$HOST
Environment=PORT=$PORT
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$ROOT/.env
ExecStart=$ROOT/.venv/bin/python $ROOT/api.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

if [ "$(id -u)" -eq 0 ]; then
  cp "$ROOT/jifen.service" "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
  echo "已安装 systemd 服务 ${SERVICE_NAME}，监听 ${HOST}:${PORT}"
  echo "1Panel：网站 -> 反向代理 -> http://${HOST}:${PORT}"
  systemctl status "${SERVICE_NAME}.service" --no-pager || true
else
  echo "当前不是 root，改用前台启动。生产环境请：sudo bash deploy.sh"
  exec env HOST="$HOST" PORT="$PORT" PYTHONUNBUFFERED=1 "$ROOT/.venv/bin/python" "$ROOT/api.py"
fi
