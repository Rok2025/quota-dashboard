-- AI 额度弹窗：Cmd+Shift+0 打开 / 关闭，Esc 或点击弹窗外部关闭；命令行可用 open -g hammerspoon://ai-quota。
-- 页面来自 quota-dashboard 本地服务（http://127.0.0.1:8765/?popup）。

local M = {}

local URL = "http://127.0.0.1:8765/?popup"
local WIDTH, HEIGHT = 680, 310

local view = nil
local escKey = nil
local clickWatcher = nil

local function serviceUp()
  local status = hs.http.get("http://127.0.0.1:8765/api/quota", nil)
  return status == 200
end

local LOG = os.getenv("HOME") .. "/.local/state/quota/hammerspoon.log"

local function log(message)
  local file = io.open(LOG, "a")
  if file then
    file:write(os.date("%Y-%m-%d %H:%M:%S ") .. message .. "\n")
    file:close()
  end
end

local function hide()
  if view then view:hide() end
  if escKey then escKey:disable() end
  if clickWatcher then clickWatcher:stop() end
end

-- Close when a click lands outside the popup; the click itself still goes through.
-- Requires Accessibility permission for Hammerspoon; without it Esc still works.
local function outsideClick(event)
  if view and view:isVisible() then
    local point = event:location()
    local frame = view:frame()
    local inside = point.x >= frame.x and point.x <= frame.x + frame.w
      and point.y >= frame.y and point.y <= frame.y + frame.h
    if not inside then
      hs.timer.doAfter(0, hide) -- stop the tap outside its own callback
    end
  end
  return false
end

local function show()
  if not serviceUp() then
    hs.alert.show("AI 额度看板服务没有运行：在 quota-dashboard 目录执行 ./install.sh")
    return
  end
  local screen = hs.mouse.getCurrentScreen():frame()
  local rect = {
    x = screen.x + (screen.w - WIDTH) / 2,
    y = screen.y + (screen.h - HEIGHT) / 3,
    w = WIDTH,
    h = HEIGHT,
  }
  if not view then
    view = hs.webview.new(rect)
      :windowStyle({ "borderless" })
      :transparent(true)
      :shadow(true)
      :level(hs.drawing.windowLevels.floating)
      :allowTextEntry(false)
      :url(URL)
  else
    view:frame(rect):url(URL) -- reload so the numbers are current
  end
  view:show()
  escKey:enable()
  clickWatcher:start()
end

function M.toggle()
  local ok, err = pcall(function()
    if view and view:isVisible() then hide() else show() end
  end)
  if not ok then
    log("toggle failed: " .. tostring(err))
    hs.alert.show("AI 额度弹窗出错，详见 " .. LOG)
  end
end

escKey = hs.hotkey.new({}, "escape", hide)
clickWatcher = hs.eventtap.new({
  hs.eventtap.event.types.leftMouseDown,
  hs.eventtap.event.types.rightMouseDown,
}, outsideClick)
hs.hotkey.bind({ "cmd", "shift" }, "0", M.toggle)
-- Also callable from a shell: open -g hammerspoon://ai-quota
hs.urlevent.bind("ai-quota", function() M.toggle() end)

return M
