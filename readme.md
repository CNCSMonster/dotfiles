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

### Used in Local Machine

```bash
git clone https://github.com/cncsmonster/dotfiles
cd dotfiles
# install xdotter
cargo install xdotter
# deploy the dotfiles in interactive mode,which is suggested
xdotter deploy -i
# or you can deploy the dotfiles just force
# xdotter deploy -q
```

### Quick Experience Using Docker
you can experience my dotfiles by running the following command:

```bash
# try to make sure there is no image has the same name
docker rmi dotfiles
# build the image
docker build -t dotfiles -f Dockerfile .
```
this Dockerfile use my dotfiles and use xdotter to deploy the dotfiles.
you can get the final image and run it to experience the final environment:

```zsh
docker run -it dotfiles
```

## Inspired by 

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
- https://github.com/5eqn/nvim-config
- https://juejin.cn/post/7283030649610223668