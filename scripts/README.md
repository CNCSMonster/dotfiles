# Verify setup.sh with Docker

Purpose: verify that `setup.sh` can run on a clean machine.

Run from repo root:

```bash
# 1) Build test image (this runs setup.sh inside Dockerfile)
./scripts/docker-build-test.sh

# 2) Verify installed environment inside the container
# The build script prints this command after a successful build.
docker run --rm dotfiles:test /root/dotfiles/scripts/verify-docker-build.sh
```

No-cache rebuild:

```bash
./scripts/docker-build-test.sh --no-cache
```

若因网络波动导致构建偶发失败，可加重试次数（例如最多重试 3 次）：

```bash
./scripts/docker-build-test.sh --retry 3
```

## Offline safety regressions

Run these without installing project tools or modifying deployed configuration:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tool-installer/tests -t tool-installer
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s .tmp/supply-chain-watch -p test_audit.py
python3 -B scripts/test-check-tool-updates.py
python3 -B scripts/test-check-manifest-platforms.py
bash scripts/test-setup-xdotter.sh
bash scripts/test-setup-deploy-safety.sh
bash scripts/test-setup-summary.sh
bash scripts/test-zcomet-pins.sh
bash scripts/test-shell-regressions.sh
bash scripts/test-github-mirror-urls.sh
bash scripts/test-github-mirror-callers.sh
./scripts/check-tool-installer-sync.sh
./scripts/check-manifest-platforms.sh
```

The installer suite includes local, self-created npm/wheel fixtures. They use isolated temporary directories and offline caches, do not execute installed entry points, and explicitly skip when the required existing runtime is unavailable. Python wheel tests validate the uv installation component, not the complete Python manager.

For an explicitly declared locked tool, `python3 scripts/update-tool-locks.py --module <module> --tool <tool> --check` validates its existing lock without network access. `--generate` resolves registry metadata for every declared platform (npm `os`/`cpu` override, uv `--python-platform`), refuses to publish unless all three resolutions are identical, and records the verified platform list in `x-tool-lock-generator` / `# generator:`. Existing output additionally requires `--force`. Locks are stored once per tool under `locks/<ecosystem>/` and referenced by both OS tables in `manifest.toml`; do not copy them per platform or edit their provenance.

The platform guard accepts a universal lock only when its `platforms` list covers the target and npm `packages[]` carries that target's `os/cpu` artifacts. A legacy single-platform provenance is still accepted only on an exact OS/arch match. See the security practices document for the npm lifecycle-script, Python root-identity and pyright Node-runtime limits.

## Full Docker verification

Pass condition:
- Image `dotfiles:test` is built successfully
- Verify script exits with code `0` and shows `失败: 0`
