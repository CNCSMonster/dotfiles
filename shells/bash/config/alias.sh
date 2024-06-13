##################################################

# 文件系统

alias ls='eza -a --color=auto -s=type'
alias ll='eza -laHhg --color=always -s=type --time-style=long-iso'
alias dirs="eza -Fa1 --color=never -s=type | rg '/' -r ''"

##################################################

# 编译/解释

## 现代C++编译
alias mcpp='clang++ -std=c++2a -Wall -Werror'

alias py='python3'
alias rsi='rust-script'

##################################################
