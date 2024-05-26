# My Dotfiles 

This is a collection of my dotfiles. 
I use these to set up my development environment on a new machine, usually a Ubuntu machine 20.04 LTS / 22.04 LTS.
using [xdotter](https://github.com/cncsmonster/xdotter) to deploy .

## Installation And Deployment

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
# install xdotter
cargo install xdotter && alias xd=xdotter
# to see if the deploy will work
xdotter deploy --dry-run
# to deploy the dotfiles
xdotter deploy
```

## Quick Start

you can experience my dotfiles by running the following command:

```bash
docker build -t dotfiles -f Dockerfile .
```
this Dockerfile use my dotfiles and use xdotter to deploy the dotfiles.
you can get the final image and run it to experience the final environment:
```
docker run -it dotfiles
```

## Inspired by 

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
- https://github.com/5eqn/nvim-config

