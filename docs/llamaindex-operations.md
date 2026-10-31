# LlamaIndex 索引运维

运行内核使用 `llama-index-core==0.14.16`、Chroma adapter 0.5.5（确切依赖见 `apps/backend/uv.lock`）。CI 和容器通过锁文件安装。应用仍为单写入进程，不修改 SQLite schema。新 collection 为 `<embedding_collection>-li-v1`。普通检索经过 BaseRetriever；节点由 ChromaVectorStore 序列化，原始 cosine distance 单次查询取得，阈值为 clamp(1-distance, 0, 1)。旧 collection 不会被自动修改或删除。

## 上线前转换

以下命令均在 `apps/backend` 目录运行，使用部署环境的同一组 `RAG_*` 配置。不得对正在写入的数据目录执行转换。先在完整备份的副本上演练。

1. 停止应用及全部维护写入进程，完整备份 `RAG_DATA_DIR`（SQLite、Chroma、uploads 一起），保留旧镜像、锁文件和模型配置。退出所有读取该目录的 Chroma 进程后再复制或恢复目录。
2. 运行预检：

   ```sh
   uv run --locked python -m rag.migrate --report /backup/preflight.json
   ```

   预检读取业务目录、校验 schema、原件 SHA256、实际切片、结构 metadata 和向量。它不调用模型，不修改业务状态，不创建目标 collection；Chroma 公共客户端仍可能创建自身运行文件，因此要求停机。报告中的 `complete=true` 在 dry-run 中只表示预检通过。
3. 正文、分块、模型身份及维数不变时执行格式转换：

   ```sh
   uv run --locked python -m rag.migrate --apply --report /backup/conversion.json
   ```

   格式分支直接复制已有向量，embedding 调用数为零，保留 chunk/document ID、SQLite 和图谱。确定性 ID 与按文档替换允许中断后重跑。目标设置 `migration_complete=false`，全部记录验证通过后才设为 true；应用拒绝不完整目标。报告记录每个文档分支、原因、正文哈希、核验结果及业务状态变更标志，任一失败退出码为 1。
4. 若预检要求重建，先审查 `--rebuild` dry-run 的受影响文档和 chunk 数量，再执行：

   ```sh
   uv run --locked python -m rag.migrate --rebuild --report /backup/rebuild-preflight.json
   uv run --locked python -m rag.migrate --apply --rebuild --report /backup/rebuild.json
   ```

   更换模型导致源 collection 名变化时，显式添加 `--source-collection <旧collection名称>`。模型身份不同强制重建。重建复用 DocumentIndexingService：indexing/ready/failed、chunk_count、图谱清理及补偿均照常执行，仅删除目标 collection 中的文档。`business_state_changed` 在首次业务写入前持久化；从此即使服务尚未上线，也应按完整备份回滚。SHA256 不符始终中止，不能在转换工具中接受原件变化。损坏 schema/结构元数据和孤立旧向量须先修复。
5. 审查报告，启动新版本，保持写入入口关闭，验证健康、切片分页、知识库/文档过滤、请求重排、聊天来源、Agent 降级。通过语义和性能门槛后恢复写入。不要把转换成功等同于发布验收成功。

默认本地 embedding 仍调用 Chroma 的 DefaultEmbeddingFunction，模型及预处理未替换；可能需要部署环境已有的本地模型缓存。外部 embedding 每批最多 10 条，严格校验数量、索引、维数与有限数值。所有向量操作传显式 embedding，不使用 LlamaIndex 默认云模型或全局 Settings。

## 评估与性能

至少准备 50 条实际业务问题，人工标注相关 chunk、引用正确性、无答案处理，固定原件、模型及配置。仓库 stub 测试只作契约回归。业务问题及人工标注不能由程序虚构，本次代码实施不代表真实语义门槛已通过。

可用只读命令进行固定向量/召回和性能比较：

```sh
uv run --locked python -m rag.benchmark /backup/questions.jsonl --report /backup/benchmark.json
```

每行格式为 `{"knowledge_base_id":"...","query":"...","embedding":[0.1,0.2],"relevant_ids":["doc:0"]}`。embedding 应由原/目标共同模型事先对该 query 生成。缺省 embedding 时使用该知识库首条存量向量，只验证格式与性能，报告 `semantic=false`，不能当作语义评估。脚本不调用模型，每个问题两条路径各预热 10 次，再计时至少 100 次，报告 Recall@5、MRR、p50/p95、ID 一致性和 p95 比值。候选路径包含 LlamaIndex Retriever 的框架开销；上游模型耗时另行测量。空标注问题的召回指标为 null，无答案正确性和引用正确性需人工核验。相同分数可有不同顺序。

发布门槛：Recall@5/MRR 和人工引用正确性不下降；普通 chat 最多一次模型调用；格式转换零 embedding；固定环境检索 p95 不超过旧基线 1.2 倍。未达标须定位并记录原因。

## 回答及请求预算

`RAG_ANSWER_CONTEXT_CHARACTERS` 默认 24000，按 system prompt、问题、来源标签和正文的 Unicode 字符总量限制，不是 tokenizer 的 token 估算。只保留连续的完整证据块，API sources 与实际送入模型的证据一致；无完整证据不调用模型。部署时应按模型实际上下文容量设置保守字符预算。

Agent 固定执行原问题检索、规划、同知识库补充检索、去重、回答。每次外部步骤开始前扣减 step，规划/回答扣减 LLM 调用次数；原问题包含在去重后的 max_subqueries 中。无隐式模型重试。扩展前预留一步回答和一次 LLM 调用；预算不足、规划/回答失败或整体超时复用保存的原问题来源，不再次检索。请求状态独立；整体截止时间包含排队，模型请求受剩余时限约束。同步调用最多同时运行 4 个，超时取消等待后仍占工作线程名额直到底层返回，迟到结果不修改请求 trace/sources。同步本地 Chroma 查询不能被强行终止。

## 回滚和恢复演练

只有全部走纯格式分支且备份后没有任何 SQLite/uploads 业务写入，才可直接切旧镜像和旧 collection。显式重建或已恢复在线写入后，停止所有进程并恢复完整备份；只切 collection 会留下不一致的文档/图谱状态。保留新写入需要先导出并验证重放方案。

恢复演练应在隔离目录执行：记录备份前文档 ready/chunk_count、原件 SHA256、图谱事实和查询；模拟重建失败/中断，确认目标不允许启动；关闭全部进程，移走失败目录、恢复完整备份，用旧版本启动，复核上述记录。正式生产数据、镜像切换、恢复演练与人工业务评估均由维护窗口执行，首次发布不清理旧索引和备份。
