#!/bin/bash
# Install and start the quota-dashboard launchd service (127.0.0.1 only).
set -euo pipefail

LABEL="com.freeman.quota-dashboard"
PROJECT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${QUOTA_PYTHON:-/opt/homebrew/bin/python3}"
LOG_DIR="${QUOTA_STATE_DIR:-$HOME/.local/state/quota}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${QUOTA_PORT:-8765}"

if [ ! -x "$PYTHON" ]; then
  echo "找不到 Python：$PYTHON（可用 QUOTA_PYTHON 指定）" >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
chmod 700 "$LOG_DIR"

sed -e "s#__PYTHON__#$PYTHON#g" \
    -e "s#__PROJECT__#$PROJECT#g" \
    -e "s#__LOG_DIR__#$LOG_DIR#g" \
    "$PROJECT/launchd/$LABEL.plist.template" >"$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$PORT/api/quota" >/dev/null 2>&1; then
    echo "已启动：http://127.0.0.1:$PORT"
    exit 0
  fi
  sleep 0.5
done

echo "服务没有响应，查看日志：$LOG_DIR/serve.log" >&2
exit 1
