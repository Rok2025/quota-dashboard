#!/usr/bin/env python3
"""Collect Claude Code and Codex rate-limit usage from local files.

Run directly to print remaining quota as a table, or the raw JSON:

    python3 collect.py
    python3 collect.py --json
"""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("QUOTA_STATE_DIR", HOME / ".local/state/quota"))
CLAUDE_STATE_FILE = "claude-statusline.json"
# Vibe Island's statusline already caches Claude's rate_limits object here.
VIBE_ISLAND_RL = Path(os.environ.get("QUOTA_VIBE_ISLAND_RL", HOME / ".vibe-island/cache/rl.json"))

CODEX_ACCOUNTS = [
    ("codex", "Codex 主号", HOME / ".codex"),
    ("codex-plus", "Codex 副号", HOME / ".codex-plus"),
]

# Codex windows up to one day are treated as the short (5h) window.
SHORT_WINDOW_MAX_MINUTES = 1440
TAIL_BLOCK = 1 << 20  # 1 MiB
TAIL_MAX = 64 << 20  # stop scanning a single file after 64 MiB from the end
MAX_ROLLOUTS_TO_TRY = 20


def to_epoch(value) -> float | None:
    """Accept epoch seconds/milliseconds or an ISO-8601 string."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e12 else float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return to_epoch(float(text))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def make_window(used_percent, window_minutes, resets_at, now: float) -> dict:
    used = float(used_percent) if used_percent is not None else None
    reset_epoch = to_epoch(resets_at)
    is_reset = reset_epoch is not None and reset_epoch <= now
    return {
        "used_percent": 0.0 if is_reset else used,
        "raw_used_percent": used,
        "window_minutes": window_minutes,
        "resets_at": reset_epoch,
        "reset": is_reset,
    }


# ---------------------------------------------------------------- Codex


def iter_rollouts_newest_first(codex_home: Path):
    """Yield rollout files ordered by mtime, newest first.

    A long session keeps writing into the directory of the day it started,
    so directory dates are not reliable; stat every file instead.
    """
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return
    found = []
    stack = [sessions]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.name.startswith("rollout-") and entry.name.endswith(".jsonl"):
                        try:
                            found.append((entry.stat().st_mtime, Path(entry.path)))
                        except OSError:
                            continue
        except OSError:
            continue
    found.sort(reverse=True)
    for _, path in found:
        yield path


def iter_lines_reversed(path: Path):
    """Yield complete lines from the end of a file, reading backwards in blocks."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        remainder = b""
        scanned = 0
        while position > 0 and scanned < TAIL_MAX:
            size = min(TAIL_BLOCK, position)
            position -= size
            scanned += size
            handle.seek(position)
            chunk = handle.read(size) + remainder
            lines = chunk.split(b"\n")
            remainder = lines.pop(0)
            for line in reversed(lines):
                if line:
                    yield line
        if position == 0 and remainder:
            yield remainder


def last_codex_rate_limits(path: Path):
    """Return (rate_limits, event_epoch) for the last usable record in a rollout."""
    for raw in iter_lines_reversed(path):
        if b'"rate_limits"' not in raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        payload = record.get("payload") or {}
        limits = payload.get("rate_limits")
        if isinstance(limits, dict) and (limits.get("primary") or limits.get("secondary")):
            return limits, to_epoch(record.get("timestamp"))
    return None, None


def codex_windows(limits: dict, now: float) -> dict:
    windows = {}
    for key in ("primary", "secondary"):
        item = limits.get(key)
        if not isinstance(item, dict):
            continue
        minutes = item.get("window_minutes")
        name = "5h" if minutes is not None and minutes <= SHORT_WINDOW_MAX_MINUTES else "week"
        windows[name] = make_window(item.get("used_percent"), minutes, item.get("resets_at"), now)
    return windows


def collect_codex(account_id: str, name: str, codex_home: Path, now: float) -> dict:
    account = {"id": account_id, "name": name, "source": str(codex_home), "ok": False}
    try:
        for index, path in enumerate(iter_rollouts_newest_first(codex_home)):
            if index >= MAX_ROLLOUTS_TO_TRY:
                break
            limits, event_epoch = last_codex_rate_limits(path)
            if limits is None:
                continue
            credits = limits.get("credits") or {}
            account.update(
                ok=True,
                updated_at=event_epoch or path.stat().st_mtime,
                plan=limits.get("plan_type"),
                credits=credits.get("balance") if isinstance(credits, dict) else None,
                limit_reached=limits.get("rate_limit_reached_type"),
                windows=codex_windows(limits, now),
            )
            return account
        account["error"] = "没有找到额度记录，使用一次 Codex 后会出现"
    except OSError as exc:
        account["error"] = f"读取失败：{exc}"
    return account


# ---------------------------------------------------------------- Claude


def claude_window_name(key: str, item: dict) -> str | None:
    lowered = key.lower()
    if "five" in lowered or "5h" in lowered or "hour" in lowered:
        return "5h"
    if "seven" in lowered or "7d" in lowered or "week" in lowered or "day" in lowered:
        return "week"
    minutes = item.get("window_minutes")
    if isinstance(minutes, (int, float)):
        return "5h" if minutes <= SHORT_WINDOW_MAX_MINUTES else "week"
    return None


def claude_source(state_dir: Path, vibe_island_rl: Path) -> Path | None:
    """Pick the freshest available source: Vibe Island cache or our relay file."""
    candidates = [p for p in (vibe_island_rl, state_dir / CLAUDE_STATE_FILE) if p.exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def collect_claude(state_dir: Path, now: float, vibe_island_rl: Path | None = None) -> dict:
    vibe_island_rl = VIBE_ISLAND_RL if vibe_island_rl is None else vibe_island_rl
    path = claude_source(state_dir, vibe_island_rl)
    account = {"id": "claude", "name": "Claude Code", "source": str(path or vibe_island_rl), "ok": False}
    if path is None:
        account["error"] = "还没有数据：开启 Vibe Island 的用量显示，或接入 statusline-tee.sh 后使用一次 Claude Code"
        return account
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        account["error"] = f"读取失败：{exc}"
        return account

    # The relay file holds the full statusline JSON; Vibe Island stores rate_limits itself.
    limits = data.get("rate_limits", data) if isinstance(data, dict) else None
    if not isinstance(limits, dict):
        account["error"] = "状态栏数据里没有 rate_limits"
        return account

    windows = {}
    for key, item in limits.items():
        if not isinstance(item, dict):
            continue
        used = item.get("used_percentage", item.get("used_percent"))
        if used is None:
            continue
        name = claude_window_name(key, item)
        if name and name not in windows:
            windows[name] = make_window(used, item.get("window_minutes"), item.get("resets_at"), now)

    if not windows:
        account["error"] = "rate_limits 格式无法识别"
        account["raw_keys"] = sorted(limits)
        return account

    account.update(ok=True, updated_at=path.stat().st_mtime, windows=windows)
    return account


# ---------------------------------------------------------------- Aggregate


def collect(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    accounts = [collect_claude(STATE_DIR, now)]
    accounts += [collect_codex(account_id, name, home, now) for account_id, name, home in CODEX_ACCOUNTS]
    return {"generated_at": now, "accounts": accounts}


# ---------------------------------------------------------------- Terminal table

STALE_SECONDS = 3600
WINDOW_LABELS = (("5h", "5 小时"), ("week", "每周"))


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def short_time(epoch: float, now: float) -> str:
    moment = datetime.fromtimestamp(epoch)
    if moment.date() == datetime.fromtimestamp(now).date():
        return moment.strftime("%H:%M")
    return f"{moment.month}/{moment.day} {moment.strftime('%H:%M')}"


def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def reset_text(key: str, reset_at: float, now: float) -> str:
    """5h window: reset clock time; weekly window: reset date plus time left."""
    moment = datetime.fromtimestamp(reset_at)
    if key == "5h":
        return moment.strftime("%H:%M")
    seconds = max(0, int(reset_at - now))
    days, hours = seconds // 86400, seconds % 86400 // 3600
    left = f"{days}天{hours}小时" if days else f"{hours}小时"
    return f"{moment.month}月{moment.day}日 · {left}"


def paint(text: str, used: float | None, color: bool) -> str:
    if not color or used is None:
        return text
    code = "31" if used >= 95 else "33" if used >= 80 else "32"
    return f"\033[{code}m{text}\033[0m"


def window_cell(key: str, window: dict | None, now: float) -> tuple[str, float | None]:
    if not window or window.get("used_percent") is None:
        return "—", None
    used = window["used_percent"]
    remaining = max(0.0, 100.0 - used)
    if window.get("reset"):
        return f"剩 {remaining:.0f}%（待刷新）", used
    reset_at = window.get("resets_at")
    suffix = f" · {reset_text(key, reset_at, now)}" if reset_at else ""
    return f"剩 {remaining:.0f}%{suffix}", used


def format_table(data: dict, color: bool = False) -> str:
    now = data["generated_at"]
    header = ["账号", "5 小时", "每周", "数据时间"]
    rows = []
    for account in data["accounts"]:
        if not account.get("ok"):
            rows.append(([account["name"], account.get("error", "暂无数据"), "", ""], [None, None]))
            continue
        cells, levels = [account["name"]], []
        for key, _ in WINDOW_LABELS:
            text, used = window_cell(key, account["windows"].get(key), now)
            cells.append(text)
            levels.append(used)
        age = now - account["updated_at"]
        stamp = f"{short_time(account['updated_at'], now)}（{ago(age)}）"
        cells.append(stamp + (" ⚠ 较旧" if age > STALE_SECONDS else ""))
        rows.append((cells, levels))

    widths = [max(display_width(r[i]) for r in [header] + [c for c, _ in rows]) for i in range(4)]
    lines = [f"AI 额度剩余 · 更新时间 {short_time(now, now)}", "  ".join(pad(h, w) for h, w in zip(header, widths)).rstrip()]
    for cells, levels in rows:
        parts = []
        for index, (cell, width) in enumerate(zip(cells, widths)):
            text = pad(cell, width)
            if index in (1, 2):
                text = paint(text, levels[index - 1], color)
            parts.append(text)
        lines.append("  ".join(parts).rstrip())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    data = collect()
    if "--json" in args:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        print(format_table(data, color=color))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
