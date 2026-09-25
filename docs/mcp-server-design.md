# 后端 MCP Server 接入方案

> 状态：**缓行存档**——设计完整、决策已全部关闭，暂不实施。当前执行方案为 Skill 优先，见 `agent-access-design.md`；满足其 §8 重启条件时按本文档 §9 分阶段计划实施（其中 `kb:read` 改造已由 Skill 阶段 Phase S1 提前完成）。
> 目标：将 antler-rag 后端现有 RAG 能力（检索、Agentic RAG、知识库列表、图谱搜索）以 MCP tools 形式通过 Streamable HTTP 暴露，使 Claude Code、Cursor、Claude Desktop 等外部 MCP 客户端能够以受控、可审计的方式调用知识库。

## 1. 范围与原则

本期能力：

- 后端作为 **MCP Server**（资源方），挂载在现有 FastAPI 应用内，单进程单端口（8000）对外服务；
- 暴露 4 个只读 tools：`retrieve`、`agentic_rag`、`list_knowledge_bases`、`graph_search`；
- 鉴权**复用现有 API Key + scope 体系**（API Key 作为 Bearer Token），不引入新凭据体系；
- tools 实现**复用现有服务层**（RetrievalService / AgentService / GraphStore / Database），零业务逻辑复制；
- 功能开关 `RAG_MCP_ENABLED`，默认关闭（与 `agentic_enabled` / `graph_enabled` 一致）；
- 每次 tool 调用写审计（actor_type=api_key），日志不落原始 token。

非目标：

- **不做 MCP Client/Host**：AgentService 仍使用固定 vector_search 工具，不消费外部 MCP Server（如需要另行立项）；
- **不暴露 chat tool**：MCP 客户端自身就是 agent，通常拿 `retrieve` 结果自行合成答案；后续有需要可低成本补充；
- **不实现完整 OAuth 2.1 授权服务器**：无登录页、无 consent 流程，采用静态 API Key Bearer token（见 §5.4 tradeoff）；
- 不提供 stdio 传输、MCP resources/prompts；
- 不暴露任何写操作（文档上传、删除、图谱重建等）。

安全原则（继承 `rag/agentic.py` 现有约定）：文档与模型输出是数据不是指令；预算（top_k、超时）永远来自服务端设置。

## 2. 技术选型

### 2.1 SDK：官方 mcp Python SDK v2

依赖：`mcp>=2,<3`（Python ≥3.10，实现 MCP 2026-07-28 规范；项目现要求 Python ≥3.11，满足）。

- 高级 API 为 `mcp.server.MCPServer`（v1 中名为 `FastMCP`；若因生态兼容必须停留 v1，则锁 `mcp>=1.28,<2`，本方案代码按 v2 书写）；
- `@mcp.tool()` 从类型注解 + docstring 自动生成 JSON Schema，无需手写；
- `mcp.streamable_http_app()` 返回标准 Starlette ASGI 应用，可直接挂载进 FastAPI；
- 自带 Bearer 鉴权中间件（`TokenVerifier` 协议），正好包装现有 API Key 存储。

不引入 `fastapi-mcp` 等第三方封装，减少一层依赖。

### 2.2 部署形态对比

| 形态 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **挂载进现有 FastAPI 应用** | 单进程单端口；直接复用 lifespan 中创建的服务单例（SQLite/Chroma/服务对象）；复用现有请求日志、审计、部署与备份流程 | 与主应用同生命周期 | **推荐** |
| 独立 stdio 进程 | 客户端本地拉起、无网络暴露 | 每个客户端各自起进程；无法复用进程内 Chroma/SQLite 单例；多客户端无法共享；鉴权退化为文件权限 | 否 |
| 独立 HTTP 服务 | 与主应用隔离部署 | 跨进程访问 SQLite（WAL 单写者）与 Chroma PersistentClient 引入锁冲突；多一个部署单元 | 否 |

### 2.3 挂载的两个关键机制（v2 官方文档 run/asgi）

1. **lifespan 接管**：被 mount 的子应用 lifespan 永远不会执行。宿主 FastAPI 的 lifespan 必须进入 `mcp.session_manager.run()`，否则首个请求即报 `RuntimeError: Task group is not initialized`。且 `session_manager` 属性只在调用过 `streamable_http_app()` 之后才存在。
2. **DNS rebinding 防护**：`streamable_http_app()` 默认只接受 localhost Host 头；部署到真实域名后**所有请求返回 421**，必须显式传 `TransportSecuritySettings(allowed_hosts=[...])`。

会话为进程内有状态（Streamable HTTP session manager）。当前部署为 uvicorn `--workers 1`（见 Dockerfile），不受影响；未来扩 worker 需 sticky session 或评估无状态模式（见 §10）。

## 3. 架构与模块设计

```text
MCP 客户端 (Claude Code / Cursor / Claude Desktop / Inspector)
        |  Streamable HTTP  ·  Authorization: Bearer <API Key>
        v
FastAPI app (现有, :8000)
  ├── /api/v1/...     现有 REST 路由（不动）
  ├── /mcp            新增：Mount(mcp.streamable_http_app())
  │     ├── auth 中间件: ApiKeyTokenVerifier ──> api_keys 表（复用 key_by_hash）
  │     └── tools: retrieve / agentic_rag / list_knowledge_bases / graph_search
  │              │
  │              v  ServiceContainer（宿主 lifespan 内填充）
  │        RetrievalService · AgentService · GraphStore · Database（均为现有对象）
  └── /               StaticFiles 前端（保持最后挂载）
```

### 3.1 模块布局

```text
src/mcp_server/
├── __init__.py   # create_mcp_server(settings, database) -> tuple[MCPServer, ServiceContainer]
├── auth.py       # ApiKeyTokenVerifier：API Key -> AccessToken
└── tools.py      # register_tools(mcp, container, settings)：4 个 tool + scope/开关检查
```

注意：目录**不能**命名为 `src/mcp/` —— pytest `pythonpath=["src"]` 会使本地包遮蔽 SDK 的 `mcp` 包。

### 3.2 服务获取方式

tools 运行在被挂载的子应用中，**拿不到 FastAPI 的 `app.state`**。引入极简 `ServiceContainer`（dataclass，字段：`retrieval` / `agentic` / `graph_store` / `database`），由宿主 lifespan 在创建完现有服务对象后填充；tool 执行时容器未就绪则 fail fast。不引入 DI 框架。

### 3.3 app.py 集成示意

```python
# create_app() 内，settings 就绪后：
mcp_server, container = create_mcp_server(settings, ...)   # mcp_enabled=false 时返回 (None, None)
mcp_asgi = mcp_server.streamable_http_app(
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts),
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ...  # 现有 Database / RAGStore / 各 Service 创建逻辑不变
    container.populate(app.state)                          # 填充 ServiceContainer
    async with contextlib.AsyncExitStack() as stack:
        if mcp_server is not None:
            await stack.enter_async_context(mcp_server.session_manager.run())
        yield
    ...

app.mount("/mcp", mcp_asgi)          # 必须在 StaticFiles("/") 之前挂载
```

## 4. Tool 定义

| tool | 参数 | 所需 scope | 功能开关 | 对应 REST |
|---|---|---|---|---|
| `retrieve` | `knowledge_base_id`, `query`, `top_k=5 (1..20)`, `document_ids?`, `score_threshold?`, `rerank=False` | `retrieve` | — | `POST /api/v1/retrieve` |
| `agentic_rag` | `knowledge_base_id`, `message`, `top_k=5 (1..20)` | `agentic:query` | `agentic_enabled` | `POST /api/v1/agentic-rag` |
| `list_knowledge_bases` | 无 | `kb:read`（**新增**，见下文） | — | `GET /api/v1/knowledge-bases` |
| `graph_search` | `knowledge_base_id`, `query`, `top_k=5 (1..20)` | `graph:read` | `graph_enabled` | `POST /api/v1/graph/search` |

设计要点：

- **参数校验复用 `models/schemas.py` 现有 Pydantic 模型**（`RetrieveRequest` / `AgenticRagRequest` / `GraphSearchRequest`），保证与 REST 行为、限制（top_k ≤ 20、query ≤ 10k 字符）完全一致；
- **返回结构与 REST 对齐**（JSON 序列化后作为 tool 文本返回）：
  - `retrieve` / `graph_search` → `{"results": [chunk_payload...]}`；
  - `agentic_rag` → `{"answer", "sources", "retrieval_mode", "detail"?}`；
  - `list_knowledge_bases` → `{"items": [...]}`（仅 id/name/description 等元数据）；
- `agentic_rag` 不暴露 `mode`（服务端已收敛为 vector，AgentService 内部忽略该参数）与 `include_trace`（trace 服务于前端调试视图，避免消耗客户端 token）；
- **错误映射**：`APIError` → MCP tool 调用返回 `isError`，文本格式 `[code] message`（如 `[not_found] Knowledge base was not found`、`[feature_disabled] ...`、`[insufficient_scope] ...`），与 REST 错误码语义一一对应；
- KB / 文档存在性校验直接复用 `routers/retrieval.validate_retrieve`（其本身是纯函数，可脱离 FastAPI Depends 调用）；
- LLM 未配置时 `agentic_rag` 沿用现有语义：`answer=null` + `detail` 提示，sources 照常返回。

### list_knowledge_bases 与 `kb:read` scope（已决策）

现状：`GET /api/v1/knowledge-bases` **明确禁止 API Key 枚举**（router 内 403 特判），而 MCP 客户端需要发现知识库才能选择 `knowledge_base_id`。

**已确认采用**：新增 `kb:read` scope，受控放开枚举——

- `utils/security.SCOPES` 增加 `"kb:read"`；
- HTTP 路由改为 `access("kb:read", ROLES)`，删除 API Key 403 特判（持有 `kb:read` 的 Key 亦可枚举，属受控放开）；
- 前端 `ApiKeysPage.vue` 增加 `kb:read` 复选框，**同时补齐缺失的 `graph:read`**（现存 gap：后端 SCOPES 已有 `graph:read`，但前端无法签发，`graph_search` tool 依赖它）。

备选（已否决）：不提供列表 tool，要求客户端配置时显式写死 `knowledge_base_id`。

## 5. 认证与授权

### 5.1 方案：API Key 即 Bearer Token

SDK v2 的鉴权模型是 OAuth 2.1 资源服务器：实现 `TokenVerifier` 协议（一个异步方法，token 进、`AccessToken | None` 出），SDK 中间件负责 401 拦截与 per-request 上下文注入。

```python
# src/mcp_server/auth.py
class ApiKeyTokenVerifier(TokenVerifier):
    def __init__(self, database: Database):
        self.database = database

    async def verify_token(self, token: str) -> AccessToken | None:
        key = self.database.key_by_hash(token_digest(token))  # SQL 已过滤 revoked/expired
        if not key:
            return None
        self.database.touch_key(key["id"])                    # 复用 last_used_at 更新
        return AccessToken(
            token=token,
            client_id=key["id"],
            scopes=json.loads(key["scopes_json"]),
            subject=key["created_by"],
        )
```

MCPServer 构造（`token_verifier` 与 `auth` 必须成对传入，否则 SDK 抛 ValueError）：

```python
mcp = MCPServer(
    "antler-rag",
    token_verifier=ApiKeyTokenVerifier(database),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(settings.mcp_public_url),
        resource_server_url=AnyHttpUrl(f"{settings.mcp_public_url}/mcp"),
        required_scopes=[],               # scope 差异在 tool 内逐个检查
        validate_token_resource=False,    # API Key 无 OAuth audience 绑定
    ),
)
```

要点：

- **对外名称定为 `antler-rag`**（与仓库名一致）。该名字出现在 initialize 握手的 `serverInfo.name`、客户端服务器列表与日志中，且 Claude Code 等客户端会以其为工具命名空间（`mcp__antler-rag__retrieve`）。`MCPServer(name)`、客户端配置的 server 名（§5.3 示例）与接入文档三处必须统一使用此名；名字保持稳定，不含环境/版本后缀（环境靠 URL 区分），日后改名会牵连所有客户端配置与文档；
- **完全复用现有 API Key 基建**：签发/吊销/过期/前缀展示（管理端已具备），`key_by_hash` 自带 revoked/expired 过滤，无新增凭据表；
- 只接受 API Key，**不接受用户 session token**——MCP 属机器对机器集成，API Key 具备独立过期、吊销与审计能力；
- SDK 自动提供 RFC 9728 保护资源元数据（`/.well-known/oauth-protected-resource/mcp`）与标准 401 + `WWW-Authenticate` 响应。

### 5.2 tool 内授权

```python
@mcp.tool()
async def retrieve(knowledge_base_id: str, query: str, top_k: int = 5, ...) -> str:
    """在指定知识库中做向量检索，返回带分数与出处的原文片段。"""
    token = get_access_token()                     # SDK auth 中间件注入
    if token is None or "retrieve" not in token.scopes:
        raise ToolError("[insufficient_scope] ...")
    ...
```

每个 tool 统一执行四步：scope 检查 → 功能开关检查（agentic/graph）→ 存在性校验（validate_retrieve）→ 审计记录（复用 `db.audit`，action 如 `mcp_retrieve`，actor 取自 AccessToken）。

### 5.3 客户端接入示例

Claude Code：

```bash
claude mcp add --transport http antler-rag https://rag.example.com/mcp \
  --header "Authorization: Bearer <API_KEY>"
```

Cursor / Claude Desktop（mcpServers JSON）：

```json
{
  "mcpServers": {
    "antler-rag": {
      "url": "https://rag.example.com/mcp",
      "headers": { "Authorization": "Bearer <API_KEY>" }
    }
  }
}
```

### 5.4 Tradeoff 说明

- 静态 API Key Bearer 而非完整 OAuth 2.1：MCP 规范推荐 OAuth，但本项目为单工作区内部服务，已有成熟的 API Key 体系；主流客户端（Claude Code / Cursor / Desktop）均支持自定义 Authorization 头，静态 token 即可工作。`AuthSettings.issuer_url` 指向自身仅为满足 SDK 构造要求与 401 发现流程，不会真正对外提供 token 签发。若未来对接企业 IdP，可平滑替换为 JWT 校验型 TokenVerifier，tools 层无需改动；
- 不启用 CORS：面向浏览器内 MCP 客户端的场景暂不存在，`allowed_origins` 留空，出现需求再按 SDK 文档补齐（需同时配置 `allow_headers` 含 `Mcp-*` 与 `expose_headers=["Mcp-Session-Id"]`）。

## 6. 配置项（core/config.py Settings 新增）

| 环境变量 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `RAG_MCP_ENABLED` | bool | `false` | 总开关；false 时不挂载 /mcp（404） |
| `RAG_MCP_PUBLIC_URL` | str \| None | `None` | 对外根 URL（如 `https://rag.example.com`），用于 issuer/resource_server_url；enabled 时必填（model_validator 校验） |
| `RAG_MCP_ALLOWED_HOSTS` | str \| None | `None` | 逗号分隔 Host 白名单（transport security 防 DNS rebinding）；缺省从 public_url 推导 hostname，本地开发自动附加 localhost/127.0.0.1 |

## 7. 对现有代码的改动清单

| 文件 | 改动 |
|---|---|
| `apps/backend/pyproject.toml` | 依赖 + `mcp>=2,<3` |
| `src/core/config.py` | +3 配置项与校验 |
| `src/app.py` | create_app 内构造 MCP server/container、lifespan 进入 session_manager、Mount("/mcp")（位于 StaticFiles 之前） |
| `src/utils/security.py` | SCOPES + `"kb:read"` |
| `src/routers/knowledge_bases.py` | list 路由改 `access("kb:read", ROLES)`，移除 API Key 403 特判 |
| `src/mcp_server/`（新增） | `__init__.py` / `auth.py` / `tools.py` |
| `apps/frontend/src/routes/ApiKeysPage.vue` | + `kb:read`、`graph:read` 复选框 |
| `tests/`（新增/更新） | 见 §8；`test_api_contract.py` 若覆盖 KB 列表鉴权需同步更新 |
| `docs/operations/deployment.md` | 补充 /mcp 端点与客户端接入说明（Phase 4） |

不改动：`rag/`、`db/`、`services/` 各服务实现；现有 REST 路由行为（除 KB 列表鉴权按决策点调整）。

## 8. 测试方案

单元（`tests/unit/test_mcp_auth.py`、`test_mcp_tools.py`）：

- ApiKeyTokenVerifier：有效 key → AccessToken（scopes/subject 正确）且 touch_key 被调用；过期 / 已吊销 / 未知 key → None；
- scope 拒绝：无对应 scope 的 token 调用各 tool → `[insufficient_scope]`；
- 功能开关：`agentic_enabled=false` 调 agentic_rag → `[feature_disabled]`；graph 同理；
- 存在性：kb 不存在 → `[not_found]`；
- 返回结构：retrieve 结果与 `chunk_payload` 字段一致（fake RetrievalService）。

集成（`tests/integration/test_mcp_api.py`，httpx ASGITransport 直连 create_app 产物）：

- 无 Authorization POST /mcp → 401 且带 `WWW-Authenticate`；
- `RAG_MCP_ENABLED=false` → /mcp 404，其余路由不受影响；
- 带有效 API Key：initialize 握手 → tools/list 断言 4 个 tool 名称与 schema → tools/call `retrieve` 断言结果结构；
- 现有 REST 契约测试全量回归。
- 注意：SDK 的 in-memory `Client(mcp)` 会**跳过 HTTP 鉴权层**，鉴权断言必须走 HTTP。

手工验收：

- MCP Inspector（`uv run mcp dev`）连 `http://127.0.0.1:8001/mcp` 走通 handshake 与 tools/call；
- Claude Code 配置真实 API Key 端到端完成一次 retrieve + agentic_rag。

## 9. 分阶段实施计划

**Phase 1 骨架挂载（约 0.5 天）**

1. 加依赖 `mcp>=2,<3` → verify: `uv sync` 通过、现有测试不回归；
2. Settings 新增 3 配置 + 校验 → verify: `test_config.py` 新用例（enabled 无 public_url 报错）；
3. `src/mcp_server/` 骨架（含临时 ping tool）+ app.py 集成 Mount/lifespan/transport_security → verify: 集成测试 handshake 成功；开关关闭时 /mcp 404。

**Phase 2 鉴权（约 0.5 天）**

4. ApiKeyTokenVerifier + AuthSettings → verify: 无 token 401、有效 key 握手成功、过期 key 401；
5. `kb:read` scope 落地（SCOPES + KB 路由 + 前端复选框，含补 `graph:read`）→ verify: 单元测试 + 契约测试更新通过。

**Phase 3 tools（约 1 天）**

6. 实现 4 个 tool（含 scope/开关/存在性检查与审计）→ verify: §8 单元 + 集成用例逐 tool 通过；
7. 移除临时 ping tool → verify: tools/list 恰为 4 个。

**Phase 4 文档与验收（约 0.5 天）**

8. 部署文档与客户端接入指南（Claude Code / Cursor 示例）；
9. Inspector + Claude Code 手工验收 → verify: 真实知识库完成一次检索问答。

## 10. 风险与开放问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| SDK v2 发布不久，API 仍在演进 | 升级成本 | 锁 `mcp>=2,<3`；升级前查 CHANGELOG；tools 层与 SDK 耦合面小（仅装饰器与 get_access_token） |
| 未来多 worker 部署破坏进程内 MCP 会话 | /mcp 间歇失败 | 当前 `--workers 1` 不受影响；扩容前需 sticky session 或评估无状态模式 |
| `kb:read` 放开 API Key 枚举知识库 | 元数据泄露面扩大 | 独立 scope、管理员显式签发；备选：去掉列表 tool（§4 决策点） |
| 大 top_k 返回占用客户端 token | 成本 / 上下文溢出 | 沿用 schema 上限 20；接入文档建议 top_k=5 |
| Bearer token 明文传输 | 凭据泄露 | 生产强制 HTTPS；API Key 可吊销、有过期；审计 last_used_at |

已决策：

- MCP server 对外名称定为 **`antler-rag`**（与仓库名一致，命名约定见 §5.1）；
- `kb:read`：**新增 scope，受控放开知识库枚举**（含 HTTP 路由与前端复选框改造，详见 §4）；
- `chat` tool：**本期不做**（已列入 §1 非目标；客户端 agent 通常基于 retrieve 结果自行合成答案）。

开放问题：无，全部决策点已确认，可按 §9 进入实施。

## 附：参考资料

- MCP Python SDK v2 文档：Add to an existing app（run/asgi，挂载与 lifespan 机制）、Authorization（TokenVerifier/AuthSettings）
- SDK 仓库：modelcontextprotocol/python-sdk（v2 为当前稳定线，v1 兼容锁 `mcp>=1.28,<2`）
- 本项目现有约定：`apps/backend/src/rag/agentic.py`（安全原则）、`routers/dependencies.py`（scope 鉴权模式）
