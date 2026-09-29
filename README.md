# quota-dashboard

本机 AI 额度看板：同时查看 Claude Code 与两个 Codex 账号的 5 小时 / 每周剩余额度。

- 只读本机数据，不调用任何接口，不读取登录凭据，不消耗额度。
- 本地服务只监听 `127.0.0.1`，不对外开放。
- 数据在你使用工具时刷新，显示的是“最后一次使用时”的额度；每个账号标注数据时间。

## 三种查看方式

| 方式 | 入口 | 说明 |
|---|---|---|
| 快捷键弹窗 | `Cmd+Shift+0` | 屏幕中央弹出；再按一次、`Esc` 或点击外部关闭 |
| 网页 | `http://127.0.0.1:8765` | 每 30 秒自动刷新 |
| 命令行 | `ai-quota`（`--json` 输出原始数据） | 直接读本机文件，不依赖本地服务 |

三种方式共用 `collect.py` 的采集结果，数字一致。

## 数据来源

| 账号 | 来源 | 刷新时机 |
|---|---|---|
| Claude Code | Vibe Island 状态栏脚本已缓存的 `~/.vibe-island/cache/rl.json`（需开启 Vibe Island 用量显示）；备用：`statusline-tee.sh` 保存的 `~/.local/state/quota/claude-statusline.json`，两者取较新的 | Claude Code 刷新状态栏时 |
| Codex 主号 | `~/.codex/sessions/**/rollout-*.jsonl` 中最后一条 `rate_limits` | Codex 对话产生 `token_count` 事件时 |
| Codex 副号 | `~/.codex-plus/sessions/**/rollout-*.jsonl`，同上 | 同上 |

Codex 的 `primary` / `secondary` 不固定对应 5 小时或每周，按 `window_minutes` 判断：`≤ 1440` 视为 5 小时窗口，否则视为每周窗口。记录里没有的窗口显示“无”。

## 显示规则

- 大数字为**剩余**百分比；剩余 ≤ 20% 黄色，≤ 5% 红色。
- 5 小时窗口：进度条右侧显示重置时刻（如 `19:50`）。
- 每周窗口：进度条右侧显示重置日期（如 `10月5日`），其下叠放剩余时长（如 `6天0小时`）。
- 窗口已过重置时间但尚无新数据：显示 100% 与“待刷新”。
- 数据超过 10 分钟：账号名下显示“x 分钟前”；超过 1 小时：该行调淡、时间标黄。
- 右上角“更新时间”为页面最近一次拉取数据的时间。

## 需求分级（MoSCoW）

### Must（已实现）

- **M1 Codex 双账号采集**：找到修改时间最新、含 `rate_limits` 的会话文件，从文件末尾读取，按 `window_minutes` 归类窗口。
- **M2 Claude 采集**：优先读取 Vibe Island 已缓存的 `rl.json`，不改动状态栏配置；未使用 Vibe Island 时，可改用中转脚本 `statusline-tee.sh`（保存后原样转给下游，保存失败不影响状态栏，缺少 `rate_limits` 时不覆盖旧数据）。
- **M3 汇总接口**：`/api/quota` 在请求时汇总三个账号（缓存 5 秒），输出统一结构；单个账号出错只影响自己那一行。
- **M4 展示页面**：一个账号一行，5 小时 / 每周各一格：剩余百分比、进度条、重置时间。
- **M5 窗口已重置**：`resets_at` 已过时按已重置处理，保留重置前的原始数值。
- **M6 本机安全**：只监听 `127.0.0.1`；状态文件权限 600；不读取 `auth.json` 等凭据文件。

### Should（已实现）

- **S1 开机自启**：launchd 常驻本地服务，意外退出自动拉起（`install.sh` / `uninstall.sh`）。
- **S2 阈值配色**：剩余 ≤ 20% 黄色、≤ 5% 红色。
- **S3 数据时间**：每个账号标注数据时间，过旧时调淡提示。
- **S4 自动刷新**：页面每 30 秒重新拉取。
- **S5 自动化测试**：采集解析、窗口归类、重置判断、时间格式、终端表格、中转脚本透传。
- **S6 快捷键弹窗**：Hammerspoon `Cmd+Shift+0` 弹出，`Esc` / 点击外部关闭。
- **S7 命令行查看**：`ai-quota` 输出剩余额度表格。

### Could（暂不实现）

- 菜单栏常驻最紧张的额度。
- 剩余额度偏低时系统通知。
- 历史用量曲线。

### Won't（明确不做）

- 主动发请求刷新额度（会消耗额度）。
- 调用 claude.ai / ChatGPT 网页后台的非官方用量接口（需要登录凭据，接口不稳定）。
- 发布到外网或同步到云端。

## 设计变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-09-29 | 汇总由“launchd 每分钟生成 `quota.json`”改为“请求时实时汇总” | 单次采集约 0.06 秒，少一个定时任务，数据也更新 |
| 2026-09-29 | Claude 数据改为读取 Vibe Island 缓存，不改 `statusLine.command` | Vibe Island 已缓存 `rate_limits`，且其脚本要求不改该配置；中转脚本保留为备用 |
| 2026-09-29 | 新增快捷键弹窗与 `ai-quota` 命令 | 不打开浏览器也能一眼查看 |
| 2026-09-29 | 页面改为一行一个账号、显示剩余而非已用 | 与命令行口径一致，信息一眼看完 |

## 文件

```text
quota-dashboard/
├── collect.py            # 采集与汇总；也是 ai-quota 命令本体
├── serve.py              # 本地服务：/ 页面，/?popup 弹窗页面，/api/quota 数据
├── statusline-tee.sh     # Claude 状态栏中转脚本（备用）
├── web/index.html        # 看板页面（网页与弹窗共用）
├── hammerspoon/          # 快捷键弹窗模块
├── launchd/              # launchd 配置模板
├── install.sh            # 安装并启动常驻服务
├── uninstall.sh          # 停止并移除常驻服务
└── tests/                # 自动化测试
```

## 安装与使用

```bash
# 常驻服务（网页与弹窗都依赖它）
./install.sh
./uninstall.sh

# 命令行查看
ln -s "$PWD/collect.py" ~/.local/bin/ai-quota
ai-quota
ai-quota --json

# 手动前台启动（调试用）
python3 serve.py

# 测试
python3 -m unittest discover -s tests
```

### 快捷键弹窗（Hammerspoon）

- 安装：`ln -s "$PWD/hammerspoon/ai_quota.lua" ~/.hammerspoon/ai_quota.lua`，在 `~/.hammerspoon/init.lua` 加入 `require("ai_quota")`，重新加载 Hammerspoon。
- 使用：`Cmd+Shift+0` 打开 / 关闭；`Esc` 或点击弹窗外部关闭（点击关闭需要 Hammerspoon 的辅助功能权限）；命令行可用 `open -g hammerspoon://ai-quota`。
- 弹窗读取本地服务的 `/?popup` 页面，需要常驻服务在运行；出错时写入 `~/.local/state/quota/hammerspoon.log`。
- 移除：删掉 `init.lua` 中的 `require("ai_quota")` 与 `~/.hammerspoon/ai_quota.lua` 链接，然后重新加载 Hammerspoon。

### 接入 Claude 状态栏（仅在未使用 Vibe Island 时需要）

使用 Vibe Island 且开启用量显示时无需任何配置。Vibe Island 的脚本要求不要修改 `statusLine.command`。

不用 Vibe Island 时，把 `~/.claude/settings.json` 的 `statusLine.command` 改为本目录的 `statusline-tee.sh`。脚本默认把 JSON 转给 `~/.vibe-island/bin/vibe-island-statusline`，可用环境变量 `QUOTA_STATUSLINE_DOWNSTREAM` 改为其他下游命令。

恢复原状：把 `statusLine.command` 改回 `/Users/freeman/.vibe-island/bin/vibe-island-statusline`。

## 常见问题

- **某个账号数据很旧**：该工具最近没用过，使用一次即更新。
- **Claude 一行不再更新**：检查 Vibe Island 的用量显示是否开启，或改用 `statusline-tee.sh`。
- **网页 / 弹窗打不开**：`launchctl print gui/$(id -u)/com.freeman.quota-dashboard` 查看服务状态，或重新运行 `./install.sh`；日志在 `~/.local/state/quota/serve.log`。
- **Python 路径变化**：`install.sh` 默认使用 `/opt/homebrew/bin/python3`，可用 `QUOTA_PYTHON` 指定后重新安装。

## 环境变量

| 变量 | 默认值 | 作用 |
|---|---|---|
| `QUOTA_VIBE_ISLAND_RL` | `~/.vibe-island/cache/rl.json` | Vibe Island 缓存的 Claude 额度文件 |
| `QUOTA_STATE_DIR` | `~/.local/state/quota` | 状态文件与日志目录 |
| `QUOTA_STATUSLINE_DOWNSTREAM` | `~/.vibe-island/bin/vibe-island-statusline` | 中转脚本的下游状态栏命令 |
| `QUOTA_PORT` | `8765` | 本地服务端口 |
| `QUOTA_PYTHON` | `/opt/homebrew/bin/python3` | `install.sh` 使用的 Python |
