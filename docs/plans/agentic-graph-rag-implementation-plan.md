# Antler RAG：Agentic RAG 与 Graph RAG 实施计划

> 状态：Draft（已依据当前仓库校正）
> 范围：在保持单容器、单写入进程和现有 `/api/v1/retrieve`、`/api/v1/chat` 合约不变的前提下，分阶段交付受控 Agentic RAG 与可追溯的 Graph RAG。

## 1. 当前基线与边界

### 已确认的仓库事实

- 后端是 Python 3.11+ / FastAPI；入口和全部 API 路由在 `apps/backend/src/app.py`。`/api/v1/retrieve` 与 `/api/v1/chat` 都直接调用 `RAGStore.retrieve`，尚不存在 `RetrievalService`。
- `apps/backend/src/rag/store.py` 使用一个嵌入式 Chroma collection，按 `knowledge_base_id`（以及可选 `document_ids`）过滤；可选 TEI Cross-Encoder rerank 已实现。
- 元数据在 SQLite；`Database.migrate()` 只显式执行 v1 和 `_migrate_v2()`，不会自动发现新增的 `db/migrations/*.sql`。数据库以 WAL、`BEGIN IMMEDIATE` 和 5 秒 busy timeout 使用，且 README 明确只支持一个共享数据卷的应用容器/写入进程。
- 文档上传、切块、向量写入目前在 `upload_documents` 请求内同步完成；仓库没有队列、worker 或持续任务执行器。
- 权限是工作区级角色（`admin`、`editor`、`viewer`）和 API Key scope；当前不存在知识库或文档级 ACL。所有已授权工作区用户可访问活动知识库。新能力只能保持该语义，不能宣称提供 KB 级授权。
- 当前 API Key scope 是 `retrieve`、`chat`、`documents:read`、`documents:write`、`documents:delete`。API Key 不能调用无 scope 的端点；普通会话依据路由指定角色授权。

### 非目标

- 不支持任意代码、URL/网络访问、外部传入工具、后台无限循环或自动修改知识库。
- 首期不提供跨知识库关系、企业本体/规则推理、社区发现或多实例共享 SQLite/Chroma。
- 本计划不把“异步”当作既有能力；耐久后台构建需要先作出并实现任务执行方案（见开放问题）。

## 2. 目标架构与关键调用链

```text
HTTP request
  -> app.py: 认证 / role-or-scope 校验 / knowledge_base active 校验
  -> RetrievalService
       -> VectorRetriever -> RAGStore (Chroma)
       -> KeywordRetriever -> SQLite FTS5（启用后）
       -> GraphRetriever -> GraphStore (SQLite)
       -> EvidenceMerger -> 可选 Reranker
  -> AgentService（仅 agentic endpoint）
       -> bounded planner -> allowlisted retriever tools -> evidence assessment -> answer
  -> 审计摘要、request_id 和安全的 trace 响应

Document ingestion
  -> app.py 上传
  -> RAGStore.index（保留现有同步路径；不触发图抽取）

Admin graph rebuild
  -> app.py 管理重建动作
  -> GraphBuildService -> extraction -> one SQLite transaction upsert provenance/status
```

`app.py` 仍是 HTTP、认证、校验、审计和错误映射的边界；检索/编排逻辑不得再次写入路由。所有 retriever 入参必须来自已校验的 `knowledge_base_id`、可选的已存在 `document_ids` 和服务端限制后的 `top_k`。文档文本、LLM 输出、planner JSON 和抽取结果均是不可信数据。

**首期上传决策：**上传成功仅完成现有的文本提取、切块和向量索引，**绝不**在 HTTP 请求内调用 GraphBuildService 或 extractor。新上传、重传或图数据被清理后的文档在图状态中显示 `not_built`/`stale`，只能由管理员 rebuild 纳入图谱。这样 `/documents` 的 201 成功路径不增加 LLM 调用、图构建排队或新的超时承诺；上传失败也不存在本请求产生的图抽取记录需要补偿。

## 3. API 与兼容性契约

### 保持不变

- 不改变 `/api/v1/retrieve` 的 `{results: [...]}` 响应，或 `/api/v1/chat` 的 `{answer, sources}` / 未配置模型时的现有来源回退行为。
- `RetrieveRequest`、`ChatRequest` 的校验范围、`message` 兼容别名、`X-API-Key` 和 Bearer session 继续有效。旧客户端不会被静默切换到 Agent 或 Graph。

### 新端点（显式 opt-in）

| 端点 | 认证与授权 | 请求/响应要点 | 目的 |
| --- | --- | --- | --- |
| `POST /api/v1/agentic-rag` | API Key `agentic:query` 或任意已授权工作区角色 | 请求：`knowledge_base_id`、`message`、`top_k`、`mode`、`include_trace=false`；响应：`answer`、`sources`、`retrieval_mode`、可选 `trace_id`/受限 `trace` | 受限多步问答 |
| `POST /api/v1/graph/search` | API Key `graph:read` 或任意已授权工作区角色 | 请求仅为 `knowledge_base_id`、`query`、`top_k`、可选 `document_ids` 和 `max_hops`；响应以 `{results: [...]}` 包裹统一 `Evidence` | 只读图检索 |
| `GET /api/v1/knowledge-bases/{knowledge_base_id}/graph/status` | API Key `graph:read` 或任意已授权工作区角色 | 返回每文档/知识库聚合状态和安全失败码，不返回原文或模型 prompt | 图构建可见性 |
| `POST /api/v1/knowledge-bases/{knowledge_base_id}/graph/rebuild` | **仅 admin Bearer session**；不授予 API Key scope | 请求必须在非空、去重的 `document_ids` 与 `all_documents=true` 中二选一；前者还须逐一验证属于该活动 KB。在已选择并实现耐久任务时返回 `202` 和 build id，在同步方案时返回最终构建结果 | 管理重建 |
| `GET /api/v1/features` | API Key `retrieve` 或任意已授权工作区角色 | 返回各 retrieval/agent mode 的全局启用与运行就绪状态，供 UI 决定是否显示 opt-in 控件 | 能力发现 |

`graph/search` 不接受向量专属的 `score_threshold` 和 `rerank`，也不接受 Agent `mode`/`include_trace`；`max_hops` 仅允许 1 或 2，`top_k` 与 `document_ids` 复用 `RetrieveRequest` 的既有上限与 KB 所属校验。`GET /api/v1/features` 的固定响应形状为 `{modes: {vector, keyword, graph, hybrid, agentic}}`，其中每个 mode 是 `{enabled: bool, ready: bool, reason: null | "feature_disabled" | "dependency_unavailable" | "not_configured"}`。它只报告全局配置/依赖可用性；所选 KB 是否已有可查询图数据必须再由 `graph/status` 判断，不把 `graph_not_ready` 伪装为全局 feature 状态。

`mode` 仅允许 `auto`、`vector`、`keyword`、`graph`、`hybrid`；被 feature flag 禁用或图谱未就绪的 mode 必须返回定义明确的 `feature_disabled` / `graph_not_ready`，或在 `auto` 模式记录降级后走 Vector。`include_trace` 仅返回步骤摘要（工具名、计数、耗时、错误码、证据 ID）；不返回 chain-of-thought、system prompt、API Key、原始完整文档或未采纳的模型文本。

`SCOPES`、`ApiKeyCreate` 默认项、`README.md` scope 表和 `ApiKeysPage.vue` 必须同步新增 `agentic:query`、`graph:read`。不新增 `graph:rebuild` scope，避免任意 API Key 触发昂贵/破坏性的重建；这与现有 `access(required_scope)` 语义相容。

## 4. 数据模型、迁移与一致性

### SQLite v3 迁移

不能只新增一个 SQL 文件。按以下顺序修改 `apps/backend/src/db/repository.py`：

1. 将 `Database.migrate()` 扩展为 `if version < 3: self._migrate_v3()`，并在版本高于该代码所支持的最大版本时抛出启动错误；当前实现只会跳过未知高版本，无法满足第 4 节的回滚承诺。v3 只在整个 transaction 成功后记录到 `schema_migrations`。
2. `_migrate_v3()` 使用一个连接和 `BEGIN IMMEDIATE`；保持 `PRAGMA foreign_keys=ON`，创建表/索引后在**提交前**执行 `PRAGMA foreign_key_check`，无违反时插入 v3 migration record 并 commit，任一异常 rollback。**v3 的每条 DDL/DML 必须以逐条 `conn.execute()` 执行，禁止在该方法或其调用的 helper 中使用 `conn.executescript()`。**现有连接是 autocommit 模式，而 Python `sqlite3.executescript()` 会先隐式提交挂起事务；照抄 v2 的模式会破坏本节的原子性承诺。不可照搬 v2 在 commit 后才检查 FK 的顺序；它不能使失败的 FK 检查回滚已经提交的 schema。
3. 创建下列最小表。`graph_builds.id` 为主键，`requested_by` 为可空 `users(id)` FK；调用方传入当前会话的 `principal.user_id`，没有可归属用户时写 SQL `NULL`，**不得**以 `principal.user_id or ""` 写空字符串。`graph_document_states` 的主键为 `(knowledge_base_id, document_id)`，其 `build_id` 为 `graph_builds(id)` FK。`relation_mentions.build_id` 同样引用 `graph_builds(id)`。为每一张按知识库查询的表建立以 `knowledge_base_id` 为前缀的复合索引。所有引用必须声明 FK，并为跨知识库实体引用使用复合 FK：`entities` 和 `relations` 都额外声明 `UNIQUE(knowledge_base_id, id)`；`entity_aliases.entity_id` 引用 `entities(id)`；`relations` 以 `(knowledge_base_id, subject_entity_id)` 和 `(knowledge_base_id, object_entity_id)` 分别引用 entity 复合唯一键；`entity_mentions` 以 `(knowledge_base_id, entity_id)` 引用 entity，`relation_mentions` 以 `(knowledge_base_id, relation_id)` 引用 relation。`graph_document_states` 和 mentions 的 `document_id` 引用 `documents(id)`；`graph_builds.knowledge_base_id` 和各图表的 `knowledge_base_id` 引用 `knowledge_bases(id)`。对 SQLite 不能以 FK 表达的 `chunk_id` 所属关系，GraphStore 必须在同一 transaction 内依据受信任的索引清单校验。这样 `PRAGMA foreign_key_check` 才能实际覆盖关系/mention 断链和跨 KB 引用：

```text
graph_builds(id, knowledge_base_id, requested_by, status,
             extractor_model, extractor_version, schema_version,
             requested_at, started_at, finished_at, error_code)
graph_document_states(knowledge_base_id, document_id, build_id,
                      source_sha256, status, extractor_model, extractor_version,
                      indexed_at, error_code, updated_at,
                      PRIMARY KEY(knowledge_base_id, document_id))
entities(id, knowledge_base_id, canonical_name, normalized_name, entity_type,
         created_at, updated_at, UNIQUE(knowledge_base_id, normalized_name, entity_type))
entity_aliases(id, entity_id, normalized_alias, UNIQUE(entity_id, normalized_alias))
relations(id, knowledge_base_id, subject_entity_id, predicate, object_entity_id,
          confidence, extractor_model, extractor_version, created_at, updated_at,
          UNIQUE(knowledge_base_id, subject_entity_id, predicate, object_entity_id))
entity_mentions(id, entity_id, knowledge_base_id, document_id, chunk_id,
                start_offset, end_offset, UNIQUE(entity_id, chunk_id, start_offset, end_offset))
relation_mentions(id, relation_id, knowledge_base_id, document_id, chunk_id,
                  build_id, UNIQUE(relation_id, chunk_id, build_id))
```

`chunk_id` 必须等于现有 Chroma 格式 `{document_id}:{chunk_index}`；提取器需保存 Chroma 实际索引用的 chunk 文本/索引输入，不能对文件重新切块后假定 ID 相同。实现时新增供上传和 GraphBuildService 共用的内部 chunk 产物（ID、index、text）；保留现有 `RAGStore.index(...)->int` 返回契约，不能通过读取 Chroma 私有存储或第二次切块推导。`relations` 不直接携带唯一来源；`relation_mentions` 是关系 provenance，防止一条事实被多文档支持时删除一个文档便错误删除事实。`entity_mentions` 有意不携带 `build_id`：实体的“无 provenance”定义为不存在任一剩余 `entity_mentions`，关系则为不存在任一剩余 `relation_mentions`；清理某文档时只在删除其 mentions 后按这两个条件删除孤儿，不得从 `graph_document_states.build_id` 推断 entity provenance。

### 删除、更新与并发规则

- 对单文档删除，先把 SQLite `documents.status` 标成 `deleting`。随后在一个 SQLite transaction 中删除该 document 的 `entity_mentions`、`relation_mentions`、`graph_document_states`，再删除无 provenance 的 relation，最后删除无 mention 的 entity（顺序必须先 relation 后 entity，以满足 FK）。该 transaction 成功后删除 Chroma chunks 和上传文件；**仅当两者均成功**才标记 `documents.deleted`。任一步失败均标为 `delete_failed`，已完成的图清理必须可安全重试；管理员重试沿用现有删除语义。知识库删除对每份文档采用同一顺序，最后才删除知识库向量和标记知识库 `deleted`。
- Chroma 和 SQLite 不能跨存储原子提交。因此图清理与文档状态必须先可重试；向量删除失败不得把文档标记为 `deleted`，也不得依赖回滚已提交的图清理。新增图构建不得标 `ready`，直到对应文档向量状态为 `ready` 且 SQLite provenance 事务成功。状态不一致时状态端点展示 `failed`/`stale`，查询只采用 `ready` 记录。
- 同一知识库的 rebuild 与删除必须以 `graph_document_states` 的条件更新（预期 `source_sha256`/build id）取得所有权，避免旧任务在新上传或删除后写回过期图数据。拥有者提交前必须再次确认 `documents.status='ready'` 和 SHA 未变；删除取得所有权后优先于构建。SQLite 的单写入约束、构建最大并发数 1 和请求级超时应配置化；跨进程或跨容器并发不在支持范围。
- 文档同 SHA256 重新上传会复用 document ID；必须先清理旧 graph provenance，再以新的 build id 写入。知识库删除必须按与当前 Chroma 清理相同的失败可重试模式清理图表。

### 版本与回滚

迁移只添加表和索引，不改写现有向量、文档或 API Key。上线前在完整 `/data` 备份副本演练迁移，备份 SQLite、Chroma、uploads 和新增图数据作为一个单元。代码回滚到不识别 v3 的版本前，服务应在启动期拒绝继续运行而非写入旧 schema；恢复方式是停服务、整体恢复与旧镜像匹配的 `/data` 备份。图数据可由原始文档和向量索引重建，但不能替代完整备份。

## 5. 按阶段的实施清单

### 阶段 0：基线与评测（无 API/数据变化）

1. 新增 `apps/backend/tests/fixtures/agentic_graph_eval.jsonl`：固定单跳、跨文档、多跳、无答案、实体歧义数据和期望引用；不得放入真实敏感文档。
2. 新增 `apps/backend/tests/integration/test_agentic_graph_eval.py`：在 mock LLM、固定 Chroma stub 下记录 Recall@K、MRR、引用精确率、延迟和 LLM 调用数。
3. 修改 `apps/backend/tests/unit/test_retrieval_pipeline.py` 与 `apps/backend/tests/integration/test_api_contract.py`：锁定当前向量阈值、rerank、错误码和旧端点 JSON 合约，作为后续重构回归基线。

验收：`cd apps/backend && uv run pytest` 通过；评测仅建立基准，不在未批准阈值前宣称质量提升。

### 阶段 1：统一检索编排（不改变旧端点）

1. 新增 `apps/backend/src/rag/retrieval.py`：定义不可变的 `Evidence`、`RetrievalFilters`、`RetrievalTrace`、`Retriever` Protocol 和 `RetrievalService`；`Evidence` 包含稳定 evidence id、KB/document/chunk 引用、内容、来源类型、分数及可选图路径。
2. 修改 `apps/backend/src/rag/store.py`：保留公开 `RAGStore.retrieve` 作为 Chroma 适配器底座，或抽出等价的 `VectorRetriever`；不得改变 Chroma filter、distance 或 rerank 行为。
3. 修改 `apps/backend/src/app.py`：在 lifespan 创建 `RetrievalService`，旧 `/retrieve`、`/chat` 通过该服务调用并将 `Evidence` 映射回现有 `chunk_payload`/sources 合约；保留现有 `validate_retrieve` 作为先行授权边界。
4. 新增 `apps/backend/tests/unit/test_retrieval_service.py` 和更新既有 API 测试，验证结果顺序、过滤、重复 chunk 合并和错误映射未回归。

关键词检索是此阶段的可选子项：先在发布所用 SQLite 镜像上用真实运行时探测 FTS5。若决策启用，新增独立的**下一版本**迁移（不能使同一个 v3 按环境产生不同 schema）以创建 chunk 镜像 FTS 表及写入路径，并相应更新支持的最大 schema 版本；若未启用，`keyword` mode 固定返回 `feature_disabled`，不引入不受支持的依赖。

### 阶段 2：受限 Agentic RAG

1. 新增 `apps/backend/src/rag/agentic.py`：实现 `classify -> plan -> retrieve -> assess -> answer` 状态机和结构化 Pydantic 模型。工具表是常量 allowlist：`vector_search`、可用时 `keyword_search`、可用时 `graph_search`；planner 不能选择其他工具或控制服务端预算。
2. 修改 `apps/backend/src/config.py` 与 `.env.example`：加入默认关闭的 `RAG_AGENTIC_ENABLED`、`RAG_AGENT_MAX_STEPS=6`、`RAG_AGENT_MAX_SUBQUERIES=3`、`RAG_AGENT_MAX_LLM_CALLS=5`、`RAG_AGENT_TIMEOUT_SECONDS=30`。所有值应使用有界 `Field` 校验；最终上限取服务端配置与请求值的较小者。
3. 修改 `apps/backend/src/app.py`：增加 `AgenticRagRequest`/响应模型、`agentic:query` 到 `SCOPES`、`POST /api/v1/agentic-rag`、审计摘要和错误映射。通过 `validate_retrieve` 后才调用 AgentService；使用单次 HTTP client 总 deadline，任何上限、JSON 解析或模型失败均终止循环并走一次 vector retrieval，不能重试到超额。
4. 新增 `apps/backend/tests/unit/test_agentic.py`、`apps/backend/tests/integration/test_agentic_api.py`：覆盖预算停止、非法工具拒绝、无答案、LLM 失败降级、trace 脱敏、API Key scope 和跨 KB document id 拒绝。
5. 修改 `apps/frontend/src/routes/RetrievalPage.vue`：仅在服务公开 feature/status 后展示 Agentic 模式和受限 trace 摘要；原 Vector/Chat 默认不变。修改 `apps/frontend/src/routes/ApiKeysPage.vue` 与 `README.md` 展示新 query scopes。

### 阶段 3：图谱构建与持久任务

1. 修改 `apps/backend/src/db/repository.py` 并新增 `apps/backend/tests/unit/test_graph_migration.py`，实施并验证第 4 节 v3 迁移、索引、v2 升级、幂等启动和 FK 检查；在测试中注入一次 v3 的提交前失败，断言仍为 v2、`sqlite_master` 中不存在任一 v3 图表/索引，以证明逐条 `execute()` 的 rollback 实际生效。
2. 新增 `apps/backend/src/rag/graph_store.py`：仅接受已验证 KB、document 和 chunk ID，提供事务化 upsert、状态转移、邻居查询和 cleanup；所有 SQL 参数化，关系谓词/类型使用允许集或长度/字符白名单。
3. 新增 `apps/backend/src/rag/graph_build.py`：定义 extractor port、JSON schema 验证、标准化、置信度门槛和 build state machine。抽取调用必须有连接/读取超时、最大 chunk/文档、最大输出大小与受控重试；prompt 将文档明确标为数据，不执行其中指令。
4. **在实现重建端点之前决定任务执行方式。** 若选择耐久异步，新增 `graph_jobs` 持久表、单 worker 启动/恢复/互斥与取消语义，并将重建返回 `202`。若不引入 worker，端点必须同步执行、带严格文档/时长上限、返回最终状态，不能伪装为异步。两种方式都要修改 `app.py` 生命周期，保证服务重启时 `running` job 变为可重试的失败/queued 状态。
5. 修改 `apps/backend/src/app.py` 的上传、单文档删除和知识库删除路径：上传完成后最多调用 GraphStore 标记/查询 `not_built` 或 `stale`，**不得**调用 GraphBuildService、extractor 或创建 build；单文档/知识库删除调用 GraphStore 清理接口。上传失败时只保留现有向量/文件补偿路径，不存在同请求图抽取记录；删除/重建事件写入 `audit_events`，detail 不含原文。
6. 更新 `README.md`、`docs/operations/backup-and-upgrade.md` 与 `.env.example`，说明 `RAG_GRAPH_ENABLED=false`、extractor model/version、confidence、max hops、构建并发和完整 `/data` 备份要求。

### 阶段 4：GraphRetriever 与 Hybrid

1. 修改 `apps/backend/src/rag/retrieval.py` 注册 `GraphRetriever`（及已确认可用时的 `KeywordRetriever`）；图查询从 question 的服务端规范化实体候选开始，最多两跳、每跳和总 evidence 均有限制，且只读 `ready` 状态和满足 `RAG_GRAPH_MIN_CONFIDENCE` 的 provenance。
2. 修改 `apps/backend/src/rag/graph_store.py`：用带 `knowledge_base_id` 的参数化 CTE/查询实现别名匹配和一/两跳扩展；返回 `Evidence` 图路径及 provenance chunk id。对实体歧义按分数排序，分数相同不猜测，保留多个候选或降级 vector。
3. 修改 `apps/backend/src/rag/retrieval.py` 的 EvidenceMerger：以 `chunk_id`/provenance 去重，保留来源类型，不把不可比较的 vector distance、图 confidence 和 rerank score直接相加；只有可用 reranker 才以相同候选内容重排。
4. 修改 `apps/backend/src/app.py`、`config.py`、`.env.example`、`README.md`、`ApiKeysPage.vue` 和 `RetrievalPage.vue` 暴露第 3 节图 API、开关、范围和状态；`graph/rebuild` 必须使用 admin-only dependency，而非 `access("graph:rebuild")`。
5. 新增 `apps/backend/tests/unit/test_graph_store.py`、`test_graph_build.py`、`test_graph_retriever.py` 及 `apps/backend/tests/integration/test_graph_api.py`，覆盖同名实体、别名、关系 provenance、多文档共享关系、删除清理、KB 过滤、构建中/失败降级和并发所有权。

### 阶段 5：上线与观测

1. 修改 `apps/backend/src/app.py` 和新服务：使用已有 `request_id` 日志记录 mode、KB 的不可逆/截断标识、步骤数、工具名、候选数、耗时、降级/错误码；实现并测试 `GET /api/v1/features` 的全局 `enabled`/`ready`/`reason` 契约，以及 `graph/status` 的 KB 级状态，两者不得混用。严禁记录 query、chunk 正文、prompt、token 或密钥。若需要 metrics，先确认部署的采集协议，不能假设 Prometheus 已存在。
2. 修改 `apps/frontend/src/routes/RetrievalPage.vue`：显示 Vector / Hybrid / Agentic 的 feature availability、图构建状态和安全 trace；手动重建控件仅对 admin 显示。修改 `apps/frontend/src/lib/permissions.ts` 以反映该 UI 限制（后端仍为权限权威）。
3. 修改 `docs/operations/deployment.md`、`docs/operations/backup-and-upgrade.md`、`README.md`：提供 feature flag、容量上限、维护窗口、迁移预演、回滚和清除图数据的运行手册。

## 6. 安全、权限与运行风险

| 风险 | 必须的控制 |
| --- | --- |
| 文档/LLM prompt injection | 文档和模型 JSON 都不拥有指令权限；结构化解析、allowlist、服务端参数上限、无任意工具/网络/代码执行。 |
| 跨知识库数据泄露 | 路由先校验活动 KB 和 document 所属；每个 GraphStore SQL 查询带 KB 条件；在 API 和 repository 测试中构造两个 KB 验证零泄露。当前并非 KB ACL。 |
| API Key 权限扩大 | 新 scope 默认不授予；重建仅 admin session；UI 不是授权边界。 |
| LLM/图服务故障与成本 | 默认 feature 关闭；单请求 deadline、调用/候选/token 输出上限、错误码与 vector 降级。 |
| SQLite/Chroma 半完成写入 | 状态机、可重试 cleanup、条件所有权、完整数据备份；不把跨存储操作误称为事务。 |
| 重建竞争、删除竞争、重启 | 单 worker/单 KB 所有权、状态 CAS、restart recovery 和删除优先规则；不支持多实例。 |
| 图抽取错误或敏感泄露 | confidence/provenance/model version、最低置信度、审计摘要脱敏、trace 最小化；低置信度不进入默认图检索。 |

## 7. 验证与发布门槛

每一阶段先运行相关后端测试，合并前在仓库根目录依次运行：

```bash
just lint
just test
just build
```

发布前额外执行：

1. 使用 v2 SQLite 夹具启动应用，验证仅一次 v3 迁移、`PRAGMA foreign_key_check`、现有用户/API Key/文档数据无变化；另在提交前人为触发 v3 异常，验证没有 v3 migration record、表或索引残留；在完整 `/data` 备份副本预演和回滚。
2. 用 admin、editor、viewer、缺少新 scope 的 API Key、具备 `agentic:query`/`graph:read` 的 API Key 测新端点的 200/401/403；确认 API Key 无法重建。
3. 对两个知识库执行同名实体、跨 KB document id、删除与并发 rebuild 场景，验证不返回其他 KB evidence，且删除后没有可查询 provenance。
4. 在 mock LLM 下验证每条 Agent 终止路径；在 LLM、reranker、graph extractor、Chroma/SQLite 错误下验证最大调用数、deadline、脱敏 trace 和明确降级/错误码。
5. 使用阶段 0 评测集比较 Vector 与 Hybrid/Agentic；在批准的引用准确率、无答案安全率、p95 延迟、成本和资源阈值之前，不为默认流量开启 feature flag。

## 8. Assumptions 与开放问题

### Assumptions

- 首期部署持续保持 README 所述的单容器、单写入进程；不会有多个副本共享 `/data`。
- OpenAI-compatible chat endpoint 可在服务端用于结构化规划/抽取；具体模型是否支持 JSON schema、上下文窗口和价格尚未确认。
- SQLite FTS5 是否可用取决于目标运行时构建，实施前必须探测；它不是当前仓库的既成能力。

### Open questions（须在阶段 3 前决策）

1. 图构建采用耐久单 worker、外部队列，还是同步受限重建？负责人需给出部署、重试、取消和重启恢复语义。
2. 首期允许的实体类型、关系 predicate allowlist、抽取模型/version、置信度阈值和人工抽样标准是什么？
3. 上线的引用准确率、无答案安全率、p95 延迟、LLM 成本、图规模/迁移阈值分别是多少？
4. 图数据增长到何种测量阈值时迁移到 Neo4j/Postgres，迁移期间的只读/回滚策略是什么？
5. 是否需要真正的知识库级 ACL？若需要，它是独立授权项目，必须先改变当前工作区级权限模型，不能夹带在本方案中。

## 9. Revision notes

- 将“已有知识库和文档权限控制”校正为“工作区级角色 + API scope；没有 KB/document ACL”。
- 将“异步/可重试抽取”改为有前置决策的实现要求，因为当前仓库没有队列或 worker。
- 将迁移计划改为修改 `Database.migrate()`/`_migrate_v3()`，因为当前代码不会自动应用新增迁移 SQL。
- 增加关系 provenance、跨 Chroma/SQLite 的非原子风险、删除/重传竞争和可恢复状态机；原方案只列 `entity_mentions`，不足以安全删除多文档支持的关系。
- 将 `graph:rebuild` 改为仅管理员 Bearer session，不向 API Key 发放该权限；在当前 `access(required_scope)` 语义下，新增该 scope 会授权持有者重建，和“普通 API Key 不能重建”冲突。
- 审核补充：将 rebuild 的 `202` 改为仅耐久任务方案可用；同步方案必须返回最终结果，避免在任务执行模型尚未决策时承诺错误的 HTTP 契约。
- 审核补充：修正删除顺序与状态转换，确保 Chroma 或文件清理失败时文档仍为 `delete_failed` 而非 `deleted`，且满足 relation/entity 外键删除顺序。
- 审核补充：补全图表主键、复合外键、提交前 FK 检查和“未知 schema 版本拒绝启动”要求；并将可选 FTS5 改为单独的后续 migration，避免 v3 因目标环境不同而产生不可审计的 schema 分叉。
- 审核修订：v3 明确逐条 `conn.execute()`、禁止 `executescript()`，因为当前 autocommit 连接中后者会隐式提交，无法实现要求的失败 rollback 与提交前 FK 检查。
- 审核修订：新增受认证的 `GET /api/v1/features` 精确契约；它报告全局 mode 可用性，KB 是否有可查询图谱仍由 `graph/status` 报告，消除前端 feature/status 依赖但没有 API 的矛盾。
- 审核修订：决定首期上传不做图抽取；上传只保留既有同步向量索引，图数据只能由管理员 rebuild 产生，避免改变 `/documents` 的 LLM 延迟和超时契约。
- 审核修订：明确 graph build 发起人使用 FK 合法的 user ID 或 `NULL`，并定义无 `build_id` 的 `entity_mentions` 的 provenance 判定与孤儿清理规则。
