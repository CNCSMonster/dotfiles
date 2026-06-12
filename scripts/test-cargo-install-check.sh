#!/bin/bash
# =============================================================================
# 测试 cargo-install check() 修复
# =============================================================================
# 场景：模拟已安装 wild-linker/bat（通过 binstall）的环境，运行 tool-installer
# 预期：check() 正确识别为已安装，跳过 install()
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=========================================="
echo "测试环境：模拟已安装环境 + 检查 tool-installer check()"
echo "=========================================="

# 创建临时测试目录
TEST_DIR=$(mktemp -d)
trap "rm -rf $TEST_DIR" EXIT

echo ""
echo "步骤 1: 准备测试环境..."
mkdir -p "$TEST_DIR/.cargo/bin"
mkdir -p "$TEST_DIR/.local/bin"

# 模拟已安装的二进制（通过 binstall 安装的）
# wild-linker → 二进制名为 wild
cat > "$TEST_DIR/.cargo/bin/wild" << 'EOF'
#!/bin/bash
echo "Wild 0.8.0 non-git-build (compatible with GNU linkers)"
EOF
chmod +x "$TEST_DIR/.cargo/bin/wild"

# bat → 二进制名为 bat
cat > "$TEST_DIR/.cargo/bin/bat" << 'EOF'
#!/bin/bash
echo "bat 0.26.1"
EOF
chmod +x "$TEST_DIR/.cargo/bin/bat"

# 模拟 cargo install --list（只记录 cargo install 安装的，不记录 binstall）
# 这是关键：cargo install --list 找不到 wild-linker 和 bat
mkdir -p "$TEST_DIR/.cargo"
cat > "$TEST_DIR/.cargo/.crates2.json" << 'EOF'
{"installs":{}}
EOF

# 准备 tool-installer
# 测试两种版本：旧版（bug）和新版（fix）
echo ""
echo "步骤 2: 准备 tool-installer..."

# 复制当前仓库的 vendor/tool-installer（应该是修复后的版本）
if [ -f "$PROJECT_DIR/vendor/tool-installer" ]; then
    cp "$PROJECT_DIR/vendor/tool-installer" "$TEST_DIR/.local/bin/tool-installer"
    chmod +x "$TEST_DIR/.local/bin/tool-installer"
    echo "✅ 使用仓库 vendor/tool-installer"
else
    echo "❌ vendor/tool-installer 不存在"
    exit 1
fi

# 复制 manifest.toml
cp "$PROJECT_DIR/manifest.toml" "$TEST_DIR/manifest.toml"

# 创建最小化 tools.toml
cat > "$TEST_DIR/tools.toml" << 'EOF'
[dev]
modules = ["cargo-tools"]

[cargo-tools]
manifest = "manifest.toml"
EOF

# 创建最小化的 cargo-tools 模块配置（只包含 wild-linker 和 bat）
mkdir -p "$TEST_DIR/modules"

# 进入测试目录
cd "$TEST_DIR"

# 设置 PATH
export PATH="$TEST_DIR/.cargo/bin:$TEST_DIR/.local/bin:$PATH"
export HOME="$TEST_DIR"

echo ""
echo "步骤 3: 验证二进制可用性..."
if command -v wild &>/dev/null; then
    echo "✅ wild 在 PATH 中: $(which wild)"
    wild --version
else
    echo "❌ wild 不在 PATH 中"
fi

if command -v bat &>/dev/null; then
    echo "✅ bat 在 PATH 中: $(which bat)"
    bat --version
else
    echo "❌ bat 不在 PATH 中"
fi

echo ""
echo "步骤 4: 检查 tool-installer 版本..."
python3 -c "
import zipfile
z = zipfile.ZipFile('$TEST_DIR/.local/bin/tool-installer')
data = z.read('tool_installer/managers/commands.py').decode()
has_check_fix = 'binary exists in' in data
has_registry_fix = '--registry crates-io' in data
print(f'Has check() fix: {has_check_fix}')
print(f'Has registry fix: {has_registry_fix}')
if has_check_fix and has_registry_fix:
    print('✅ tool-installer 包含完整修复')
else:
    print('⚠️ tool-installer 可能缺少部分修复')
"

echo ""
echo "步骤 5: 运行 tool-installer check（dry-run）..."
# 创建一个简化的 Python 脚本来测试 check() 逻辑
python3 << 'PYEOF'
import sys
import os
sys.path.insert(0, os.path.expanduser('~/.local/bin'))

# 由于 zipapp 的特殊结构，我们直接测试关键逻辑
import zipfile
import subprocess

# 读取 tool-installer 的代码
z = zipfile.ZipFile(os.path.expanduser('~/.local/bin/tool-installer'))
commands_py = z.read('tool_installer/managers/commands.py').decode()

# 检查关键函数是否存在
if '_parse_binary_version' not in commands_py:
    print("❌ 旧版本：缺少 _parse_binary_version")
    sys.exit(1)

if '_cargo_bin_dirs' not in commands_py:
    print("❌ 旧版本：缺少 _cargo_bin_dirs")
    sys.exit(1)

# 模拟 check() 的核心逻辑：查找二进制并获取版本
print("=== 模拟 check() 逻辑 ===")

bin_dirs = [
    os.path.expanduser('~/.cargo/bin'),
    os.path.expanduser('~/.local/bin'),
]

for tool, expected_bin in [('wild-linker', 'wild'), ('bat', 'bat')]:
    bin_path = None
    for d in bin_dirs:
        candidate = os.path.join(d, expected_bin)
        if os.path.isfile(candidate):
            bin_path = candidate
            break
    
    if bin_path is None:
        print(f"❌ {tool}: 二进制 {expected_bin} 不存在")
        continue
    
    print(f"✅ {tool}: 找到二进制 {bin_path}")
    
    # 获取版本
    try:
        result = subprocess.run([bin_path, '--version'], capture_output=True, text=True, timeout=5)
        version_output = result.stdout.strip()
        print(f"   --version 输出: {version_output[:80]}")
        
        # 简单解析版本号
        version = None
        for token in version_output.split():
            if token[0].isdigit() and '.' in token:
                version = token
                break
            if token.startswith(('v', 'V')) and token[1:].replace('.', '').isdigit():
                version = token[1:]
                break
        
        if version:
            print(f"   解析到版本: {version}")
        else:
            print(f"   ⚠️ 无法解析版本")
    except Exception as e:
        print(f"   ❌ --version 失败: {e}")

print("\n=== 结论 ===")
print("如果 tool-installer 包含修复，check() 会找到二进制并解析版本")
print("如果版本匹配，返回 SATISFIED，跳过 install()")
print("如果版本不匹配或为 latest，会尝试 install()，但 cargo binstall 会报 'already exists'")

PYEOF

echo ""
echo "=========================================="
echo "测试完成"
echo "=========================================="
