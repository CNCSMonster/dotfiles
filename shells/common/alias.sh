# 配置应用别名

##################################################

# 文件系统

alias l='eza -a --color=auto -s=type'
alias ll='eza -laHhg --color=always -s=type --time-style=long-iso'
alias dirs="eza -Fa1 --color=never -s=type | rg '/' -r ''"

##################################################

# 编译/解释

## 现代C++编译
alias mcpp='clang++ -std=c++2a -Wall -Werror'

alias py='python3'
alias rsi='rust-script'

##################################################

# 应用别名

alias trans="trans-go"
alias tsg="tree-sitter-grep"
alias tssa="tree-sitter-show-ast"

##################################################

# 终端显示

alias cls="clear"

##################################################
