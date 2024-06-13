

# fnm 
eval "$(fnm env --use-on-cd)"
eval "$(fnm completions --shell $SH)"

# zoxide
eval "$(zoxide init $SH)"
eval "$(starship init $SH)"

# bob-nvim
eval "$(bob complete $SH)"
