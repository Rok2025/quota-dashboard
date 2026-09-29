#!/bin/bash
# Stop and remove the quota-dashboard launchd service. Data files are kept.
set -euo pipefail

LABEL="com.freeman.quota-dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "已停止并移除 $LABEL（~/.local/state/quota 中的数据保留）"
