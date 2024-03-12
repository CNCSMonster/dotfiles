# My Dotfiles 

This is a collection of my dotfiles. 
I use these to set up my development environment on a new machine, usually a Ubuntu machine 20.04 LTS / 22.04 LTS.
the deploy tool i used is called [xdotter](https://github.com/cncsmonster/xdotter)

## Installation

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
cargo install xdotter
# to see if the deploy will work
xdotter deploy --dry-run
# to deploy the dotfiles
xdotter deploy
```

## Structure of the Repository

- dotfiles-hub : contains submodules of the dotfiles from other developers, like TD-SKY,which is a collection of dotfiles from the developer TD-SKY,and this dotfiles use `dotter` as the deploy tool.


