local wezterm = require("wezterm")
local act = wezterm.action

-- 上中下三等分布局 (Top/Middle/Bottom)
wezterm.on("Split Vertically (Top/Middle/Bottom)", function(window, pane)
    -- 先向上分割，创建底部区域 (占 1/3)
    local bottom = pane:split({ direction = "Up", size = 0.333 })
    -- 再在剩余区域向上分割，创建中部和顶部 (各占 1/3)
    local top = pane:split({ direction = "Up", size = 0.5 })
end)

-- 田字形四等分布局 (TopLeft/TopRight/BottomLeft/BottomRight)
wezterm.on("Split (TopLeft/TopRight/BottomLeft/BottomRight)", function(window, pane)
    local right = pane:split({ direction = "Right", size = 0.5 })
    local top_left = pane:split({ direction = "Up", size = 0.5 })
    local top_right = right:split({ direction = "Up", size = 0.5 })
end)

return {
    max_fps = 165,
    enable_scroll_bar = true,
    hide_tab_bar_if_only_one_tab = true,
    tab_bar_at_bottom = true,
    font = wezterm.font_with_fallback({
        "JetBrains Mono", -- 代码 <内置>
        "FiraCode Nerd Font", -- 炫酷图标
        "Noto Sans CJK SC", -- 汉字
        "DejaVu Sans Mono",
        "Noto Sans Symbols2",
        "Noto Serif Grantha", -- 古印度文
        "Noto Sans Gujarati UI", -- 古吉拉特文
    }),
    font_size = 16.5,
    color_scheme = "Gruvbox Material (Gogh)",
    force_reverse_video_cursor = true, -- 光标反色
    window_background_opacity = 0.8,
    line_height = 1.1,
    window_padding = {
        left = 0,
        right = 0,
        top = 0,
        bottom = 0,
    },
    exit_behavior = "Close",
    keys = {
        -- 命令面板 (Ctrl+Shift+P) - 可搜索 Top/Middle/Bottom 等命令
        { key = "P", mods = "CTRL|SHIFT", action = act.ActivateCommandPalette },
        -- 重新加载配置 (Ctrl+Shift+R)
        { key = "R", mods = "CTRL|SHIFT", action = act.ReloadConfiguration },
        -- 全屏切换 (Win+F = Full Screen)
        { key = "F", mods = "SUPER", action = act.ToggleFullScreen },
        -- 分屏跳转 (Alt+hjkl)
        { key = "h", mods = "ALT", action = act.ActivatePaneDirection("Left") },
        { key = "j", mods = "ALT", action = act.ActivatePaneDirection("Down") },
        { key = "k", mods = "ALT", action = act.ActivatePaneDirection("Up") },
        { key = "l", mods = "ALT", action = act.ActivatePaneDirection("Right") },
        -- 三等分窗口 - 仅命令面板可搜索，使用 F20 虚拟键（不占用常用键）
        { key = "F20", mods = "NONE", action = act.EmitEvent("Split Vertically (Top/Middle/Bottom)") },
        -- 四等分窗口 - 仅命令面板可搜索，使用 F21 虚拟键（不占用常用键）
        { key = "F21", mods = "NONE", action = act.EmitEvent("Split (TopLeft/TopRight/BottomLeft/BottomRight)") },
    },
}
