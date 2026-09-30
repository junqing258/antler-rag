# Agent Skill 接入 Antler RAG

适用于有 POSIX shell 与 Python 3.9+ 的 Claude Code 类 agent。Windows 使用 Git Bash。后端须已部署并可通过 HTTPS 访问；本机 `localhost` 测试可用 HTTP。

## 1. 申请并注入 API Key

管理员在「API Key 管理」创建个人 Key，至少勾选 `kb:read` 和 `retrieve`，按需增加 `agentic:query`（`ask`）、`graph:read`（`graph-search`）。只有需要额外读取文档元数据时才选 `documents:read`。设置过期时间并保存创建时唯一一次显示的完整 Key；吊销和换钥也在此页面进行。

在 agent 进程的受控环境中设置 `ANTLER_RAG_URL` 为服务根地址（无 `/api/v1` 路径），设置 `ANTLER_RAG_KEY` 为完整 Key。优先使用操作系统密钥管理器或受控运行环境注入。脚本只从环境变量读取 Key，经 `X-API-Key` 请求头发送，不输出也不自行落盘。若自行写在用户级 shell profile 或 Claude Code 配置中，Key 会以明文落盘，须限制文件权限；不要放入项目级配置或提交版本库。每人使用独立 Key，按需吊销。后台显示的 `last_used_at` 是最近使用时间，不是逐次审计日志。

## 2. 下载与安装

在管理界面的「API Key 管理」页面点击「下载 Skill ZIP」。下载包与当前服务版本一起发布，包含 `antler-rag/SKILL.md` 和 `antler-rag/scripts/rag.py`。将它解压到用户级 Skill 目录：

```bash
mkdir -p "$HOME/.claude/skills"
unzip antler-rag-skill.zip -d "$HOME/.claude/skills"
```

确认 `$HOME/.claude/skills/antler-rag/SKILL.md` 与 `$HOME/.claude/skills/antler-rag/scripts/rag.py` 存在；更新时先移走旧目录，再解压新包。Windows 在 Git Bash 中执行上述命令。安装后重启 Agent 会话，以便重新发现 Skill。

也可以直接从本仓库安装。以下命令在本仓库根目录执行，用户级软链和拷贝二选一：

```bash
# 用户级软链：仓库更新后立即生效
mkdir -p "$HOME/.claude/skills"
ln -s "$(pwd)/skills/antler-rag" "$HOME/.claude/skills/antler-rag"

# 或用户级拷贝
cp -r skills/antler-rag "$HOME/.claude/skills/"
```

项目级安装可在本仓库根目录开始执行：

```bash
ANTLER_SKILL_SOURCE="$(pwd)/skills/antler-rag"
cd /path/to/consumer-project
mkdir -p .claude/skills
ln -s "$ANTLER_SKILL_SOURCE" .claude/skills/antler-rag
# 或：cp -r "$ANTLER_SKILL_SOURCE" .claude/skills/
```

项目级调用脚本时使用该项目中 `scripts/rag.py` 的**绝对路径**，例如 `python3 "/path/to/consumer-project/.claude/skills/antler-rag/scripts/rag.py" list-kbs`；用户级调用使用 `"$HOME/.claude/skills/antler-rag/scripts/rag.py"`。脚本不依赖当前工作目录。

## 3. 验证调用

先确保 `ANTLER_RAG_URL` 和 `ANTLER_RAG_KEY` 已进入 Agent 进程环境；URL 应为管理界面的服务根地址，例如 `https://rag.example.com`，不能附加 `/api/v1`。运行以下命令验证连接：

```bash
python3 "$HOME/.claude/skills/antler-rag/scripts/rag.py" list-kbs
```

连接成功后，在 Agent 中提出“请检索内部知识库中的退款政策，并引用来源”之类的问题，Skill 会引导 Agent 列出知识库、检索并引用结果。

从 `items` 选取知识库 UUID。使用客户端**文件写入工具**将问题原文写入 `mktemp -d` 返回的私有目录中的 `query.txt`。例如，先在 shell 中创建目录：

```bash
mktemp -d
```

让文件写入工具写入该目录下的 `query.txt`，然后把下面命令中的 `KB_ID`、`QUERY_FILE` 替换为已校验的知识库 UUID、临时文件绝对路径。两者都需在本次 shell 调用中赋值，且不可从问题文本或检索结果中拼接。项目级安装时替换脚本为其绝对路径。

```bash
KB_ID='已校验的知识库UUID'
QUERY_FILE='私有临时目录/query.txt'
python3 "$HOME/.claude/skills/antler-rag/scripts/rag.py" retrieve --kb "$KB_ID" < "$QUERY_FILE"
```

如需综合问答或图谱查询，使用同一文件作为 stdin，分别运行 `ask`、`graph-search`。完成后删除该私有临时目录。不要把问题放进命令文本、heredoc 或命令参数；原文可包含 shell 元字符。`retrieve` 和 `ask` 的来源引用 `filename` 与 `chunk_index`；图谱结果引用三元组内容与 `document_id`，图谱响应不含 `filename`。返回 `[insufficient_scope]` 时联系管理员补 scope；`[feature_disabled]` 表示服务端未启用该能力，可根据已有检索证据作答。

CLI 完整选项见 `python3 .../scripts/rag.py --help` 与各子命令的 `--help`。查询文本只经 stdin 读取，成功时 stdout 为原 API JSON，失败时 stderr 为 `[code] message`，含服务端 `request_id` 时一并显示。
