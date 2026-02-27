# Verify setup.sh with Docker

Purpose: verify that `setup.sh` can run on a clean machine.

Run from repo root:

```bash
# 1) Build test image (this runs setup.sh inside Dockerfile)
./scripts/docker-build-test.sh

# 2) Verify installed environment inside the container
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

Pass condition:
- Image `dotfiles:test` is built successfully
- Verify script exits with code `0` and shows `失败: 0`
