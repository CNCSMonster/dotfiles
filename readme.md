# My Dotfiles 

This is a collection of my dotfiles. 
I use these to set up my development environment on a new machine, usually a Ubuntu 22.04 LTS / 24.04 LTS.
Dotfiles are deployed by the built-in script in this repository.

## Quick Start (One Command Setup)

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
chmod +x ./setup.sh && ./setup.sh
```

This will automatically:
1. Deploy all dotfiles configurations
2. Install system dependencies
3. Install development tools (Neovim, LLVM, Rust, etc.)
4. Install runtime environments (Go, Node, Zig, etc.)

## Manual Deployment

If you prefer to deploy dotfiles manually:

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
# deploy dotfiles only
./scripts/xd --config ./xdotter.toml
```

## Quick Experience Using Docker
you can experience my dotfiles by running the following command:

### Recommended: Build with Automatic Resource Control
The build script automatically detects your system resources and sets optimal limits:

```bash
# Automatic resource-limited build (recommended)
./scripts/docker-build-test.sh

# Without cache
./scripts/docker-build-test.sh --no-cache

# Retry on network failure (e.g. up to 3 attempts)
./scripts/docker-build-test.sh --retry 3
```

The script will:
- Detect available memory and CPU cores
- Calculate resource limits dynamically (memory/cpu)
- Create a BuildKit builder with these limits
- Build the image without overwhelming your system

For minimal Docker-based `setup.sh` verification steps, see:
- [`scripts/README.md`](./scripts/README.md)

### Alternative: Basic Build (No Resource Limits)
```bash
# Warning: May consume all available resources
docker build -t dotfiles -f Dockerfile .
```

this Dockerfile uses this repository to validate the final environment setup flow.
you can get the final image and run it to experience the final environment:

```zsh
docker run -it dotfiles
```

## Inspired by 

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
- https://github.com/5eqn/nvim-config
- https://juejin.cn/post/7283030649610223668