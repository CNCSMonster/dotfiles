# WezTerm 快捷键说明

## 全屏快捷键

**快捷键**: `Win+F` (Super+F)

- **功能**: 切换全屏模式
- **说明**: `Win+F` = **F**ull **S**creen，语义化命名，跨平台统一。
  - Windows: `Win` 键 + `F`
  - macOS: `Cmd` 键 + `F`
  - Linux: `Super/Win` 键 + `F`

## 终端搜索快捷键

**快捷键**: `Ctrl+Shift+X` (WezTerm 默认)

- **功能**: 打开 Copy Mode，进入搜索模式
- **说明**: WezTerm 内置的搜索功能，无需额外配置。
  - 进入 Copy Mode 后按 `/` 或 `Ctrl+S` 开始搜索
  - 按 `Enter` 跳转到下一个匹配项
  - 按 `Esc` 退出搜索模式

## 分屏快捷键

### 三等分窗口（上/中/下）

**重要说明**: WezTerm 的命令面板只会显示在 `keys` 表中绑定的 actions。如果不绑定任何快捷键，命令面板中将不会显示这些自定义命令。

**解决方案**: 需要绑定一个"虚拟"快捷键（如 F20），使命令面板可以显示这些命令，同时不会占用常用快捷键。

**使用方式**:
1. 按 `Ctrl+Shift+P` 打开命令面板
2. 搜索 `Thirds` 或 `Top/Middle/Bottom`
3. 选择 `SplitVerticallyIntoThirds(Top/Middle/Bottom)` 命令

### 四等分窗口（田字形）

**使用方式**:
1. 按 `Ctrl+Shift+P` 打开命令面板
2. 搜索 `Quadrants` 或 `TopLeft`
3. 选择 `SplitIntoQuadrants(TopLeft/TopRight/BottomLeft/BottomRight)` 命令

## 其他常用快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+P` | 打开命令面板 |
| `Ctrl+Shift+R` | 重新加载配置文件 |
| `Ctrl+Shift+X` | 打开 Copy Mode (搜索) - WezTerm 默认 |
| `Alt+h/j/k/l` | 切换到相邻的分屏区域 |

## 配置文件位置

配置文件位于：`~/.config/wezterm/wezterm.lua`

修改配置后按 `Ctrl+Shift+R` 即可重新加载，无需重启 WezTerm。
