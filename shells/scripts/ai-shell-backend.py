#!/usr/bin/env python3
import sys, os, json, urllib.request, platform, unicodedata, shutil, re

def _config_path():
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(xdg, "ai-shell", "config.json")
    if os.path.exists(path):
        return path
    legacy = os.path.expanduser("~/.config/ai-shell/config.json")
    return legacy if os.path.exists(legacy) else path


def load_config():
    """优先级：环境变量 > 配置文件 > 内置默认值。

    环境变量代表"本次调用"的显式覆盖（临时换 base/model、CI 与测试都用它），
    配置文件代表长期偏好；早先的实现顺序颠倒，配置文件会把环境变量静默吃掉。
    """
    cfg = {
        "api_base": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "timeout": 20
    }

    config_file = _config_path()
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if v not in (None, "")})
        except Exception:
            pass

    for key, var in (
        ("api_base", "DEEPSEEK_API_BASE"),
        ("api_key", "DEEPSEEK_API_KEY"),
        ("model", "DEEPSEEK_MODEL"),
        ("timeout", "DEEPSEEK_TIMEOUT"),
    ):
        value = os.environ.get(var)
        if value:
            cfg[key] = value

    try:
        cfg["timeout"] = max(int(cfg["timeout"]), 1)
    except (TypeError, ValueError):
        cfg["timeout"] = 20

    return cfg


def call_llm(messages, config):
    url = f"{config['api_base'].rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}"
    }
    payload = json.dumps({
        "model": config["model"],
        "messages": messages,
        "temperature": 0.1
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=config["timeout"]) as resp:
        content_bytes = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip" or content_bytes[:2] == b"\x1f\x8b":
            import gzip
            content_bytes = gzip.decompress(content_bytes)
        data = json.loads(content_bytes.decode("utf-8", errors="replace"))
        return data["choices"][0]["message"]["content"].strip()

def detect_safe_context():
    """
    严格安全与隐私边界：
    1. 绝不读取任何文件内容（杜绝读取 .env、密钥、代码私有片段）
    2. 绝不泄露环境变量（杜绝提取环境变量中的 API Key/Token）
    3. 仅通过检测常见工程标记文件是否存在（os.path.isfile），识别项目语言与构建系统
    4. 仅获取脱敏工作目录名（basename），杜绝泄露完整机器路径

    返回 (目录名, 生态标记, 基建标记)。生态标记才允许影响命令推导；
    Dockerfile / compose / Makefile 这类是打包与任务编排文件，仓库"顺带提供"它们
    并不代表项目语言，混进生态会导致任何提问都被解释成 docker/make 需求。
    """
    cwd = os.getcwd()
    dirname = os.path.basename(cwd)

    ecosystem_markers = [
        ("Cargo.toml", "Rust (cargo)"),
        ("go.mod", "Go"),
        ("pnpm-lock.yaml", "Node.js (pnpm)"),
        ("yarn.lock", "Node.js (yarn)"),
        ("bun.lockb", "Node.js (bun)"),
        ("package.json", "Node.js (npm)"),
        ("pyproject.toml", "Python"),
        ("uv.lock", "Python (uv)"),
        ("requirements.txt", "Python (pip)"),
        ("setup.py", "Python"),
        ("CMakeLists.txt", "C/C++ (CMake)"),
        ("pom.xml", "Java (Maven)"),
        ("build.gradle", "Java/Kotlin (Gradle)")
    ]

    infra_markers = [
        ("Dockerfile", "Docker"),
        ("compose.yaml", "Docker Compose"),
        ("docker-compose.yml", "Docker Compose"),
        ("Makefile", "Makefile"),
        ("Justfile", "Just task runner"),
        ("justfile", "Just task runner")
    ]

    ecosystem, infra = [], []
    for filename, desc in ecosystem_markers:
        if os.path.isfile(filename):
            ecosystem.append(desc)
    # 仅在当前目录没有任何生态标记时，才向上探测一层父目录
    if not ecosystem:
        for filename, desc in ecosystem_markers:
            if os.path.isfile(os.path.join("..", filename)):
                ecosystem.append(f"{desc} (父目录)")
                break

    for filename, desc in infra_markers:
        if os.path.isfile(filename):
            infra.append(desc)

    return dirname, list(dict.fromkeys(ecosystem)), list(dict.fromkeys(infra))

def parse_candidates(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    candidates = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "cmd" in item:
                    candidates.append({
                        "cmd": str(item["cmd"]).strip(),
                        "desc": str(item.get("desc", "")).strip()
                    })
                elif isinstance(item, str):
                    candidates.append({"cmd": item.strip(), "desc": ""})
        elif isinstance(data, dict) and "cmd" in data:
            candidates.append({"cmd": str(data["cmd"]).strip(), "desc": str(data.get("desc", "")).strip()})
    except Exception:
        pass

    if not candidates:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for l in lines[:3]:
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", l)
            candidates.append({"cmd": cleaned, "desc": ""})

    return candidates[:3]

def sanitize_stderr(text):
    """
    轻量且精准的脱敏：仅针对明显的敏感凭证与用户路径，绝不过度脱敏影响报错分析
    """
    if not text:
        return ""
    # 清除 ANSI 颜色转义码
    clean = re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)
    # 脱敏真实高特征 API Key 与 Token (如 sk-xxx, ghp_xxx)
    clean = re.sub(r"sk-[a-zA-Z0-9_-]{20,}", "***API_KEY***", clean)
    clean = re.sub(r"gh[pousr]-[a-zA-Z0-9]{20,}", "***GITHUB_TOKEN***", clean)
    clean = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", "Bearer ***TOKEN***", clean, flags=re.IGNORECASE)
    # 脱敏 URL 中明文密码
    clean = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", clean)
    # 替换用户主目录为 ~
    home = os.path.expanduser("~")
    if home and len(home) > 3:
        clean = clean.replace(home, "~")
    lines = [l for l in clean.splitlines() if l.strip()]
    tail_lines = lines[-5:] if len(lines) > 5 else lines
    return "\n".join(tail_lines)[:512]

def char_width(ch):
    if unicodedata.category(ch) in ("Cc", "Cf", "Cs"):
        return 0
    w = unicodedata.east_asian_width(ch)
    if w in ("W", "F"):
        return 2
    cp = ord(ch)
    if (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF):
        return 2
    return 1

def str_display_width(s):
    clean = re.sub(r"\033\[[0-9;]*m", "", s)
    return sum(char_width(ch) for ch in clean)

def render_box(candidates, title="💡 推荐命令", out=sys.stderr):
    formatted_lines = []
    max_cmd_w = max(str_display_width(item["cmd"]) for item in candidates) if candidates else 0

    for i, item in enumerate(candidates):
        prefix = f"[{i+1}] " if len(candidates) > 1 else ""
        cmd_str = item["cmd"]
        desc_val = item.get("desc", "")

        cmd_w = str_display_width(cmd_str)
        space_padding = " " * max(max_cmd_w - cmd_w + 3, 2) if desc_val else ""
        desc_str = f"{space_padding}# {desc_val}" if desc_val else ""

        plain_line = f"{prefix}{cmd_str}{desc_str}"
        if desc_str:
            styled_line = f"\033[1;33m{prefix}\033[1;32m{cmd_str}\033[0m{space_padding}\033[36m{desc_str.lstrip()}\033[0m"
        else:
            styled_line = f"\033[1;33m{prefix}\033[1;32m{cmd_str}\033[0m"
        formatted_lines.append((plain_line, styled_line))

    max_content_w = max(str_display_width(p) for p, s in formatted_lines) if formatted_lines else 0
    title_w = str_display_width(title)

    try:
        term_cols = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        term_cols = 80

    min_w = max(max_content_w + 6, title_w + 8, 48)
    total_w = min(min_w, max(term_cols - 4, 30))

    top_dash_count = max(total_w - title_w - 5, 2)
    total_w = title_w + 5 + top_dash_count

    top = f"\n\033[36m┌─\033[0m \033[1;36m{title}\033[0m \033[36m" + ("─" * top_dash_count) + "┐\033[0m\n"
    out.write(top)

    for plain, styled in formatted_lines:
        pw = str_display_width(plain)
        padding = max(total_w - pw - 4, 0)
        out.write(f"\033[36m│\033[0m  {styled}" + (" " * padding) + "\033[36m│\033[0m\n")

    bottom = "\033[36m└" + ("─" * (total_w - 2)) + "┘\033[0m\n"
    out.write(bottom)
    out.flush()

def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(0)
    
    fix_mode = False
    failed_cmd = ""
    err_file = ""

    if "--fix" in args:
        fix_mode = True
        idx = args.index("--fix")
        if idx + 1 < len(args):
            failed_cmd = args[idx + 1]
    if "--err-file" in args:
        idx = args.index("--err-file")
        if idx + 1 < len(args):
            err_file = args[idx + 1]

    scope = "generic"
    if len(args) >= 2 and args[0] == "--scope":
        scope = args[1]
        query = " ".join(args[2:])
    else:
        query = " ".join(args)

    if not query.strip() and not fix_mode:
        sys.exit(0)

    config = load_config()

    try:
        tty_out = open("/dev/tty", "w", encoding="utf-8", errors="replace")
    except Exception:
        tty_out = sys.stderr

    try:
        tty_in = open("/dev/tty", "r", encoding="utf-8", errors="replace")
    except Exception:
        tty_in = sys.stdin

    if not config["api_key"]:
        tty_out.write(f"\033[31m❌ 未找到 DEEPSEEK_API_KEY，请在环境变量或 {_config_path()} 中配置。\033[0m\n")
        tty_out.flush()
        sys.exit(1)

    os_info = f"{platform.system()} ({platform.machine()})"
    shell_info = os.environ.get("SHELL", "zsh")
    dirname, project_hints, infra_hints = detect_safe_context()
    proj_tag = f" ({project_hints[0]})" if project_hints else ""
    eco_block = f"项目特征: {', '.join(project_hints)}" if project_hints else ""
    if infra_hints:
        eco_block = (eco_block + "\n" if eco_block else "") + (
            f"仓库还包含: {', '.join(infra_hints)}"
            "（打包/CI 类文件，不能据此判断项目语言或生态，仅在需求确实相关时参考）"
        )
    # 让模型知道这套 shell 自带的工具名，否则"ai shell 状态怎么查"会被猜到别的名字上
    eco_block += (
        "\n本机 shell 内置 ai-shell 命令：`ai-shell status` 查看当前会话状态，"
        "`ai-shell on` / `ai-shell off` 开关当前会话，"
        "`ai-shell persist on` / `ai-shell persist off` 控制是否跨会话自动开启。"
        "用户询问该工具本身时直接使用这些命令，不要臆造其他命令名。"
    )

    if fix_mode:
        err_text = ""
        if err_file and os.path.isfile(err_file):
            try:
                with open(err_file, "r", encoding="utf-8", errors="replace") as f:
                    err_text = f.read(2048)
            except Exception:
                pass
        sanitized_err = sanitize_stderr(err_text)
        if not sanitized_err.strip() and not failed_cmd:
            sys.exit(0)

        title = f"💡 自动反思与修复建议{proj_tag}"
        system_prompt = f"""你是一个高级终端 CLI 与命令排错修复专家。
当前环境: OS={os_info}, Shell={shell_info}, 项目={dirname}
{eco_block}

用户刚才执行的命令失败报错了：
命令: `{failed_cmd}`
错误信息:
<ERROR_LOG>
{sanitized_err}
</ERROR_LOG>

请根据上述具体错误原因进行深度反思，并推导出 1 到 2 条精准的修复命令（例如缺少 sudo 追加 sudo，路径或参数错误修正参数，缺少依赖包提示安装）。
必须输出一个纯 JSON 数组，数组项包含 "cmd" (纯命令，不含markdown反引号) 和 "desc" (10字以内简要原因与修复动作说明)。严禁输出任何 Markdown 格式或解释文字。"""
        query = f"请诊断并修复此报错: {failed_cmd}"
    elif scope and scope != "generic":
        title = f"💡 推荐 {scope} 命令{proj_tag}"
        system_prompt = f"""你是一个高级终端 CLI 与 {scope} 命令推导专家。
环境: OS={os_info}, Shell={shell_info}, 项目={dirname}
{eco_block}

用户明确指定使用工具 【{scope}】 来完成需求。
请将用户需求推导为 1 到 3 条以 `{scope}` 开头的标准、高质量命令。
必须输出一个纯 JSON 数组，数组项包含 "cmd" (纯命令，不含markdown反引号) 和 "desc" (5字以内简要区别说明)。严禁输出任何 Markdown 格式或解释文字。
示例:
[
  {{"cmd": "{scope} ...", "desc": "基础用法"}},
  {{"cmd": "{scope} ...", "desc": "组合统计"}}
]"""
    else:
        title = f"💡 推荐命令{proj_tag}"
        system_prompt = f"""你是一个高级终端 CLI 命令推导专家。
环境信息: OS={os_info}, Shell={shell_info}, 项目目录名={dirname}
{eco_block}

请根据用户的自然语言需求，推导出 1 到 3 条最精准实用的命令。
对于编译、构建、运行、测试等与项目生态相关的需求，优先匹配已检测到的项目生态（如 Rust 用 cargo，Go 用 go，Node.js 优先匹配包管理器）；与项目无关的需求（例如查询某个命令或工具自身的状态）不要硬套项目生态。
如果用户是在提问（含"能否/是否/怎么/为什么/有没有"等），优先给出能直接回答或验证该问题的一条命令，宁可只给 1 条，也不要用无关工具的命令凑数。
必须输出一个纯 JSON 数组，数组项包含 "cmd" (纯命令，不含markdown反引号) 和 "desc" (5字以内简要区别说明)。严禁输出任何 Markdown 格式或解释性废话。
示例（只演示输出格式，内容与用户需求无关，禁止照搬）:
[
  {{"cmd": "<命令1>", "desc": "<说明1>"}},
  {{"cmd": "<命令2>", "desc": "<说明2>"}}
]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    while True:
        try:
            tty_out.write("\033[33m⏳ 正在推导命令...\033[0m\r")
            tty_out.flush()
            
            raw_resp = call_llm(messages, config)
            tty_out.write("\033[2K\r")
            messages.append({"role": "assistant", "content": raw_resp})

            candidates = parse_candidates(raw_resp)
            if not candidates:
                tty_out.write("\033[31m❌ 未能推导出有效命令。\033[0m\n")
                sys.exit(1)

            render_box(candidates, title, out=tty_out)

            if len(candidates) > 1:
                select_prompt = (
                    f"\033[1;37m[\033[1;32m回车\033[1;37m: 执行[1] | "
                    f"\033[1;34me\033[1;37m: 编辑 | "
                    f"\033[1;33m{' / '.join(str(i+1) for i in range(1, len(candidates)))}\033[1;37m: 选候选 | "
                    f"\033[1;31mCtrl+C\033[1;37m: 取消]\033[0m \033[1;36m❯\033[0m "
                )
            else:
                select_prompt = (
                    "\033[1;37m[\033[1;32m回车\033[1;37m: 执行 | "
                    "\033[1;34me\033[1;37m: 编辑 | "
                    "\033[1;31mCtrl+C\033[1;37m: 取消]\033[0m \033[1;36m❯\033[0m "
                )

            tty_out.write(select_prompt)
            tty_out.flush()

            choice = tty_in.readline()
            if not choice:
                break
            choice = choice.strip()

            if choice == "" or choice.lower() in ("y", "yes", "1"):
                sys.stdout.write(candidates[0]["cmd"])
                sys.stdout.flush()
                sys.exit(0)
            elif choice.lower() == "e":
                sys.stdout.write(f"EDIT:{candidates[0]['cmd']}")
                sys.stdout.flush()
                sys.exit(0)
            elif choice in ("2", "3") and int(choice) <= len(candidates):
                sys.stdout.write(candidates[int(choice) - 1]["cmd"])
                sys.stdout.flush()
                sys.exit(0)
            elif choice.lower() in ("n", "no", "q", "quit"):
                tty_out.write("\033[33m⚡ 已取消。\033[0m\n")
                tty_out.flush()
                sys.exit(1)
            else:
                messages.append({"role": "user", "content": choice})
                if not title.endswith("(已微调)"):
                    title = f"{title} (已微调)"

        except KeyboardInterrupt:
            tty_out.write("\n\033[33m⚡ 已取消。\033[0m\n")
            sys.exit(1)
        except Exception as e:
            tty_out.write(f"\n\033[31m❌ 请求失败: {e}\033[0m\n")
            sys.exit(1)

if __name__ == "__main__":
    main()
