# LlamaIndex 实施与验证记录

日期：2026-10-30。代码已接入新内核，发布验收尚未完成。原计划的维护窗口切换、50 条人工业务语义评估及性能门槛不能据此标记完成。操作步骤见 [运维说明](llamaindex-operations.md)。

## 已实施

- 锁定 core 0.14.16、Chroma adapter 0.5.5 及传递依赖；仅安装所需集成，新增 CI 锁文件安装。
- `contracts/nodes/embeddings/llm/vector_store/retrievers/postprocessors/runtime/synthesis/workflows` 分离领域、模型和框架边界。不修改全局 Settings，不增加独立 docstore，不改变两种字符分块算法。
- TextNode 保持原 chunk ID、正文、结构 metadata、document source relationship，metadata 不参与 embedding。文档/查询使用同一显式模型。真实 Chroma 持久化写入/过滤/删除/重开，单次查询保留原始 distance；阈值后 TEI 稳定重排。
- 普通聊天、规划、Agent 回答及图谱抽取共享兼容 LLM；一次回答调用，无隐式重试。无证据不调用模型，字符预算按完整证据块截断，sources 与实际上下文一致。
- Agent 请求级步骤/模型/去重查询预算、原问题来源保存、整体截止时间、线程实际结束才释放名额及迟到结果隔离。
- 独立迁移命令：dry-run、零 embedding 格式转换、显式重建复用业务生命周期、机器报告、完成标志、失败拒绝启动、原 collection 保留。报告在重建业务变更前落盘。
- 离线比较工具和运维文档。原 HTTP 模型重复实现已删除；`rag.agentic` 仅保留兼容导出，没有旧生产后端开关。

## 验证证据

- 后端 122 项测试；前端 8 项测试。覆盖原 API/权限、节点正文与结构、真实 Chroma 距离/过滤/重开、转换幂等与零 embedding、重建失败/部分写入补偿、SHA256 拒绝、Agent 最小预算/最后步骤失败/并发/超时/迟到线程。
- 独立进程恢复演练：完整复制 SQLite/Chroma/uploads，重建到 embedding 前使用进程退出模拟中断；退出全部客户端后恢复备份，核对文档 ready/chunk_count、原件哈希、旧向量和 entity_mentions。
- Chroma 默认本地模型直接调用与 BaseEmbedding 包装对相同两条正文产生完全相同的 384 维向量。
- 实际配置服务的最小合成请求：聊天 wire contract 通过；外部 embedding 两条文本返回 2 × 1024 维。没有向服务发送业务文档。
- `just test`、`just lint`、`just build`：通过。现有前端 lint 警告、bundle 体积警告及 Vitest 退出等待提示仍存在。
- `just docker-build`：未完成，Docker daemon 不可连接。CI 使用 Python 3.12；本地测试环境 Python 3.13.14。锁文件已解析声明的 Python 范围，尚未逐个 Python 版本构建验证。

## 性能发现与发布前修正工作

2026-10-30 本机单文档/单 chunk/二维固定向量微基准，预热每条路径 10 次后各运行 100 次：

| 路径 | p50 | p95 |
| --- | ---: | ---: |
| 旧 Chroma 查询与 RetrievedChunk 映射 | 0.363 ms | 0.612 ms |
| 新 LlamaIndex Retriever、后处理与相同映射 | 0.597 ms | 1.114 ms |

ID 一致、embedding/LLM 调用为零；p95 比值约 **1.82**，超过计划的 1.2 倍门槛。此合成样本不代表真实语义效果，不构成发布通过。

进一步 cProfile 对新链路执行 200 次：总耗时 0.167s，其中 Chroma Rust query 0.073s，框架 dispatcher 包装累计 0.160s（包含下游，不能与 query 相加），inspect.signature 0.026s、get_query_embedding 0.025s、后处理 0.010s。说明增量包含框架事件/签名检查、embedding 调用包装、节点与结果映射，不能把差异归因于模型耗时。

因此 P4/P5 保持未验收：先使用至少 50 条人工标注业务问题与固定真实向量，锁定完整数据副本和硬件重复测试，分别记录端到端检索及上述组成耗时；再依据热点优化或调整适配设计，保持授权前过滤、框架 Retriever 路径及原始距离语义。若业务数据仍超过 1.2 倍，继续优化并重新评审方案，不自动放宽门槛。微基准工具包含旧结果映射，避免只用原始数据库查询作为发布基线。

正式发布还需要真实 TEI 部署冒烟、人工引用/无答案评估、Docker 构建启动、实际备份恢复与只读切换演练。没有对当前生产数据目录执行转换、重建或删除。
