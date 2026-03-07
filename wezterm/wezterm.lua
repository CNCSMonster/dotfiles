local wezterm = require("wezterm")

-- 三等分布局事件 (竖屏上中下)
wezterm.on("split-vertical-thirds", function(window, pane)
    -- 当前 pane 变成底部 (33%)
    local bottom = pane:split({
        direction = "Up",
        size = 0.333,
    })
    -- 原 pane 现在是上部 67%，再分割成中部和顶部
    local top = pane:split({
        direction = "Up",
        size = 0.5, -- 剩余空间的 50%，即总体的 33.3%
    })
    -- 最终: top(33%) / pane(33%) / bottom(33%)
end)

-- 田字形四等分布局事件
wezterm.on("split-quadrants", function(window, pane)
    -- 先水平分割成左右两半
    local right = pane:split({
        direction = "Right",
        size = 0.5,
    })
    -- 左边垂直分割成上下两半
    local top_left = pane:split({
        direction = "Up",
        size = 0.5,
    })
    -- 右边垂直分割成上下两半
    local top_right = right:split({
        direction = "Up",
        size = 0.5,
    })
    -- 最终布局:
    -- top_left | top_right
    -- ---------+----------
    -- pane     | right
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
        -- Tab 移动
        {
            key = "{",
            mods = "SHIFT|ALT",
            action = wezterm.action.MoveTabRelative(-1),
        },
        {
            key = "}",
            mods = "SHIFT|ALT",
            action = wezterm.action.MoveTabRelative(1),
        },
        -- 分屏跳转 (Alt+hjkl)
        {
            key = "h",
            mods = "ALT",
            action = wezterm.action.ActivatePaneDirection("Left"),
        },
        {
            key = "j",
            mods = "ALT",
            action = wezterm.action.ActivatePaneDirection("Down"),
        },
        {
            key = "k",
            mods = "ALT",
            action = wezterm.action.ActivatePaneDirection("Up"),
        },
        {
            key = "l",
            mods = "ALT",
            action = wezterm.action.ActivatePaneDirection("Right"),
        },
        -- 三等分布局 (Alt+Shift+T)
        {
            key = "t",
            mods = "ALT|SHIFT",
            action = wezterm.action.EmitEvent("split-vertical-thirds"),
        },
        -- 田字形四等分布局 (Alt+Shift+Q)
        {
            key = "q",
            mods = "ALT|SHIFT",
            action = wezterm.action.EmitEvent("split-quadrants"),
        },
    },
}