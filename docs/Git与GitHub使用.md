# Git 与 GitHub 使用说明

> 仓库地址：https://github.com/JNxX1/chenpi-orchard-system （Private，分支 `main`）
> 本文只讲这个项目里实际用得到的操作，照着复制命令即可。

## 1. 日常修改后怎么上传

改完代码，在项目根目录打开终端，三条命令：

```bash
git status                  # 看改了哪些文件（红色=没暂存，绿色=已暂存）
git add -A                  # 把所有改动加入暂存区
git commit -m "改了什么的说明"   # 提交到本地，例如：修复估产页除零错误
git push                    # 推送到 GitHub
```

提交说明写清楚"改了什么"，不要在一条提交里混进无关改动。

## 2. 常用查看命令

```bash
git log --oneline -10        # 最近 10 条提交
git diff                     # 还没暂存的改动内容
git diff --cached            # 已暂存待提交的内容
git status -s                # 精简状态
```

## 3. 哪些文件不会上传

`.gitignore` 已经排除，属于正常现象：

| 路径 | 原因 |
|---|---|
| `.venv/`、`__pycache__/` | 本机环境与缓存，换机器要重装 |
| `.env` | 含密钥与密码，绝不入库 |
| `instance/` | SQLite 数据库（含演示/真实业务数据） |
| `storage/` | 上传的原图、结果图、导出的报表 |
| `runs/` | 训练输出与权重 |
| `models/*.pt` | 模型权重（6MB 级二进制，换机器重新训练或单独拷贝） |
| `datasets/orange_orchard/images|labels` | 数据集图片与标签（约 380MB） |
| `tools/DBBrowser/` | 便携版数据库软件 |
| `.idea/`、`.vscode/` | 编辑器配置 |
| `CLAUDE.md`、`.claude/`、`tmp9/`、`*.docx`、`素材/首页图*`、`素材/场景图*` | 本地私有，写在 `.git/info/exclude`：既不进仓库，仓库里也看不到这些文件名 |

想确认某个文件是否被忽略：`git check-ignore -v 文件路径`。

## 4. 网络问题：推送报 Failed to connect to github.com:443

本机直连 GitHub 会被重置，需要走代理。本仓库已配置（只影响这个仓库）：

```bash
git config http.proxy http://127.0.0.1:7897
git config https.proxy http://127.0.0.1:7897
```

前提是 Clash Verge（`verge-mihomo`）正在运行，混合端口为 7897。换代理端口后用上面两条命令改掉即可；查看当前配置：

```bash
git config --local --get http.proxy
```

## 5. 认证说明

- 用的是 Git Credential Manager（GCM），凭据存在 Windows「凭据管理器」，Git 会自动带上，不需要每次输密码。
- 重新登录 / 换账号：`git credential-manager github login --browser`
- 查看已登录账号：`git credential-manager github list`
- **不要把 token 写进代码、`.env.example` 或提交历史里**。若误传：立刻在 GitHub → Settings → Developer settings 撤销该 token。

## 6. 常见报错

| 报错 | 原因与处理 |
|---|---|
| `Failed to connect to github.com:443` | 代理没开或端口变了，见第 4 节 |
| `Authentication failed` / `403` | 凭据失效，执行 `git credential-manager github login --browser` 重新授权 |
| `rejected ... non-fast-forward` | 远端有你本地没有的提交，先 `git pull --rebase` 再 `git push` |
| `file is 60.00 MB; this exceeds GitHub's file size limit` | 单文件超过 100MB 被拒绝（50MB 会警告），检查是不是把数据库/权重/数据集加进来了 |
| `LF will be replaced by CRLF` | Windows 换行符提示，只是警告，可以忽略 |

## 7. 仓库设置（在网页上操作）

- 改成公开 / 私有：仓库 → Settings → 最下方 Danger Zone → Change repository visibility。
- 添加协作者（队友、老师）：Settings → Collaborators → Add people。
- 改仓库名：Settings → Repository name，改完本地执行
  `git remote set-url origin https://github.com/JNxX1/新仓库名.git`。
- 想要在线预览网页效果：Settings → Pages（私有仓库需要 Pro 才能开 Pages；本项目是本地运行的 Flask，不需要 Pages）。

## 8. 建议的提交节奏

- 一个功能做完 → 一次提交（如"新增采收登记页面"）
- 修 bug → 单独一次提交，说明现象与原因
- 改文档 → 可以合并成一次提交
- 答辩前打标签：`git tag v1.0 && git push --tags`，方便回溯"答辩版本"
