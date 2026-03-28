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
2. Initialize git submodules (zcomet, etc.)
3. Install system dependencies
4. Install development tools (Neovim, LLVM, Rust, etc.)
5. Install runtime environments (Go, Node, Zig, etc.)

## Manual Deployment

If you prefer to deploy dotfiles manually:

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
chmod +x ./setup.sh && ./setup.sh  # This will download xdotter automatically
```

Or if you already have xdotter installed:

```bash
# Using xdotter from PATH
xd --config ./xdotter.toml

# Or using the downloaded version
~/.local/bin/xd --config ./xdotter.toml
```

**Tip**: On first zsh login, zcomet plugin manager installs automatically in background.
- **Default**: Non-blocking background installation, shell ready immediately
- **Wait for completion**: `ZCOMET_BG_INSTALL=0 zsh` (blocks for ~10-30 seconds)

## Quick Experience Using Docker

You can build the Docker image locally to experience my dotfiles:

```bash
# Build with automatic resource control (recommended)
./scripts/docker-build-test.sh

# Build without cache
./scripts/docker-build-test.sh --no-cache

# Retry on network failure (e.g. up to 3 attempts)
./scripts/docker-build-test.sh --retry 3
```

The build script will:
- Detect available memory and CPU cores
- Calculate resource limits dynamically
- Create a BuildKit builder with these limits
- Build the image without overwhelming your system

After building, run the container:

```bash
# Run the container
docker run -it dotfiles:test zsh
```

For more details, see [`scripts/README.md`](./scripts/README.md).

## Documentation

- [Rust 工具更新 SOP](./docs/rust-tools-update-sop.md) - 如何检查和更新通过 cargo binstall 安装的 Rust 工具

## Inspired by 

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
- https://github.com/5eqn/nvim-config
- https://juejin.cn/post/7283030649610223668