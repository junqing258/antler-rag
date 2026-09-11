# Antler RAG Admin：Monorepo 轻量自建 RAG 服务实施计划

> 状态：Draft
>
> 本文只定义方案、实施顺序和验收标准，不包含业务代码实现。

## 1. 背景与目标

在当前空仓库 `antler-rag-admin` 中建立一个可自建、低运维成本的 RAG 管理服务 Monorepo：

- `apps/frontend`：提供 RAG 管理界面，技术栈与工程习惯对齐 `/Users/junqing/git-hy/ses-flow/apps/frontend`。
- `apps/backend`：迁移 `/Users/junqing/git-hy/antler-rag` 现有 FastAPI 服务，并在迁移后演进为多租户后端。
- 生产环境默认只运行一个应用容器、挂载一个持久化数据卷，不依赖外部向量数据库、关系数据库或任务队列。
- 同时服务两类调用者：浏览器中的管理人员，以及携带租户 API Key 的 Agent/程序客户端。

### 1.1 成功标准

首个可发布版本应满足：

1. 管理员能登录，创建租户、用户、知识库和租户 API Key。
2. 租户成员能上传、查看、删除文档，并在检索调试页验证召回结果。
3. Agent 能通过稳定的 HTTP API 上传文档、检索上下文，并可选调用兼容 OpenAI 协议的 LLM 生成回答。
4. 任意普通用户或租户 API Key 都无法列出、检索、读取或删除其他租户的数据。
5. `docker compose up --build` 可启动完整系统；默认部署只需一个数据卷。
6. 原后端支持的 TXT、Markdown、PDF、DOCX、持久化 Chroma、检索和可选问答能力均有迁移回归测试。

## 2. 已确认的现状

### 2.1 目标仓库

`/Users/junqing/git-hy/antler-rag-admin` 当前为空，适合直接按 Monorepo 结构建立，不需要兼容已有目录或构建脚本。

### 2.2 前端参考工程

`ses-flow/apps/frontend` 当前主要约定如下：

- Vue 3.5 + TypeScript + Vite 8。
- Element Plus 作为主要组件库，Tailwind CSS 4 辅助布局和视觉样式。
- `vite-plugin-pages` 文件路由与 `vite-plugin-vue-layouts` 布局系统。
- Vue Router Hash History，适合静态文件随 FastAPI 一起发布。
- `vue-i18n`，已有中文、英文、日文、韩文的组织方式。
- 原生 `fetch` 的轻量请求封装，统一超时、`x-request-id` 和 `accept-language`。
- Composition API 模块化认证状态，没有引入 Pinia。
- Vitest、ESLint、Prettier、`vue-tsc`。

本项目复用上述技术选型、目录习惯和交互框架，不复制 SES Flow 的工作流、分拣等业务代码，也不无条件带入 Vue Flow、Monaco、Pixi.js、NATS 等无关依赖。

### 2.3 待迁移后端

`antler-rag` 当前是 Python 3.11–3.14、FastAPI、Chroma PersistentClient、LangChain Text Splitter 的单进程本地服务：

- `POST /v1/documents`：上传并同步解析、切块和索引。
- `GET /v1/documents`、`DELETE /v1/documents/{id}`：管理单一语料库。
- `POST /v1/retrieve`：向量检索。
- `POST /v1/chat`：可选调用 OpenAI-compatible `chat/completions`。
- `GET /health`：健康检查。
- 原文件保存在本地目录，向量索引保存在本地 Chroma。
- 仅支持一个全局 `RAG_API_KEY`，没有用户、租户、权限、知识库目录或关系型元数据。
- 当前自动化测试只覆盖文本提取的两个基础用例。

迁移不能只是复制目录；必须先锁定原行为，再把租户隔离贯穿 API、业务服务、SQLite、Chroma 和文件系统。

## 3. 范围

### 3.1 首版范围

- 本地账号登录、会话、退出和当前用户信息。
- 平台管理员、租户管理员、编辑者、只读成员四类角色。
- 租户、成员、知识库、文档、API Key 管理。
- TXT、Markdown、PDF、DOCX 上传、解析、切块和索引。
- 文档列表、状态、删除与失败原因展示。
- 基于知识库的向量检索调试。
- 可选的 LLM 问答调试和 Agent API。
- OpenAPI 文档、健康检查、审计事件、基础运行指标/日志上下文。
- 单容器生产镜像和根目录 Docker Compose。
- 数据备份、恢复和版本升级说明。

### 3.2 首版明确不做

- OCR、图片理解、网页抓取、Office 格式全集。
- 混合检索、rerank、复杂查询改写、Agent 编排。
- Redis/Celery 等独立任务系统；首版上传仍同步执行并设置明确大小/数量限制。
- 外部身份提供商、SSO、SCIM、计费、套餐、复杂配额。
- 多副本并行写入、跨机器高可用或云对象存储。
- 终端用户聊天产品；`chat` 只是 RAG 能力验证和 Agent 接口。

这些能力可在确认真实需求后增加，不提前进入核心架构。

## 4. 关键架构决策

### 4.1 Monorepo 与工具链

建议目录：

```text
antler-rag-admin/
├── apps/
│   ├── frontend/               # Vue 管理端
│   └── backend/                # FastAPI 服务及 Python 包（含提交到仓库的 uv.lock）
├── docs/
│   ├── plans/
│   └── operations/             # 部署、备份、恢复、升级
├── scripts/                    # 必要的开发/发布脚本，保持少量
├── .env.example
├── compose.yaml
├── Dockerfile                  # Node 构建前端 + Python 运行时的多阶段镜像
├── Justfile                    # 跨语言统一任务入口
├── package.json
└── pnpm-workspace.yaml
```

约定：

- 根目录使用 `pnpm` 管理 JavaScript workspace；首版只有 `apps/frontend` 一个 JS 包，也保留标准 workspace 结构。
- Python 项目保留在 `apps/backend/pyproject.toml`，不为了统一而把 Python 依赖塞入 Node 工具链。
- 根 `Justfile` 提供 `dev`、`test`、`lint`、`format`、`build`、`docker-build` 等统一命令。
- 开发时运行 Vite 与 Uvicorn 两个进程；Vite 将 `/api` 代理到后端。
- 生产镜像先构建前端，再将静态产物复制到 Python 镜像，由 FastAPI 同源提供管理界面和 API。
- 继续使用 Hash History，避免自建部署中的 SPA fallback 和反向代理额外配置。

### 4.2 保持轻量的持久化组合

首版使用：

| 数据类型 | 存储 | 说明 |
| --- | --- | --- |
| 租户、用户、成员关系、会话、API Key、知识库、文档目录、审计记录 | SQLite | 权限和资源状态的唯一事实来源 |
| 文档向量与 chunk 元数据 | 嵌入式 Chroma | 保留当前本地向量检索方式 |
| 原始上传文件 | 本地文件系统 | 放入租户/知识库命名空间目录 |
| 前端静态资源 | 应用镜像 | 不写入数据卷 |

统一挂载 `/data`：

```text
/data/
├── app.sqlite3
├── chroma/
└── tenants/
    └── {tenant_id}/
        └── knowledge-bases/
            └── {knowledge_base_id}/
                └── uploads/
```

SQLite 负责资源目录，避免从 Chroma 全量扫描来推导文档列表。默认单 Uvicorn worker、单容器写入；SQLite 启用 WAL、外键和合理 busy timeout。该约束应明确写入部署文档，而不是暗示支持多副本。

### 4.3 多租户资源模型

建议关系：

```text
User --< Membership >-- Tenant --< KnowledgeBase --< Document --< Chunk
                               ├--< TenantApiKey
                               └--< AuditEvent
```

核心实体：

- `tenants`：租户 ID、名称、状态、创建时间。
- `users`：全局登录身份、密码摘要、状态、`is_platform_admin`、`must_change_password` 和临时密码到期时间；同一用户可加入多个租户。`is_platform_admin` 是平台级授权，不放入任何租户 membership。
- `memberships`：用户在租户中的角色。
- `sessions`：只保存会话 token 摘要、到期时间和吊销状态。
- `tenant_api_keys`：只保存 Key 前缀和摘要，Key 明文只在创建时展示一次。
- `knowledge_bases`：属于租户，保存名称、描述及切块配置；每个新租户自动创建一个默认知识库。
- `documents`：属于租户和知识库，记录文件元数据、哈希、chunk 数、处理状态、错误信息、创建者。
- `audit_events`：记录安全相关写操作及操作者、租户、资源、请求 ID 和时间。

建议角色与最小权限：

| 角色 | 权限 |
| --- | --- |
| `platform_admin` | 管理所有租户及平台管理员；跨租户操作必须显式选择目标租户并记录审计 |
| `tenant_admin` | 管理本租户成员、API Key、知识库和文档 |
| `editor` | 管理本租户知识库/文档，执行检索和问答 |
| `viewer` | 只读查看文档目录，执行检索和问答 |
| `tenant_api_key`（凭证而非角色） | 默认只有 `retrieve`、`chat` 只读数据面能力；文档列表、上传和删除分别通过 `documents:read`、`documents:write`、`documents:delete` 显式授权，不暴露成员/Key/租户管理接口；权限范围持久化在 Key 记录上 |

平台管理员授权必须由现有平台管理员显式授予或撤销，并记录审计；系统必须拒绝撤销、停用或删除最后一个可用的平台管理员。首次 bootstrap 只负责建立第一个平台管理员，不创建隐式的“全租户 membership”。

### 4.3.1 成员创建流程

首版不接 SMTP/SSO，因此"邀请"落地为两种显式操作：

- tenant_admin 直接创建新用户：设置初始密码，用户首次登录强制改密后才能继续使用。初始密码默认 24 小时过期；过期后由 tenant_admin 重置，不通过日志或普通查询接口回显。
- tenant_admin 把已存在的全局用户加入本租户并指定角色。

`POST /api/v1/members` 的请求体据此区分"新建用户"与"关联已有用户"两种模式，不引入邮件邀请或待接受状态。

### 4.4 租户上下文与隔离规则

每个受保护请求都先解析 `TenantContext`，后续业务代码不得接收“可有可无”的租户过滤条件。

- 浏览器会话：Bearer session token 标识用户；`X-Tenant-ID` 指定当前租户，后端必须同时校验有效 membership 和 `tenant.status == active`。
- 租户 API Key：Key 自身唯一绑定租户，忽略客户端伪造的其他租户 ID；所属租户不是 `active` 时 Key 对所有数据面接口失效。
- 平台管理员：只有显式选择租户后才能访问租户资源，且写操作记审计。
- 停用租户后，普通 session 与租户 API Key 的所有租户级读写请求均被拒绝；平台管理员只能通过平台管理接口查看或重新启用该租户，不能绕过状态读取其知识库、文档或检索结果。
- `tenant_id` 不能从请求 body 直接写入模型，也不能依赖前端隐藏字段实现隔离。
- 数据访问层中的租户资源查询都要求 `tenant_id`；按裸 `document_id` 直接查询/删除应在代码审查和测试中禁止。

四层隔离：

1. SQLite：所有租户资源表都有 `tenant_id`，唯一索引包含租户维度。
2. Chroma：每个 chunk 强制写入 `tenant_id`、`knowledge_base_id`、`document_id`，所有查询、获取、删除使用组合过滤。
3. 文件系统：路径由后端使用受信任 ID 组装，客户端文件名只作为展示元数据，不参与目录解析。
4. API/服务层：统一依赖注入租户上下文和权限，不允许路由自行拼接过滤条件。

首版使用一个共享 Chroma collection，以元数据过滤隔离租户，避免每租户 collection 带来的生命周期和迁移复杂度。若未来出现强监管或独立备份需求，再评估每租户物理 collection/实例。

### 4.5 认证与 API Key 迁移

- Web 管理端使用可撤销的随机 Bearer session token；数据库只保存摘要。
- 密码使用成熟的自适应密码哈希实现，不自行设计算法。
- Agent 使用租户 API Key；Key 支持名称、创建者、最后使用时间、到期时间、吊销状态和必填权限范围。默认有效期为 90 天、权限为 `retrieve` 与 `chat`；永久 Key 和写入/删除权限必须在创建时显式选择。
- 当前全局 `RAG_API_KEY` 不应长期变成“可访问全部租户”的万能 Key。
- 若已有旧客户端，迁移期可通过显式开关将原 `RAG_API_KEY` 映射到预创建的 `default` 租户，并标记弃用；确认无旧客户端时直接关闭兼容层。
- 首次平台管理员通过一次性 bootstrap 命令或一次性环境变量创建。数据库记录 bootstrap 已完成状态；后续命令拒绝创建第二个初始管理员，正常重启不得重复创建或因残留环境变量而失败，并应告警提示部署者移除 bootstrap secret。

### 4.6 文档索引一致性

SQLite、文件系统、Chroma 之间没有分布式事务，因此文档使用明确状态机：

```text
pending -> indexing -> ready
                    -> failed
ready   -> deleting -> deleted
                    -> delete_failed
```

索引流程：

1. 校验权限、文件数量、大小、扩展名和知识库归属。
2. 先创建 `pending` 文档记录，再将文件写入隔离目录。
3. 提取文本并切块，写入含完整租户元数据的 Chroma。
4. 成功后写回 chunk 数并标记 `ready`；失败时记录可展示的安全错误，并清理不完整向量。
5. 只有 `ready` 文档参与检索。

删除流程先标记 `deleting`，再删除 Chroma chunks 和原文件，最后完成目录清理。提供内部 reconciliation 命令检查悬空文件、悬空向量和中间状态；不在首版引入常驻队列。

知识库删除使用独立状态机 `active -> deleting -> deleted/delete_failed`。进入 `deleting` 后立即阻断该知识库的新上传、检索和配置修改，并逐个调用幂等的文档删除流程；确认该租户/知识库组合下已无 Chroma chunks 和原始文件后，才完成 SQLite 目录清理。默认知识库不得删除。reconciliation 同时覆盖知识库中间状态，删除失败可安全重试，不能只依赖 SQLite 级联删除。

### 4.7 Embedding 与 LLM 配置

- 首版显式决策：继续使用 Chroma 内置默认 embedding function（ONNX all-MiniLM-L6-v2，首次运行需下载模型）。这是一项架构决策而非实现细节：原服务 `store.py` 通过 `collection.add(documents=...)` 隐式依赖该默认值，迁移时必须显式声明，否则基线回归无法判断检索质量是否漂移。
- Embedding 配置在首版是部署级配置，所有租户共享，避免同一 Chroma collection 中混合不可比较的向量空间。
- 记录 embedding provider、实现版本、模型标识、模型制品 SHA-256 和配置指纹；任一项变化必须触发显式全量重建，不允许静默切换。
- 默认模型在镜像构建阶段以最终非 root 运行用户预热到该用户镜像内的固定 home/cache 目录，并随镜像发布；运行时只读使用该缓存，不依赖首次启动联网，也不额外占用 `/data` 之外的持久卷。CI 必须在禁网条件下完成一次索引和检索 smoke。
- Python 依赖保留 `pyproject.toml` 的声明范围，同时提交 `apps/backend/uv.lock`；开发、CI 和生产镜像均使用 frozen lock 安装。Chroma 的精确版本和默认 ONNX 模型制品摘要属于发布清单的一部分。
- LLM provider 首版同样由部署者通过环境变量配置；管理端只能查看“已配置/未配置”和模型名，不回显密钥。
- 用户提交的 `system_prompt` 设置最大长度；服务端仍负责来源拼接和基础安全提示。
- 调用外部 LLM 时设置连接/读取超时、响应结构校验和无敏感信息的错误返回。

## 5. API 规划

正式 API 统一使用 `/api/v1`。FastAPI OpenAPI 是契约来源；前端按 feature 划分 API 模块。接口稳定后再决定是否引入 TypeScript 自动生成，首版不创建只服务一个前端的独立 client package。

### 5.1 系统与认证

```text
GET    /health/live
GET    /health/ready
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
GET    /api/v1/auth/me/tenants
POST   /api/v1/auth/change-password
```

使用初始密码登录时，响应和 `/auth/me` 返回 `must_change_password=true`；该会话除 `/auth/me`、`/auth/logout` 和 `/auth/change-password` 外不能访问其他接口。改密成功后吊销该用户的全部现有会话（包括当前会话），用户必须使用新密码重新登录。

### 5.2 平台与租户管理

```text
GET    /api/v1/tenants
POST   /api/v1/tenants
PATCH  /api/v1/tenants/{tenant_id}
GET    /api/v1/platform-admins
POST   /api/v1/platform-admins
DELETE /api/v1/platform-admins/{user_id}
GET    /api/v1/members
POST   /api/v1/members
PATCH  /api/v1/members/{membership_id}
DELETE /api/v1/members/{membership_id}
GET    /api/v1/api-keys
POST   /api/v1/api-keys
DELETE /api/v1/api-keys/{key_id}
```

`members/{membership_id}` 与 `api-keys/{key_id}` 是裸 ID 路由，但不豁免 §4.4 的规则：这两个路由的资源同样属于当前 `TenantContext`，数据访问层必须带 `tenant_id` 校验，越权访问统一返回 404。选择裸 ID 而非嵌套路径是因为 membership/key 的 ID 本身全局唯一，但隔离义务不变。

`platform-admins` 是平台级接口，不接收 `X-Tenant-ID`，仅允许平台管理员调用；授予、撤销和“最后一个可用平台管理员”保护均在事务内完成并记录审计。

### 5.3 知识库与文档

```text
GET    /api/v1/knowledge-bases
POST   /api/v1/knowledge-bases
GET    /api/v1/knowledge-bases/{id}
PATCH  /api/v1/knowledge-bases/{id}
DELETE /api/v1/knowledge-bases/{id}
GET    /api/v1/knowledge-bases/{id}/documents
POST   /api/v1/knowledge-bases/{id}/documents
GET    /api/v1/knowledge-bases/{id}/documents/{document_id}
DELETE /api/v1/knowledge-bases/{id}/documents/{document_id}
```

删除知识库遵循 §4.6 的知识库状态机并返回可查询的删除状态；默认知识库返回 409。处于 `deleting` 的知识库不参与列表之外的数据面操作，重复 DELETE 视为幂等请求。

### 5.4 检索与问答

```text
POST   /api/v1/retrieve
POST   /api/v1/chat
```

请求中的 `knowledge_base_id` 必须属于当前租户；可选 `document_ids` 也逐一校验归属。响应保留 `chunk_id`、`document_id`、`filename`、`content`、`distance`，并补充知识库 ID 和可用于前端展示的 chunk 序号。

### 5.5 原 `/v1` 接口兼容策略

实施前先确认是否已有外部调用者：

- 无调用者：直接切换到 `/api/v1`，不维护双路由。
- 有调用者：保留 `/v1/documents`、`/v1/retrieve`、`/v1/chat` 的薄适配层一个发布周期，只接受绑定默认租户的旧 API Key，并在响应头和日志中输出弃用提示。

兼容层不得绕过新认证、租户上下文和数据访问层。

### 5.6 通用响应约定

- 错误统一为稳定的 `code`、面向用户的 `message`、`request_id` 和可选字段错误列表。
- 分页参数统一为 `page`、`page_size`，响应包含 `items`、`total`、`page`、`page_size`。
- 写接口对越权资源统一返回 404，减少资源枚举风险；认证失败返回 401，已确认身份但权限不足返回 403。
- 请求日志包含 request ID、actor 类型、tenant ID、路由、耗时和状态码，不记录密码、token、API Key、文档正文或 LLM prompt。

## 6. 前端信息架构

管理端沿用参考项目的默认布局：可折叠侧边栏、顶部当前页面信息、用户菜单、语言切换和角色/权限驱动的菜单可见性。

### 6.1 页面

| 页面 | 主要能力 | 权限 |
| --- | --- | --- |
| 登录 | 本地账号登录、错误提示 | 公开 |
| 概览 | 知识库数、文档数、索引状态、服务配置摘要 | 全部成员 |
| 知识库列表 | 新建、搜索、进入详情、删除 | 查看为全员；写入为 admin/editor |
| 知识库详情 | 文档列表、上传、失败原因、删除、切块配置只读摘要 | 按角色 |
| 检索调试 | 选择知识库、问题、top_k、可选文档范围，展示命中 chunk 与 distance | 全部成员 |
| 问答调试 | 在已配置 LLM 时展示回答与引用来源 | 全部成员 |
| 成员管理 | 创建新用户（初始密码）、添加已有用户、修改角色、禁用或移除 | tenant_admin |
| API Key | 创建、一次性复制、查看前缀/权限/到期及最后使用时间、吊销 | tenant_admin |
| 租户管理 | 创建、停用、重新启用、选择目标租户、管理平台管理员 | platform_admin |
| 个人设置 | 当前账号、密码修改、当前租户切换 | 登录用户 |
| 系统信息 | 版本、embedding/LLM 配置状态、健康状态 | platform_admin |

### 6.2 前端模块建议

```text
src/
├── components/
├── composables/                # useAuth、useTenantContext 等
├── features/
│   ├── auth/
│   ├── tenants/
│   ├── knowledge-bases/
│   ├── documents/
│   ├── retrieval/
│   └── system/
├── i18n/
├── layouts/
├── lib/                        # request、api-response、toast
├── routes/                     # 文件路由页面
├── styles/
└── types/
```

实现约束：

- 认证和当前租户状态使用 Composition API 单例模块即可；只有状态复杂度明显上升时才引入 Pinia。
- 通用请求层自动附加 `Authorization`、`X-Tenant-ID`、`x-request-id`、`accept-language`，遇到 401 清理会话。
- 切换租户时清空所有租户级缓存并回到概览，避免旧租户数据残留在界面。
- 上传首版按文件展示进度/结果，但后端同步处理；前端限制并发，避免同时触发大量 embedding。
- 首版至少完整提供简体中文和英文；日文、韩文目录结构可以保留，但不要求首发完成翻译。
- 响应式目标以桌面管理端为主，保证平板可用，不投入独立移动端交互。

## 7. 后端模块建议

迁移后避免继续把模型、路由、存储和外部 LLM 调用全部放在 `app.py`：

```text
apps/backend/
├── src/antler_rag/
│   ├── app.py                  # 应用工厂与生命周期
│   ├── config.py
│   ├── api/                    # 路由和依赖注入
│   ├── auth/                   # 会话、密码、API Key、权限
│   ├── db/                     # SQLite 连接、schema/migrations、repositories
│   ├── domain/                 # 核心模型与错误
│   ├── services/               # 文档、检索、问答、租户服务
│   ├── rag/                    # parser、splitter、Chroma adapter
│   └── static/                 # 生产构建时复制前端 dist
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── pyproject.toml
└── uv.lock
```

保持依赖方向为 `api -> services -> repositories/adapters`。Chroma、SQLite、文件系统和 LLM 都通过边界清晰的 adapter 使用，重点是让租户隔离可集中测试；不要求建立重量级 DDD 框架。

数据库 schema 采用可追踪的版本迁移。首版可以选择轻量 SQL migration runner 或 Alembic，但不能依赖启动时散落的 `CREATE TABLE IF NOT EXISTS` 作为长期升级方案。

## 8. 分阶段实施计划

### Phase 0：基线锁定与关键决策确认

工作项：

- 为原 `antler-rag` 的五类接口补足黑盒回归测试或固定请求/响应样例，测试中显式固定 Chroma 精确版本、embedding provider/model 和模型制品 SHA-256（当前为 Chroma 内置 ONNX all-MiniLM-L6-v2）。
- 确认是否存在依赖旧 `/v1` 路由和全局 API Key 的客户端。
- 确认现有部署的 `/data`（Chroma + uploads）中是否有需要保留的存量数据；若有，产出数据迁移方案（见 Phase 3）。
- 确认首版采用内置账号，而不是接入现有 SSO。
- 确认“一租户多知识库 + 自动默认知识库”的模型。
- 明确单文件大小、单次文件数、允许 MIME、默认 `top_k`、会话有效期、临时密码有效期，以及 API Key 默认有效期和权限。

退出标准：原行为有可重复验证的基线；兼容策略和以上默认值被记录为 ADR 或更新到本文。

### Phase 1：Monorepo 骨架与原样迁移

工作项：

- 建立根 workspace、统一命令、环境变量示例和忽略规则。
- 将后端迁入 `apps/backend`，先保持现有行为和依赖声明范围；解析并提交 `uv.lock`，所有自动化和镜像构建使用 frozen lock。
- 创建最小 Vue 前端骨架，复用参考工程的 Vite、Element Plus、Tailwind、路由、布局、i18n、request、lint/test 方式。
- 建立 Vite `/api` 代理、FastAPI 静态资源服务和多阶段 Docker 构建。
- 新增 `/health/live`、`/health/ready`，区分进程存活与 SQLite/Chroma 可用。

退出标准：开发命令能同时启动前后端；生产镜像能展示占位管理页；原后端回归测试全部通过。

### Phase 2：SQLite 目录、认证与租户核心

工作项：

- 增加版本化数据库迁移与 SQLite 连接配置。
- 实现 tenant、user（含平台管理员标志和强制改密状态）、membership、session、tenant API Key 和 audit schema。
- 实现平台管理员 bootstrap、本地登录、注销、会话吊销与密码修改（含临时密码到期、首次登录接口限制和改密后吊销全部会话）。
- 实现 `TenantContext`、租户 active 状态检查、RBAC 依赖和统一错误模型。
- 实现租户、平台管理员、成员、API Key 管理 API；保护最后一个可用平台管理员，Key 的到期时间和 scopes 在认证时强制执行。
- 对 token/API Key 只保存摘要，并补充登录限速或基础失败退避。

退出标准：可以用两个租户、多个角色完成 API 级权限矩阵测试；伪造 `X-Tenant-ID` 无法进入非成员租户；停用租户后 session 与 Key 均不能访问数据面；首次改密和平台管理员保护规则通过测试。

### Phase 3：RAG 数据模型与隔离迁移

工作项：

- 增加 knowledge base、document 目录表和文档状态机。
- 把 parser、splitter、Chroma store、文件存储从原 `app.py` 拆到明确模块。
- 所有索引、列表、检索、删除操作接收强制 `TenantContext` 和 knowledge base ID。
- chunk metadata 写入完整租户维度，文件迁入租户目录。
- 实现文档与知识库的失败清理、删除状态和 reconciliation 命令；默认知识库不可删除，知识库批量清理可幂等重试。
- 若 Phase 0 确认存在存量数据：编写一次性迁移命令，将旧部署的 `/data` 归入预创建租户的默认知识库——为存量 chunk 元数据回填 `tenant_id`/`knowledge_base_id`，文件迁入租户目录，并在 SQLite 重建文档目录；迁移命令可重复执行且对已成功项幂等。
- 根据 Phase 0 结果实现或取消旧 API 兼容层。

退出标准：原 RAG 能力回归通过；跨租户泄漏测试覆盖 list/retrieve/chat/get/delete 和伪造资源 ID，并全部通过；知识库删除在每个中断点重启后均可恢复且不会遗留文件或向量。

### Phase 4：管理端业务页面

工作项：

- 完成登录、主布局、当前租户切换和权限菜单。
- 完成概览、知识库、文档上传/列表/删除/状态页面。
- 完成检索调试、问答调试和引用来源展示。
- 完成成员、API Key（含 scopes/到期时间的显式选择）、租户、平台管理员和个人设置页面。
- 为 API 模块、认证存储、权限显示、租户切换清理编写 Vitest。
- 补充核心浏览器流程：登录、切租户、上传、检索、删除、吊销 Key。

退出标准：四种角色看到并能执行的功能符合权限矩阵；刷新和切租户不会显示旧租户数据；关键流程有自动化验证和人工截图验收。

### Phase 5：打包、运维与发布门槛

工作项：

- 完成单镜像、Compose、非 root 用户、只读应用目录和 `/data` 数据卷；以最终运行用户将默认 ONNX 模型缓存固化到镜像。
- 完成生产环境变量校验；弱口令、默认 signing secret 或未初始化管理员时拒绝不安全启动。
- 编写备份/恢复文档：停止写入或进入维护模式后，一致性备份整个 `/data`。
- 编写 schema migration、Chroma/embedding 变化的升级与回滚说明。
- 配置结构化日志、请求 ID、审计查询和健康检查。
- 执行依赖漏洞、锁文件一致性、禁网索引/检索、镜像、上传边界、权限与恢复演练。

退出标准：全新部署、备份、恢复、升级演练通过；发布检查表全部完成；没有高危跨租户或密钥泄露问题。

## 9. 测试策略与上线门槛

### 9.1 后端

- 单元测试：文本提取、切块、密码/API Key 摘要、初始密码过期、Key scope/到期、权限判断、路径构造、错误映射。
- Repository 测试：每个按 ID 的读写都必须同时带 tenant ID；唯一约束不会跨租户误冲突。
- RAG 集成测试：使用临时 SQLite、临时文件目录和隔离 Chroma collection。
- API 合约测试：OpenAPI、状态码、分页、错误格式和旧接口兼容行为。
- 故障测试：空文档、不支持格式、超限文件、Chroma 写入失败、LLM 超时、文档/知识库删除中断、重启后 reconciliation。

### 9.2 必须单独维护的租户隔离测试矩阵

对租户 A 创建用户、Key、知识库、文档，对租户 B 重复操作，然后验证：

- A 的 session 与 API Key 都不能列出 B 的知识库或文档。
- A 用 B 的 knowledge base/document ID 发起 retrieve、chat、详情、删除均不能获得资源信息。
- A 在请求头伪造 B 的 tenant ID 会被拒绝。
- A 或 B 被停用后，其 session 与 API Key 均不能 list/retrieve/chat/get/delete/upload；重新启用前平台管理员也不能从数据面绕过状态。
- 同名文件、相同 SHA、相同知识库名称在两个租户间互不影响。
- 删除 A 的文档不会删除 B 的 Chroma chunks 或文件。
- 切换 embedding/重建索引时仍保留租户元数据。
- 平台管理员的跨租户写入包含明确目标租户和审计事件。
- 平台管理员授予/撤销有审计记录，最后一个可用平台管理员不能被撤销、停用或删除。

该矩阵是发布阻断项，不以“前端菜单不可见”替代后端验证。

### 9.3 前端与端到端

- Vitest：request headers、401 处理、角色菜单、表单校验、租户切换和 feature API 解析。
- 浏览器 smoke：登录 -> 创建/选择知识库 -> 上传 -> 检索 -> 删除 -> 退出。
- 管理 smoke：创建租户 -> 添加成员 -> 首次登录改密 -> 创建带到期时间/scopes 的 API Key -> 验证 scope -> 吊销 Key。
- 可访问性基础检查：键盘操作、表单 label、加载/空/错误状态、颜色对比。

### 9.4 根级 CI 顺序

1. 校验 `uv.lock` 与 `pyproject.toml` 一致，使用 frozen lock 执行后端 format/lint/type check（若引入）与单元测试。
2. 前端 format check、lint、`vue-tsc --noEmit`、Vitest、build。
3. API 集成与租户隔离矩阵。
4. 生产 Docker 镜像构建、容器健康 smoke，以及禁网条件下的索引/检索 smoke。

## 10. 安全与运维要求

- 默认只监听预期地址；未完成管理员初始化或关键 secret 不安全时给出明确告警/拒绝生产启动。
- 同源部署默认不开放宽泛 CORS；若单独部署前端，使用显式 allowlist。
- 上传采用后端生成的 UUID 文件名，防止路径穿越；限制压缩炸弹式输入和最大解析页数/文本量。
- API Key、session、密码、bootstrap secret、LLM 密钥不进入日志、错误响应或前端持久状态。
- 数据库和数据目录权限仅授予运行用户；容器以非 root 用户运行。
- 备份是整个 `/data` 的一致性快照；只备份 SQLite 或只备份 Chroma 都不能视为完整恢复点。
- 停用租户立即阻断普通 session 与租户 API Key 的全部租户级读写；平台管理员仅可通过平台管理接口重新启用。数据清理采用显式二次确认和可审计流程，不提供普通 API 的立即递归硬删除。
- 明确容量边界并监控磁盘空间；嵌入式方案接近容量或并发边界时再升级，而非首版提前引入分布式组件。

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| Chroma 元数据过滤遗漏 | 严重跨租户泄漏 | 强制 TenantContext、集中 store API、禁止裸 ID、隔离测试矩阵 |
| SQLite/Chroma/文件三者状态不一致 | 文档不可检索或无法清理 | 状态机、幂等清理、reconciliation、完整数据卷备份 |
| 同步 embedding 导致上传超时 | 管理体验差 | 限制大小/并发、逐文件反馈；达到真实阈值后再引入任务队列 |
| 默认 embedding 模型首次下载 | 离线部署启动/首请求失败 | 镜像构建阶段以最终运行用户预热并固化缓存，记录模型版本与制品摘要 |
| embedding 配置被静默修改 | 新旧向量不可比较 | 配置指纹、启动检查、显式 reindex 流程 |
| Python 浮动依赖或模型制品漂移 | 构建不可重复、检索基线变化 | 提交 uv.lock、frozen 安装、记录 Chroma 精确版本和模型 SHA-256 |
| 非 root 运行用户无法读取构建阶段模型缓存 | 离线环境无法索引或检索 | 以最终 UID 预热固定镜像内 cache，执行禁网容器 smoke |
| 长期高权限 API Key 泄露 | 租户数据被批量写入或删除 | 默认 90 天只读 scope，写入/删除和永久有效均需显式选择 |
| 从参考前端复制过多依赖 | 构建膨胀、维护成本增加 | 只复用基础栈与模式，按实际页面引入依赖 |
| 旧全局 API Key 变成平台万能凭证 | 安全边界失效 | 只允许映射默认租户的短期兼容，设开关和移除日期 |
| 单容器被误用于水平扩展 | 并发写损坏或锁竞争 | 部署文档明确单副本；扩展前迁移到服务化存储 |

## 12. 需要在 Phase 0 最终确认的事项

以下事项不阻塞建立骨架，但会影响接口或验收：

1. 是否已经有 Agent 或脚本调用原 `/v1` API；这决定是否需要兼容适配层。
2. 现有部署的 `/data` 中是否有需要保留的文档和向量；这决定 Phase 3 是否需要数据迁移命令及其验收方式。
3. 是否接受首版内置账号体系（含“管理员直接创建用户 + 首次登录强制改密”的成员流程）；若必须接现有 SSO，应在认证实现前替换方案。
4. 是否确认每租户支持多个知识库；本文默认“支持，并自动创建默认知识库”。
5. 目标部署是否保证单实例和本地持久卷；若首版就要求多副本，SQLite + 嵌入式 Chroma 不再合适。
6. 首发语言是否只要求简体中文/英文；本文默认这两种语言完整可用。
7. 是否确认首版继续使用 Chroma 内置默认 embedding（ONNX all-MiniLM-L6-v2）；若要换用外部 embedding 服务，应在数据模型定稿前替换 §4.7 的决策。

## 13. 建议的首版默认值

这些值应在 Phase 0 用真实文档验证后定稿：

- 单文件上限：25 MiB。
- 单请求最多：10 个文件；前端默认最多 2 个并发上传请求。
- chunk size：900，overlap：150，沿用原服务作为初始基线。
- `top_k`：默认 5，范围 1–20。
- Web session：默认 12 小时，可吊销。
- 临时初始密码：默认 24 小时过期，首次改密前只允许访问身份查询、改密和退出接口。
- 租户 API Key：默认 90 天过期，默认 scopes 为 `retrieve`、`chat`；`documents:read`、`documents:write`、`documents:delete` 和永久有效均需创建者显式选择，生产运维指南要求到期前轮换。
- 文档去重：同一知识库内按 SHA-256 拒绝重复，跨知识库或跨租户允许。
- 默认单副本、单 Uvicorn worker。

## 14. 完成定义（Definition of Done）

只有同时满足以下条件，才认为“Monorepo 自建轻量 RAG 服务”首版完成：

- 目录、统一命令、前后端开发流程和单镜像发布流程可重复执行。
- 原服务能力完成迁移，接口变化有明确兼容或升级说明。
- 管理端覆盖租户、成员、API Key、知识库、文档、检索和问答的首版范围。
- 所有租户资源的服务与存储调用都强制携带租户上下文。
- 跨租户隔离矩阵、关键端到端流程、容器 smoke、备份恢复演练全部通过。
- 安全配置、数据目录、单实例边界、依赖锁定、模型缓存、embedding 变更和升级流程有运维文档。
- 不包含首版范围外的外部服务和提前抽象，部署仍保持一个应用容器和一个数据卷。
