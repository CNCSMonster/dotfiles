# Zsh 插件版本更新 SOP

## 信任边界

启动仅校验并加载本地 checkout，不 clone、fetch、checkout、删除目录或执行 self-update/update。manager 固定为完整 commit；插件声明为完整 40 位 commit，tag 仅用于解释来源。缺失、HEAD 不符、tracked 文件变动或 origin 不符 时告警跳过；manager 不通过时跳过整个插件系统。已有用户 checkout 一律保留，由用户人工确认后处理。

manager 位于 `$ZSH_CONFIG_HOME/.zcomet`，插件位于 `${ZDOTDIR:-$HOME}/.zcomet/repos/<owner>/<repo>`。两者不是同一根目录。忽略自定义 zcomet repos-dir，配置仅向 manager 传已校验的本地绝对路径。

固定 manager [3dfe6f837479c6731e74400a233739500ec6d648](https://github.com/agkozak/zcomet/blob/3dfe6f837479c6731e74400a233739500ec6d648/zcomet.zsh) 的实现支持 @commit，但 _zcomet_clone_repo 对已有目录直接返回，不校验 HEAD，不能单靠 @SHA 保证实际加载版本。本项目在调用前校验。manager 通过普通 source 加载，不修改其函数和编译语义。上游可生成正常 .zwc 缓存，未跟踪缓存不作为版本漂移；不删除用户缓存。该检查信任本机既有缓存，不保证未跟踪 .zwc 的来源，若缓存来源不明应由用户人工备份核验，不能把 HEAD 校验等同于所有执行字节均来自该 commit。

## 人工更新流程

1. 先记录当前 HEAD、工作树状态和完整 pin；不要清理或覆盖已有用户目录。
2. 在登录交互 shell 使用只读 gh api 查询上游 tag 解析出的 commit（包括 annotated tag 的最终 commit），验证 SHA 严格为 40 位十六进制；不得输出 token。为避免启动旧配置的自动更新，审计时用 zsh -d -f -lic，继承已有认证环境但不读取用户 rc。若认证缺失，停止并由用户在现有终端查询，禁止 source 配置来取得凭据。

```bash
zsh -d -f -lic 'gh api repos/zsh-users/zsh-completions/commits/0.36.0 --jq .sha'
```

3. 审查 upstream diff、依赖、联网和 hook 行为；在用户确认后于新的隔离目录准备候选 checkout，显式 checkout --detach 到完整 SHA。不要对现有目录执行 reset --hard、clean 或自动更新。
4. 更新配置 pin 和本表；经用户确认迁移前，备份原目录及用户改动。缺失 checkout 也由用户在启动之外显式准备。
5. 自动验证只运行隔离 mock，不 source 真实用户交互配置：

```bash
bash scripts/test-zcomet-pins.sh
zsh -n shells/zsh/config.zsh
bash -n scripts/test-zcomet-pins.sh
git diff --check
```

6. 用户在确认 checkout 与缓存后自行开新终端检查补全功能。回滚时恢复已审查旧 pin 及其对应备份，不用 git checkout HEAD 覆盖尚未提交的用户配置。

## 固定清单与核验记录

2026-11-17：只读 gh api repos/<repo>/commits/<tag> 返回以下完整 SHA；本机已有 checkout HEAD 全部吻合。前会话九个 tag→SHA 均确实为 40 位，原值未改；smartcache 从短 SHA 补全。powerlevel10k 未在当前配置加载，不列入有效依赖。

| 仓库 | 来源 | 完整 commit |
|---|---|---|
| agkozak/zcomet | 既有 checkout / 上游 HEAD | 3dfe6f837479c6731e74400a233739500ec6d648 |
| zsh-users/zsh-completions | 0.36.0 | 28c5bdcaf81bb89e56d0df8267d822c3b8aed9e0 |
| nix-community/nix-zsh-completions | 0.5.1 | 6e782b97091b07eb849b58953eb200ccc56ef833 |
| tj/git-extras | 7.4.0 | 13cbdfc51e22e635939d07af86b33fca78c45411 |
| QuarticCat/zsh-smartcache | 54aba13 (既有commit补全) | 54aba13a6824e212992fd754c598c9e9acd259a3 |
| chisui/zsh-nix-shell | v0.8.0 | 8b86281cf9e9ef9f207433dd8b36d157dd48d50a |
| romkatv/zsh-no-ps2 | v1.0.0 | 4b23567dc503170672386660706e55ce0201770c |
| hlissner/zsh-autopair | v1.0 | 34a8bca0c18fcf3ab1561caef9790abffc1d3d49 |
| Aloxaf/fzf-tab | v1.3.0 | d7e0234614dbe5369fdd760907d12c0e05a4dccc |
| zsh-users/zsh-autosuggestions | v0.7.1 | e52ee8ca55bcc56a17c828767a3f98f22a68d4eb |
| zdharma-continuum/fast-syntax-highlighting | v1.56 | 5ecd353c81214f82bdeca5483fab6ccc5a2d5494 |

## 漂移排查

只读检查 git -C <目录> rev-parse HEAD、git -C <目录> status --porcelain；确认字节码与忽略文件来源，勿显示凭据文件或把全部 diff 原样输出。任何 Git 读取失败也拒绝加载。完整 commit 固定不能防御本机账户或 Git 配置已经被攻陷；这是可审计版本约束，不是沙箱。
