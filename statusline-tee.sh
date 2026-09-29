#!/bin/bash
# Claude Code statusline relay for quota-dashboard.
# Saves the statusline JSON (only when it carries rate_limits), then passes the
# same input to the downstream statusline so the visible status line is unchanged.

STATE_DIR="${QUOTA_STATE_DIR:-$HOME/.local/state/quota}"
DOWNSTREAM="${QUOTA_STATUSLINE_DOWNSTREAM:-$HOME/.vibe-island/bin/vibe-island-statusline}"

input=$(cat)

case "$input" in
  *'"rate_limits"'*)
    (
      umask 077
      mkdir -p "$STATE_DIR" &&
        tmp="$STATE_DIR/.claude-statusline.$$" &&
        printf '%s' "$input" >"$tmp" &&
        mv -f "$tmp" "$STATE_DIR/claude-statusline.json"
    ) 2>/dev/null || true
    ;;
esac

if [ -x "$DOWNSTREAM" ]; then
  printf '%s' "$input" | exec "$DOWNSTREAM"
fi
