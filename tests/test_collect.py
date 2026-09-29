import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import collect  # noqa: E402

NOW = 1_790_000_000.0


def token_count_line(primary=None, secondary=None, timestamp="2026-09-29T01:29:10.322Z", plan="plus"):
    return json.dumps({
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "limit_id": "codex",
                "primary": primary,
                "secondary": secondary,
                "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
                "plan_type": plan,
                "rate_limit_reached_type": None,
            },
        },
    })


def write_rollout(home: Path, name: str, lines, mtime=None) -> Path:
    day = home / "sessions/2026/09/29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_windows_are_classified_by_minutes_not_field_name(self):
        weekly_as_primary = {"used_percent": 8.0, "window_minutes": 10080, "resets_at": NOW + 3600}
        write_rollout(self.home, "a", [token_count_line(primary=weekly_as_primary, secondary=None)])
        account = collect.collect_codex("codex", "Codex", self.home, NOW)
        self.assertTrue(account["ok"])
        self.assertEqual(set(account["windows"]), {"week"})
        self.assertEqual(account["windows"]["week"]["used_percent"], 8.0)

    def test_short_and_weekly_windows(self):
        write_rollout(self.home, "a", [token_count_line(
            primary={"used_percent": 38.0, "window_minutes": 300, "resets_at": NOW + 60},
            secondary={"used_percent": 7.0, "window_minutes": 10080, "resets_at": NOW + 86400},
        )])
        windows = collect.collect_codex("codex", "Codex", self.home, NOW)["windows"]
        self.assertEqual(windows["5h"]["used_percent"], 38.0)
        self.assertEqual(windows["week"]["used_percent"], 7.0)

    def test_expired_window_shows_zero_and_keeps_raw_value(self):
        write_rollout(self.home, "a", [token_count_line(
            primary={"used_percent": 38.0, "window_minutes": 300, "resets_at": NOW - 1},
        )])
        window = collect.collect_codex("codex", "Codex", self.home, NOW)["windows"]["5h"]
        self.assertTrue(window["reset"])
        self.assertEqual(window["used_percent"], 0.0)
        self.assertEqual(window["raw_used_percent"], 38.0)

    def test_uses_last_record_in_newest_file(self):
        old = {"used_percent": 1.0, "window_minutes": 300, "resets_at": NOW + 60}
        new = {"used_percent": 2.0, "window_minutes": 300, "resets_at": NOW + 60}
        newest = {"used_percent": 3.0, "window_minutes": 300, "resets_at": NOW + 60}
        write_rollout(self.home, "old", [token_count_line(primary=old)], mtime=NOW - 100)
        write_rollout(self.home, "new", [token_count_line(primary=new), token_count_line(primary=newest)], mtime=NOW)
        account = collect.collect_codex("codex", "Codex", self.home, NOW)
        self.assertEqual(account["windows"]["5h"]["used_percent"], 3.0)

    def test_falls_back_when_newest_file_has_no_limits(self):
        usable = {"used_percent": 5.0, "window_minutes": 300, "resets_at": NOW + 60}
        write_rollout(self.home, "older", [token_count_line(primary=usable)], mtime=NOW - 100)
        write_rollout(self.home, "fresh", ['{"type":"session_meta"}', token_count_line()], mtime=NOW)
        account = collect.collect_codex("codex", "Codex", self.home, NOW)
        self.assertEqual(account["windows"]["5h"]["used_percent"], 5.0)

    def test_reads_backwards_across_blocks(self):
        record = token_count_line(primary={"used_percent": 9.0, "window_minutes": 300, "resets_at": NOW + 60})
        filler = json.dumps({"type": "response_item", "text": "x" * 5000})
        original = collect.TAIL_BLOCK
        collect.TAIL_BLOCK = 4096
        try:
            write_rollout(self.home, "big", [record] + [filler] * 20)
            account = collect.collect_codex("codex", "Codex", self.home, NOW)
        finally:
            collect.TAIL_BLOCK = original
        self.assertEqual(account["windows"]["5h"]["used_percent"], 9.0)

    def test_missing_home_reports_error(self):
        account = collect.collect_codex("codex", "Codex", self.home / "missing", NOW)
        self.assertFalse(account["ok"])
        self.assertIn("error", account)


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.vibe = self.state / "vibe-rl.json"  # absent unless a test writes it

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, payload, mtime=None):
        path = self.state / collect.CLAUDE_STATE_FILE
        path.write_text(json.dumps(payload), encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    def write_vibe(self, payload, mtime=None):
        self.vibe.write_text(json.dumps(payload), encoding="utf-8")
        if mtime is not None:
            os.utime(self.vibe, (mtime, mtime))

    def claude(self):
        return collect.collect_claude(self.state, NOW, vibe_island_rl=self.vibe)

    def test_parses_five_hour_and_seven_day(self):
        self.write_state({"rate_limits": {
            "five_hour": {"used_percentage": 12, "resets_at": NOW + 600},
            "seven_day": {"used_percentage": 30, "resets_at": "2026-10-05T00:00:00Z"},
        }})
        account = self.claude()
        self.assertTrue(account["ok"])
        self.assertEqual(account["windows"]["5h"]["used_percent"], 12.0)
        self.assertEqual(account["windows"]["week"]["used_percent"], 30.0)
        self.assertIsNotNone(account["windows"]["week"]["resets_at"])

    def test_reads_vibe_island_cache_format(self):
        self.write_vibe({"five_hour": {"used_percentage": 8, "resets_at": NOW + 600},
                         "seven_day": {"used_percentage": 3, "resets_at": NOW + 86400}})
        account = self.claude()
        self.assertTrue(account["ok"])
        self.assertEqual(account["source"], str(self.vibe))
        self.assertEqual(account["windows"]["5h"]["used_percent"], 8.0)
        self.assertEqual(account["windows"]["week"]["used_percent"], 3.0)

    def test_prefers_the_fresher_source(self):
        self.write_vibe({"five_hour": {"used_percentage": 8, "resets_at": NOW + 600}}, mtime=NOW - 100)
        self.write_state({"rate_limits": {"five_hour": {"used_percentage": 20, "resets_at": NOW + 600}}}, mtime=NOW)
        self.assertEqual(self.claude()["windows"]["5h"]["used_percent"], 20.0)

    def test_ignores_entries_without_usage(self):
        self.write_state({"rate_limits": {
            "five_hour": {"used_percentage": 12, "resets_at": NOW + 600},
            "spend_limit": {"amount": 100},
        }})
        self.assertEqual(set(self.claude()["windows"]), {"5h"})

    def test_missing_file_reports_hint(self):
        account = self.claude()
        self.assertFalse(account["ok"])
        self.assertIn("Vibe Island", account["error"])

    def test_unknown_format_reports_keys(self):
        self.write_state({"rate_limits": {"mystery": {"value": 1}}})
        self.assertFalse(self.claude()["ok"])


class TimeTests(unittest.TestCase):
    def test_to_epoch_variants(self):
        self.assertEqual(collect.to_epoch(1790000000), 1790000000.0)
        self.assertEqual(collect.to_epoch(1790000000000), 1790000000.0)
        self.assertEqual(collect.to_epoch("1790000000"), 1790000000.0)
        self.assertAlmostEqual(collect.to_epoch("2026-09-29T01:29:10Z"), 1790645350.0)
        self.assertIsNone(collect.to_epoch("not a time"))
        self.assertIsNone(collect.to_epoch(None))


class TableTests(unittest.TestCase):
    def test_table_shows_remaining_and_errors(self):
        data = {"generated_at": NOW, "accounts": [
            {"id": "a", "name": "Claude Code", "ok": True, "updated_at": NOW - 30, "windows": {
                "5h": {"used_percent": 9.0, "resets_at": NOW + 600, "reset": False},
                "week": {"used_percent": 0.0, "raw_used_percent": 38.0, "resets_at": NOW - 1, "reset": True}}},
            {"id": "b", "name": "Codex 主号", "ok": True, "updated_at": NOW - 7200, "windows": {
                "week": {"used_percent": 10.0, "resets_at": NOW + 86400, "reset": False}}},
            {"id": "c", "name": "Codex 副号", "ok": False, "error": "没有找到额度记录"},
        ]}
        table = collect.format_table(data, color=False)
        self.assertIn("剩 91% · ", table)
        self.assertIn("日 · 1天0小时", table)
        self.assertNotIn("重置", table)
        self.assertIn("更新时间", table)
        self.assertIn("剩 100%（待刷新）", table)
        self.assertIn("剩 90%", table)
        self.assertIn("⚠ 较旧", table)
        self.assertIn("没有找到额度记录", table)
        self.assertNotIn("\033[", table)

    def test_reset_text_short_window_shows_clock_time(self):
        from datetime import datetime
        expected = datetime.fromtimestamp(NOW + 600).strftime("%H:%M")
        self.assertEqual(collect.reset_text("5h", NOW + 600, NOW), expected)

    def test_reset_text_weekly_window_shows_date_and_time_left(self):
        from datetime import datetime
        target = NOW + 4 * 86400 + 14 * 3600 + 59
        moment = datetime.fromtimestamp(target)
        self.assertEqual(collect.reset_text("week", target, NOW), f"{moment.month}月{moment.day}日 · 4天14小时")
        self.assertTrue(collect.reset_text("week", NOW + 14 * 3600 + 5, NOW).endswith("· 14小时"))

    def test_display_width_counts_cjk_as_two(self):
        self.assertEqual(collect.display_width("Codex 主号"), 10)


class StatuslineTeeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.downstream = self.dir / "downstream.sh"
        self.downstream.write_text('#!/bin/bash\necho "DOWNSTREAM:$(cat)"\n')
        self.downstream.chmod(0o755)
        self.env = dict(os.environ, QUOTA_STATE_DIR=str(self.dir / "state"),
                        QUOTA_STATUSLINE_DOWNSTREAM=str(self.downstream))

    def tearDown(self):
        self.tmp.cleanup()

    def run_tee(self, text):
        return subprocess.run(["bash", str(PROJECT / "statusline-tee.sh")], input=text,
                              capture_output=True, text=True, env=self.env, timeout=10)

    def test_passes_input_through_and_saves_rate_limits(self):
        payload = '{"rate_limits":{"five_hour":{"used_percentage":5}}}'
        result = self.run_tee(payload)
        self.assertEqual(result.stdout.strip(), f"DOWNSTREAM:{payload}")
        saved = self.dir / "state" / collect.CLAUDE_STATE_FILE
        self.assertEqual(saved.read_text(), payload)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)

    def test_does_not_overwrite_when_rate_limits_missing(self):
        self.run_tee('{"rate_limits":{"five_hour":{"used_percentage":5}}}')
        result = self.run_tee('{"model":{"display_name":"Opus"}}')
        self.assertIn("DOWNSTREAM:", result.stdout)
        saved = (self.dir / "state" / collect.CLAUDE_STATE_FILE).read_text()
        self.assertIn("rate_limits", saved)

    def test_still_passes_through_when_state_dir_unwritable(self):
        blocker = self.dir / "state"
        blocker.write_text("not a directory")
        payload = '{"rate_limits":{}}'
        result = self.run_tee(payload)
        self.assertEqual(result.stdout.strip(), f"DOWNSTREAM:{payload}")


if __name__ == "__main__":
    unittest.main()
