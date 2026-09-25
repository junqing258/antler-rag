# Antler Knowledge

面向团队的轻量、自建 RAG 管理服务。它将管理界面、文档解析与向量检索部署在一个应用容器中，适合希望以较低运维成本管理内部知识库，并向 Agent 或其他程序提供检索 API 的场景。

## 功能

- 单一全局工作区：SQLite、Chroma 向量元数据、上传文件和 API 层共享同一知识资产空间。
- 管理控制台：用户、知识库、文档、API Key 和检索调试。
- 角色权限：管理员、编辑者、只读成员。
- 文档入库：支持 TXT、Markdown、PDF、DOCX；上传后同步提取文本、切块并写入嵌入式 Chroma。
- 数据接口：使用 API Key 进行文档管理、检索和可选的 RAG 问答。
- 同源部署：生产环境由 FastAPI 同时提供管理界面与 `/api/v1`，无需额外反向代理来处理 SPA 路由。

## 架构

```text
浏览器 / Agent
      │
      ▼
FastAPI（管理 UI + /api/v1）
      ├── SQLite：用户、权限、目录、审计
      ├── Chroma：文档 chunk 与向量
      └── /data/uploads：原始上传文件
```

项目是一个 Monorepo：`apps/frontend` 为 Vue 3 + Vite + Element Plus 管理端，`apps/backend` 为 Python 3.11+ / FastAPI 服务。

后端按职责分层，入口 `src/app.py` 只负责应用生命周期、中间件和路由装配：

```text
apps/backend/src/
├── core/            # 配置和应用级基础设施
├── db/              # SQLite 仓储与数据库迁移
├── models/          # Pydantic 请求/领域模型
├── rag/             # 向量、图谱和 Agentic RAG 实现
├── routers/         # 按 API 资源拆分的 FastAPI 路由
├── services/        # 可复用的业务服务（如 LLM 问答）
├── utils/           # 文档解析、日志与安全辅助函数
└── app.py           # 应用装配入口
```

为避免破坏已有脚本，`config.py` 和 `documents.py` 保留为向新模块转发的兼容入口；新代码应分别从 `core.config` 和 `utils.documents` 导入。

## 快速开始（Docker）

Docker Compose 是推荐的生产启动方式。

1. 创建本地环境文件：

   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，至少替换首次管理员密码：

   ```dotenv
   RAG_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
   RAG_BOOTSTRAP_ADMIN_PASSWORD=replace-with-a-long-unique-password
   ```

3. 构建并启动：

   ```bash
   docker compose up --build
   ```

4. 打开 `http://localhost:8000`，使用 bootstrap 账号登录，并由管理员创建首个知识库。

首次成功登录后，请从 `.env` 移除 `RAG_BOOTSTRAP_ADMIN_PASSWORD`（以及不再需要时的邮箱）。引导账户只会创建一次，但不应长期保留该明文密码。

服务就绪检查：

```bash
curl http://localhost:8000/health/ready
```

## 本地开发

需要 Node.js 22+、pnpm（项目固定使用 pnpm 10）以及 [uv](https://docs.astral.sh/uv/)。首次使用时安装前端依赖：

```bash
corepack enable
pnpm install --frozen-lockfile
```

复制并配置环境变量后，使用统一命令同时启动后端和前端：

```bash
cp .env.example .env
just dev
```

- 管理端：`http://localhost:5173`
- 后端：`http://localhost:8001`
- API 文档：`http://localhost:8001/docs`

Vite 会将 `/api` 请求代理到后端。也可以分别运行：

```bash
cd apps/backend && uv sync && uv run uvicorn app:app --reload --reload-dir src --port 8001
pnpm --dir apps/frontend dev
```

常用检查命令：

```bash
just test
just lint
just format
just build
just docker-build
```

## 配置

所有配置均使用 `RAG_` 前缀，可通过环境变量或根目录 `.env` 提供。`.env` 已被 Git 忽略；请以 [`.env.example`](.env.example) 为模板。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `RAG_BOOTSTRAP_ADMIN_EMAIL` | 无 | 首次初始化的管理员邮箱；必须与密码一同设置。 |
| `RAG_BOOTSTRAP_ADMIN_PASSWORD` | 无 | 首次初始化的管理员密码。 |
| `RAG_DATA_DIR` | `data` | SQLite、Chroma 与上传文件的根目录。生产容器中为 `/data`。 |
| `RAG_ENVIRONMENT` | `development` | 运行环境标识。 |
| `RAG_SESSION_HOURS` | `12` | 管理端会话有效期（1–168 小时）。 |
| `RAG_MAX_UPLOAD_BYTES` | `26214400` | 单个上传文件的最大字节数，默认 25 MiB。 |
| `RAG_LLM_BASE_URL` | 无 | 兼容 OpenAI 的服务地址；聊天与 embedding 共用。 |
| `RAG_LLM_API_KEY` | 无 | 上游服务的 API Key，仅在服务端使用。 |
| `RAG_CHAT_MODEL` | 无 | 用于 `/api/v1/chat` 的对话模型名。 |
| `RAG_EMBEDDING_MODEL` | 无 | 用于文档索引和检索的 embedding 模型名，例如 `text-embedding-v4`。未设置时保留 Chroma 内置 embedding。 |
| `RAG_EMBEDDING_DIMENSIONS` | 模型默认值 | 可选的 embedding 维数；使用 `text-embedding-v4` 时推荐固定为 `1024`。 |
| `RAG_RERANKER_BASE_URL` | 无 | 可选的 Hugging Face Text Embeddings Inference（TEI）CrossEncoder 服务地址；服务可加载 `BAAI/bge-reranker-large`。 |
| `RAG_RERANKER_API_KEY` | 无 | 可选的 TEI 服务 Bearer Token。 |
| `RAG_AGENTIC_ENABLED` | `false` | 是否启用受限 Agentic RAG 端点；默认关闭。 |
| `RAG_AGENT_MAX_STEPS` | `6` | 单次 Agent 请求最多执行的受控步骤数。 |
| `RAG_AGENT_MAX_SUBQUERIES` | `3` | 单次 Agent 请求最多使用的检索子查询数。 |
| `RAG_AGENT_MAX_LLM_CALLS` | `5` | 单次 Agent 请求允许的 LLM 调用上限。 |
| `RAG_AGENT_TIMEOUT_SECONDS` | `30` | Agent 调用上游模型的超时秒数。 |

未配置 `RAG_CHAT_MODEL` 时，`/api/v1/chat` 不会生成回答，但仍会返回召回的来源片段，方便 Agent 自行处理上下文。

配置外部 embedding 后，应用会使用一个由服务地址、模型和维数指纹命名的新 Chroma collection，避免新旧向量空间混用。存量文档需要显式重建索引：先备份完整数据目录，随后在维护窗口运行 `cd apps/backend && uv run python -m reindex_embeddings --confirm`。 

## 使用流程

1. 管理员登录后添加用户，并在“API Key”页面创建密钥。密钥明文只在创建时显示一次。
2. 管理员或编辑者创建知识库并上传文档。
4. 在“检索调试”中验证召回结果，或通过数据 API 接入 Agent。

角色能力概要：

| 身份 | 主要能力 |
| --- | --- |
| 管理员 | 管理用户、API Key、知识库和文档。 |
| 编辑者 | 管理知识库和文档，执行检索和问答。 |
| 只读成员 | 查看文档目录，执行检索和问答。 |
| API Key | 按 scope 调用数据 API，不能访问管理接口。 |

API Key 可授予的 scope 为 `retrieve`、`chat`、`agentic:query`、`documents:read`、`documents:write`、`documents:delete`。浏览器会话使用 `Authorization: Bearer <token>`；API Key 使用 `X-API-Key: <key>`。不需要 `X-Tenant-ID`。

## API

完整、可交互的请求模型以运行中服务的 OpenAPI 文档为准：生产环境为 `http://localhost:8000/docs`，开发环境为 `http://localhost:8001/docs`。

核心端点如下：

| 分类 | 端点 |
| --- | --- |
| 健康检查 | `GET /health/live`、`GET /health/ready` |
| 认证 | `POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、`POST /api/v1/auth/change-password` |
| 用户 | `/api/v1/users` |
| 知识库与文档 | `/api/v1/knowledge-bases`、`/api/v1/knowledge-bases/{knowledge_base_id}/documents` |
| 检索与问答 | `POST /api/v1/retrieve`、`POST /api/v1/chat`、`POST /api/v1/agentic-rag`（显式开启后） |

使用 API Key 检索的示例：

```bash
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: ark_your_key' \
  -d '{
    "knowledge_base_id": "your-knowledge-base-id",
    "query": "退款政策是什么？",
    "top_k": 5,
    "score_threshold": 0.65,
    "rerank": false
  }'
```

`score_threshold` 可选，取值为 `0` 到 `1`；它按照 `1 - cosine_distance` 过滤向量候选。`rerank` 默认关闭；启用前需配置 `RAG_RERANKER_BASE_URL`，指向提供 `POST /rerank` 的 Hugging Face Text Embeddings Inference（TEI）CrossEncoder 服务。启用后系统会先召回最多 `4 × top_k` 个候选、应用阈值、再由 CrossEncoder 重新排序，最后返回 `top_k` 条结果。

## 数据与运维边界

`/data` 中的 `app.sqlite3`、`chroma/` 与 `uploads/` 共同构成一个一致性单元。默认配置仅支持**单个应用容器和单个写入进程**；不要让多个副本共享同一个数据卷。

升级或备份前，先进入维护窗口或停止容器，然后完整复制 `/data`。只备份 SQLite、Chroma 或上传文件中的任意一项都无法恢复完整 RAG 状态。恢复时停止服务，整体替换 `/data`，再使用创建该备份的镜像版本启动。

从多租户旧版本升级前，先停止服务并备份完整数据目录，然后在备份副本上预演：

```bash
cd apps/backend
uv run python -m migrate_single_workspace --data-dir /data --dry-run
```

核对报告后，才在维护窗口中以 `--confirm` 执行迁移。该过程会撤销旧会话和 API Key、复制上传文件并重建 Chroma 索引。

更详细的操作说明见：

- [部署说明](docs/operations/deployment.md)
- [备份、恢复与升级](docs/operations/backup-and-upgrade.md)
- [Codex 设计 + Claude Code 审核工作流](docs/operations/multi-agent-workflow.md)

## 许可证

当前仓库尚未声明许可证；在对外发布或分发前请补充明确的 `LICENSE` 文件。
