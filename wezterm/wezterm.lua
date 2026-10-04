local wezterm = require("wezterm")
local act = wezterm.action

-- 上中下三等分布局 (Top/Middle/Bottom)
wezterm.on("Split Vertically (Top/Middle/Bottom)", function(window, pane)
    -- 先创建底部 2/3 区域，原 pane 自动成为顶部 1/3
    local remainder = pane:split({ direction = "Bottom", size = 0.667 })
    -- 再把底部 2/3 一分为二，得到中部和底部各 1/3
    remainder:split({ direction = "Top", size = 0.5 })
end)

-- 田字形四等分布局 (TopLeft/TopRight/BottomLeft/BottomRight)
wezterm.on("Split (TopLeft/TopRight/BottomLeft/BottomRight)", function(window, pane)
    local right = pane:split({ direction = "Right", size = 0.5 })
    pane:split({ direction = "Top", size = 0.5 })
    right:split({ direction = "Top", size = 0.5 })
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
        -- Ctrl+V：禁用 WezTerm 默认的 PasteFrom，让按键透传给应用
        -- 依据（wezterm show-keys 实测）：默认 CTRL+V -> PasteFrom(Clipboard) 会吞掉按键，
        --   pi/Qwen Code 收不到 → 图片粘贴静默失败。不禁用则无论绑不绑都无效。
        -- pi 侧配套：~/.pi/agent/keybindings.json 设
        --   "app.clipboard.pasteImage": ["ctrl+v", "alt+v"]
        -- 文本粘贴仍用 Ctrl+Shift+V；Vim/Neovim Visual Block 请改用 Ctrl+Q
        -- 文本粘贴：Ctrl+Shift+V 的默认会随 Ctrl+V 一并被消掉（实测无法用配置单独复原）
        --   → 终端里改用 Super+V 或 Shift+Insert；pi 内 Ctrl+V 自带【文字回退】也可粘文字
        { key = "V", mods = "CTRL", action = act.DisableDefaultAssignment },
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
