# Antler RAG：Agentic RAG 与 Graph RAG 实施计划

> 状态：Draft
>
> 目标：在现有轻量 Vector RAG 基础上，逐步增加可控的 Agentic RAG 和 Graph RAG 能力，同时保持现有 API、单容器部署和知识库隔离能力可用。

## 1. 当前基线

当前系统已经具备：

- 文档解析、切块和 Chroma 向量索引；
- 基于知识库的 Dense Vector 检索；
- 可选 Cross-Encoder Rerank；
- `/api/v1/retrieve` 检索接口；
- `/api/v1/chat` 的一次检索后 LLM 问答接口；
- API Key scope、知识库和文档权限控制。

当前不具备：

- Agent 规划、循环执行、工具调用和多步检索；
- 查询改写、问题拆解和检索结果自评估；
- 实体/关系抽取和知识图谱存储；
- 图遍历、社区发现或向量与图的混合检索。

实施原则是先把现有检索能力抽象成稳定的内部接口，再增加 Agent 和图谱模块，避免把复杂逻辑直接堆进现有 FastAPI 路由。

## 2. 目标范围

### 2.1 Agentic RAG

支持以下受控流程：

1. 判断问题是否需要检索；
2. 将复杂问题拆解为一个或多个子问题；
3. 对子问题执行向量检索、关键词检索或图谱检索；
4. 合并、去重和重排证据；
5. 判断证据是否充分；
6. 在有限次数内继续检索或生成最终答案；
7. 返回答案、来源、执行步骤和可选调试信息。

首期不做开放式自主 Agent、任意代码执行、无限循环、后台长任务和自动修改知识库。

### 2.2 Graph RAG

支持以下图谱能力：

- 从文档 chunk 中抽取实体、关系和实体类型；
- 保存实体、关系与原文 chunk 的 provenance 关联；
- 按知识库隔离图数据；
- 根据问题识别实体并进行一到两跳邻居扩展；
- 将图检索结果与向量检索结果合并后交给 Reranker/LLM；
- 支持图谱构建状态、失败记录和增量重建。

首期不做全自动企业级本体设计、复杂规则推理、图算法推荐和跨知识库关系。

## 3. 目标架构

```text
Client / External Agent
          │
          ▼
      FastAPI API
          │
          ├── RetrievalService
          │     ├── VectorRetriever ── Chroma
          │     ├── KeywordRetriever ── SQLite FTS5
          │     ├── GraphRetriever ── GraphStore
          │     └── Reranker
          │
          ├── AgentService
          │     ├── Planner
          │     ├── ToolRegistry
          │     ├── EvidenceMerger
          │     └── AnswerGenerator
          │
          └── IngestionService
                ├── Chunk / embedding index
                └── Entity / relation extraction
                      │
                      └── GraphStore
```

建议采用“端口与适配器”方式：AgentService 只依赖 `Retriever`、`GraphStore`、`LLMClient` 等协议，底层实现可以先使用 SQLite/本地存储，未来再替换为 Neo4j、Postgres 或独立图服务。

## 4. 分阶段实施

### 阶段 0：基线整理与评测集（1 周）

任务：

- 抽取 `RetrievalService`，将路由中的检索调用与响应组装解耦；
- 统一 `RetrievedChunk`、证据引用和检索诊断字段；
- 增加固定问答评测集：单跳、跨文档、多跳、无答案、实体歧义各一组；
- 记录 Recall@K、MRR、答案引用准确率、延迟和 token 消耗；
- 明确超时、最大候选数和最大 LLM 调用次数。

验收：现有 `/retrieve`、`/chat` 测试全部通过，重构前后结果在允许误差内一致。

### 阶段 1：统一检索编排层（1–2 周）

任务：

- 定义 `Retriever`、`QueryPlan`、`Evidence`、`RetrievalTrace` 数据结构；
- 将向量检索和现有 Rerank 封装为 `VectorRetriever`；
- 增加可选 SQLite FTS5 关键词检索；
- 实现证据去重、来源合并和统一排序；
- 为每次检索增加 request id、耗时、候选数量和错误类型日志。

建议内部接口：

```python
class Retriever(Protocol):
    def retrieve(self, query: str, *, knowledge_base_id: str,
                 top_k: int, filters: RetrievalFilters | None = None
                 ) -> list[Evidence]: ...
```

验收：向量、关键词和未来图检索都能通过同一接口返回证据；旧接口不需要客户端改动。

### 阶段 2：Agentic RAG 最小闭环（2–3 周）

任务：

- 新增 `AgentService`，实现有限状态流程：`classify → plan → retrieve → assess → answer`；
- 提供工具：`vector_search`、`keyword_search`、`graph_search`（初期可返回未启用状态）；
- 实现简单问题直接检索，复杂问题拆分为最多 3 个子问题；
- 通过结构化 JSON 输出约束规划结果和证据评估结果；
- 设置 `max_steps`、`max_subqueries`、`max_llm_calls` 和总超时；
- 失败时降级到一次普通 Vector RAG，不暴露内部 prompt 或密钥；
- 返回可选 trace，但默认只返回最终答案和来源。

建议新增接口：

```text
POST /api/v1/agentic-rag
```

请求字段建议包括 `knowledge_base_id`、`message`、`top_k`、`mode`、`max_steps` 和 `include_trace`。`mode` 可取 `auto`、`vector`、`graph`、`hybrid`。

验收：

- 单跳问题不会产生不必要的多轮调用；
- 多跳问题能够生成子查询并合并来源；
- 达到上限后必定停止；
- LLM 不可用时仍能返回证据或明确错误；
- 每次答案均能关联到来源 chunk。

### 阶段 3：Graph RAG 数据模型与构建（2–3 周）

任务：

- 增加 `entities`、`relations`、`entity_mentions` 或等价表；
- 所有图记录包含 `knowledge_base_id`、来源 `document_id/chunk_id`、抽取模型版本和时间戳；
- 实现实体标准化：名称清洗、类型约束、别名和基本去重；
- 从新增或更新文档中异步/可重试地抽取图谱；
- 增加图谱构建状态：`pending`、`running`、`ready`、`failed`；
- 支持按文档删除对应实体关系，避免删除文档后留下孤儿 provenance；
- 首期优先采用 SQLite 图模型，使用索引支持实体查找和一到两跳扩展。

建议关系模型：

```text
entities(id, knowledge_base_id, canonical_name, entity_type, aliases_json, ...)
relations(id, knowledge_base_id, subject_id, predicate, object_id, confidence, ...)
entity_mentions(id, entity_id, document_id, chunk_id, start_offset, end_offset, ...)
```

验收：同一知识库内实体可合并；不同知识库之间不可互相查询；每条关系可追溯到至少一个原文 chunk；重复构建不会无限产生重复数据。

### 阶段 4：Graph Retriever 与 Hybrid RAG（1–2 周）

任务：

- 从问题中识别实体，支持别名匹配；
- 查询实体邻居和关系 provenance，限制最多两跳；
- 将图路径序列化为可读证据，例如“实体 A —关系→ 实体 B”；
- 与 Vector/FTS 结果统一为 `Evidence`；
- 增加图证据权重、来源去重和 Rerank；
- 在 Agent 工具注册表中启用 `graph_search` 和 `hybrid_search`；
- 增加图谱不可用、构建中和无匹配实体时的降级逻辑。

建议新增接口：

```text
POST /api/v1/graph/rebuild
GET  /api/v1/knowledge-bases/{id}/graph/status
POST /api/v1/graph/search
```

验收：涉及实体关系的问题能召回正确路径；纯语义问题不会因为图检索噪声而明显下降；图检索故障时 Vector RAG 仍可用。

### 阶段 5：管理端、可观测性与上线（1–2 周）

任务：

- 在检索调试页增加 `Vector / Hybrid / Agentic` 模式；
- 增加图谱构建状态、失败原因和手动重建入口；
- trace 中展示步骤、子查询、工具、候选数、耗时和最终引用；
- 增加 token、LLM 调用次数、检索延迟和错误率指标；
- 增加 API scope：建议新增 `agentic:query`、`graph:read`、`graph:rebuild`；
- 更新部署、备份、升级和数据删除文档；
- 对 prompt injection、越权知识库 ID 和敏感数据泄露进行安全测试。

验收：管理员能判断索引和图谱是否就绪；普通 API Key 不能重建图谱；生产日志不包含原始密钥和完整敏感文档内容。

## 5. API 与兼容性策略

- 保持现有 `/api/v1/retrieve` 和 `/api/v1/chat` 行为不变；
- 新能力通过新端点或显式 `mode` 开关启用，默认仍为 Vector RAG；
- 对外响应统一包含 `answer`、`sources`、`retrieval_mode` 和可选 `trace_id`；
- 不把 Agent 的内部思考过程返回给客户端，只返回可审计的步骤摘要和工具调用结果；
- 所有新请求必须沿用现有 API Key、知识库和文档权限校验。

## 6. 配置建议

```dotenv
RAG_AGENTIC_ENABLED=false
RAG_AGENT_MAX_STEPS=6
RAG_AGENT_MAX_SUBQUERIES=3
RAG_AGENT_MAX_LLM_CALLS=5
RAG_AGENT_TIMEOUT_SECONDS=30
RAG_GRAPH_ENABLED=false
RAG_GRAPH_EXTRACT_MODEL=
RAG_GRAPH_MAX_HOPS=2
RAG_GRAPH_MIN_CONFIDENCE=0.65
RAG_GRAPH_STORE=sqlite
```

默认关闭新能力，先在测试知识库和评测集上验证，再按知识库或环境逐步开放。

## 7. 测试与质量门槛

### 单元测试

- 查询分类、问题拆解和最大步数控制；
- 工具注册、参数校验和错误降级；
- 证据去重、排序和引用编号；
- 实体规范化、关系去重和图路径限制；
- 知识库隔离、文档删除和增量重建。

### 集成测试

- Agentic 流程在 mock LLM 下完整运行；
- Vector、FTS 和 Graph 三类检索可合并；
- LLM、Reranker 或图谱构建服务不可用时正确降级；
- API Key scope 和跨知识库访问全部拒绝；
- 服务重启后图索引与向量索引状态一致。

### 上线门槛

- 现有回归测试全部通过；
- Agentic RAG 的无答案问题不能编造结论；
- 关键答案引用准确率达到预先设定阈值；
- p95 延迟、LLM 成本和最大资源消耗在预算内；
- 可从完整 `/data` 备份恢复 SQLite、Chroma、上传文件和图数据。

## 8. 主要风险与应对

| 风险 | 应对措施 |
| --- | --- |
| Agent 循环导致延迟或成本失控 | 严格限制步数、子查询、LLM 次数和总超时 |
| Agent 被文档中的 prompt injection 误导 | 文档内容只作为不可信数据；工具参数由服务端校验；禁止任意工具 |
| 图谱抽取错误传播 | 保存置信度、模型版本和 provenance；低置信度关系不进入默认检索 |
| 实体同名和别名导致错误连接 | 知识库内规范化、类型约束、别名表和人工抽查 |
| 图检索噪声降低普通问答质量 | 默认 Vector 模式；Hybrid 采用阈值、权重和 Rerank |
| SQLite 不适合大规模图数据 | 先定义 `GraphStore` 协议，规模达到阈值后替换为 Neo4j/Postgres 等实现 |
| 新索引与旧数据不一致 | 为 embedding、抽取模型和图 schema 保存版本，采用可重建索引和状态机 |

## 9. 推荐交付顺序

推荐先交付阶段 0–2，形成可用的 Agentic RAG 最小闭环；随后交付阶段 3–4，补齐 Graph RAG；最后完成管理端和生产化。这样可以先验证多步检索是否真实改善效果，再决定图谱抽取模型、图数据库和异步任务系统的投入规模。

## 10. 待确认决策

1. 图数据首期是否接受 SQLite，还是直接采用 Neo4j/PGGraph；
2. 是否需要异步任务队列来处理大批量图谱抽取；
3. Agentic RAG 是否允许外部 Agent 传入自定义工具；
4. 评测集、延迟和成本的上线阈值；
5. 图谱抽取优先支持的实体类型和关系类型。
