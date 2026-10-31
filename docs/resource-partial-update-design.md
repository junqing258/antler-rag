# RAG 资源局部更新方案

> 状态：待实施设计。适用于 Antler Knowledge，首期以网页为主要资源。本文描述新增能力，不代表现有接口已支持。  
> 日期：2026-10-30。关联设计：[网页采集入库](web-knowledge-ingestion-design.md)、[结构分块](plans/structure-chunking-implementation-plan.md)。

## 1. 目标与决策

一个网页对应一个稳定的 document。重新采集网页或编辑其中一个章节时，比较新旧结构，只对变化章节重新分块，只对实际 embedding 输入发生变化的切片生成向量。新增、修改、删除、移动章节均可处理。

首期采用：**稳定章节 ID + 章节级差异比较 + embedding 复用 + 完整版本清单 + SQLite 活动版本切换**。

“局部”指解析后差异处理和 embedding 计算范围，不承诺只下载网页的一部分。发布时为新版本写入完整的向量记录集合，其中未变切片复制已有向量；因此节省的是 embedding 调用，不是所有 Chroma 写入。该取舍使版本过滤、回滚和清理更明确，后续再评估跨版本共享物理记录。

验收目标：

- 更新一个章节，不重新嵌入其他未变章节；完全相同的有效输入不调用 embedding。
- 更新失败，旧版本继续可检索；检索不得返回未发布、已删除或已淘汰版本。
- 重试不重复创建有效版本；冲突不覆盖其他更新。
- 保留原始快照、结构、差异和引用版本，能够定位一次更新的来源。

非目标：逐句在线协同编辑、任意 DOM 局部补丁、自动登录、跨网页事务、多进程共享数据卷。首期必须单应用进程（workers=1）、单副本运行，这是进程内锁正确性的硬性前提。

## 2. 与当前实现的关系

当前已具备 SQLite、Chroma、结构解析和分块服务。相关入口：

| 位置 | 现有行为 | 本方案调整 |
| --- | --- | --- |
| `services/document_indexing.py` | 重建先删旧向量，再写新向量 | 新增版本化更新流程；局部更新不能调用先删后写路径 |
| `rag/store.py` | ID 为 `document_id:序号`，查询按知识库/文档过滤 | 新增版本化物理 ID、显式向量写入和活动版本过滤 |
| `rag/chunking.py` | 结构章节 ID 按出现顺序生成 | 保留其版本内定位意义；另建跨版本稳定章节 ID |
| `rag/retrieval.py` | 统一检索及证据模型 | 加入版本快照、活动版本过滤和引用版本 |
| 图谱与 Agentic RAG | 使用 chunk 来源 | 发布时使受影响文档的旧图谱不可查询 |

网页采集目前另有设计稿，本方案定义其与入库侧的版本化交接契约，不假设采集器已经上线。现有 recursive 知识库不能承诺章节级更新；保持原配置，使用整文档重新分块并复用相同输入的向量。需要章节更新时，新建 structure 知识库重新导入。

仓库当前不提供旧数据库自动迁移。实施时更新当前 schema 定义；已有数据按运维约定备份后在新数据目录重新导入，不在启动时隐式 ALTER 或转换旧索引。

## 3. 业务操作

### 3.1 从网页刷新

采用独立 crawler 推送。采集源配置、凭据引用、调度、源站网络请求和浏览器均由 crawler 管理；RAG 仅保存来源关联和不可变正文快照。刷新入口为 crawler 的 `POST /crawl-sources/{source_id}/runs`，可指定 external_id；RAG UI 将刷新动作转交 crawler 控制面，由其校验操作者权限。

crawler 经 outbox 调用 `PUT /api/v1/knowledge-bases/{kb_id}/external-documents/{external_id}`，提交 `base_version`（首次 null）、`idempotency_key`、`filename`、`content_markdown`、`publish_mode=auto|preview`，以及 metadata 中的 `source_id`、`canonical_url`、`content_sha256`、`crawled_at`、`extractor_version`。external_id 沿用采集设计的稳定键，以 `(knowledge_base_id, external_id)` 唯一定位 document，URL 或正文哈希不替代身份。

PUT 复用章节编辑的候选、预览与发布服务，不直接删除旧索引。异步接受返回 202、job_id 和可选 preview_id；终态返回 document_id、version_id 及 published/unchanged/needs_review/conflict。只有 published/unchanged 才允许 crawler 更新已入库哈希和 outbox 成功状态，202 不代表发布。manual 模式推送或异常正文骤减返回 needs_review，由有写权限用户发布固定预览。重复幂等请求返回同一任务，基础版本冲突返回 409 或任务 conflict。

crawler 保存最近确认的 version_id。新增受限 `GET /api/v1/knowledge-bases/{kb_id}/external-documents/{external_id}/sync-status`，供绑定该知识库/采集源的服务身份读取 document_id、active_version_id、sync_mode 和自身任务结果，不返回正文；冲突后据此重新提交，不能盲目覆盖。入库凭据不得暴露给浏览器。

静态页面可使用 ETag/Last-Modified 条件请求；只有已验证这些响应头代表正文时，304 才可跳过正文处理。CSR 页面不能仅依据 HTML 外壳的 304 判定内容未变，仍需执行受控渲染与正文提取。采集范围、重定向、网络访问限制沿用网页采集设计。

### 3.2 编辑一个章节

用户选择稳定章节 ID，提交完整章节正文与 `base_version`。服务端在基础快照上替换章节，生成完整候选快照，复用相同差异发布流程。前端不允许提交任意 chunk ID 来直接覆盖向量。

网页资源保存 `sync_mode=remote|manual`：章节手动编辑成功时切为 manual；后续自动刷新暂停。切回 remote 时必须预览远端快照差异并显式提交，防止下一次采集静默覆盖人工修改。首期不实现人工覆盖层合并。

## 4. 数据模型

所有主键使用服务端生成的 UUID；时间使用 UTC。下表是新增字段/表的逻辑定义，实施时补齐外键、CHECK 和唯一约束。

| 表 | 关键字段 | 约束与含义 |
| --- | --- | --- |
| `documents` 扩展 | `source_type, source_id, external_id, canonical_url, active_version_id, sync_mode` | 非空 `(knowledge_base_id, external_id)` 唯一；上传文件 external_id 为 null；来源绑定不可任意改写，删除与发布串行 |
| `document_versions` | `id, document_id, parent_version_id, status, content_hash, pipeline_fingerprint, snapshot_path, chunk_count, created_at, published_at` | status 为 staging/active/retired/failed；活动指针是发布权威 |
| `document_sections` | `version_id, section_uid, parent_uid, anchor, heading_path_json, ordinal, body_hash, effective_hash, body` | `(version_id, section_uid)` 唯一；ordinal 只控制展示顺序 |
| `document_version_chunks` | `version_id, chunk_uid, section_uid, ordinal, content_hash, embedding_key, vector_record_id, metadata_json` | 完整版本清单；同版本物理 ID 唯一 |
| `embedding_cache` | `embedding_key, model_fingerprint, input_hash, vector_blob, dimension` | 可校验的向量副本，避免依赖 Chroma 内部文件格式 |
| `resource_update_jobs` | `id, document_id, idempotency_key, request_hash, base_version_id, candidate_version_id, status, diff_json, error_code, attempts, timestamps` | `(document_id, idempotency_key)` 唯一 |

数据库写入还应校验 version、section、chunk 的 document 归属，不能只凭客户端传入 ID 关联。

原始响应/正文快照存放在版本目录，文件先落盘完成再登记为可发布。只读版本文件不得覆盖。快照至少包含规范正文、章节树、提取规则版本和安全来源信息；不保存认证头或 cookie。

### 4.1 身份与哈希

- `section_uid`：跨版本延续的章节身份；不使用章节序号或内容哈希直接充当身份。
- `chunk_uid`：逻辑切片身份；一对一匹配的旧切片延续 ID，其余生成新 ID。它与排序序号分离。
- `vector_record_id = document_id:version_id:chunk_uid`：Chroma 物理 ID，不同版本互不覆盖。
- `body_hash`：规范化后的章节正文哈希。
- `effective_hash`：章节正文、实际标题前缀及影响分块的配置的哈希，用于判定是否需要重新分块。
- `embedding_key = SHA256(model_fingerprint + input_hash)`：实际 embedding 输入的缓存键。各字段采用有边界的规范序列化后计算，不做无分隔拼接。

`model_fingerprint` 包含服务地址标识、模型名、部署修订标识、维数和输入预处理版本，不包含密钥。上游同名模型更换权重时必须更新部署修订标识。`pipeline_fingerprint` 另记录正文提取器、规范化器、分块器和配置。

### 4.2 文档与版本状态

`documents.status` 表示当前服务状态，候选进度由 job/version 表示。首次入库无活动版本时为 indexing，发布成功置 ready，失败且仍无活动版本时置 failed。有活动版本的刷新/预览期间保持 ready；候选失败、冲突或取消只更新 job/候选版本，不清空当前哈希或块数，不将可服务文档置 failed。发布事务同时更新 ready、哈希、块数及快照引用。

staging/failed 版本不可在线检索；active 必须与活动指针一致；retired 仅供历史读取。删除在写锁内置 deleted 并清空活动指针。活动索引损坏时置 failed，保留指针供修复，统一查询排除非 ready 文档，不自动切换历史版本。版本化入口必须替换当前无条件置 failed/清理旧索引的补偿分支，不可直接复用。

## 5. 正文规范化与章节匹配

### 5.1 规范化规则

正文提取后统一换行、去掉已确认的导航等模板噪声、规范普通段落间的空行。代码块保留缩进和空白，表格保留行列顺序，列表保留层级。不得删除数字、标点或全局折叠全部空格来提高命中率。

保留网页原生标题锚点。无标题导言作为独立章节。全文没有可靠标题时，按一个正文章节处理，接受较大的重新分块范围。正文为空、疑似登录页、正文骤减超过配置阈值时不自动发布，进入需检查状态。默认正文字符数减少超过 50% 时要求预览确认；这只是异常检测，不能作为判断内容正确的依据。

### 5.2 匹配顺序

对候选章节和旧版本执行一对一匹配，匹配成功后才继承 `section_uid`：

1. 唯一且相同的网页原生锚点，检查章节类型及上下文无明显冲突。
2. 已匹配父章节下，唯一相同的标题与正文哈希。
3. 全文范围内唯一相同的正文哈希，识别移动和改名。
4. 已匹配父章节下唯一相同的标题，结合邻居定位正文修改。
5. 剩余项使用正文相似度与邻居辅助匹配；初始建议相似度至少 0.90、最优与次优差至少 0.10，阈值须通过固定样例校准。

同名标题、重复正文不能仅按第一次出现强行匹配。候选不唯一时退化为删除旧章节、新增章节，允许多计算向量，不能错误继承身份。章节拆分/合并亦使用该保守退化策略，并在差异预览中显示。

匹配只影响身份连续性与成本，不作为内容真伪判断。即使匹配失败，相同 embedding 输入仍可命中缓存。

### 5.2.1 切片身份匹配

未变章节直接继承切片身份。重分块章节只在已匹配的同一 section_uid 内，按规范化后实际切片正文哈希进行顺序对齐（LCS/diff），哈希相同仍核对原文字节。只继承所有最优顺序对齐中配对唯一的旧 chunk_uid；重复正文导致配对不唯一则生成新 ID，不按首次出现猜测。正文变化的块也生成新 ID，不做模糊身份继承。新 ID 首次生成后持久化到候选清单，重试读取同一清单。

身份与向量复用独立：新 ID 只要输入和模型指纹相同仍可复用向量；embedding_inputs_computed 按实际请求的唯一 embedding_key 统计，不按 chunks_created 或 ID 变化推算。

### 5.3 变更分类

| 变化 | 分块与向量处理 |
| --- | --- |
| 正文、标题前缀及配置均未变 | 直接复用切片和向量，只更新版本内位置 |
| 章节正文变化 | 重新切分整个章节，对每个新块检查 embedding 缓存 |
| 父标题变化 | 递归检查后代的实际标题前缀；前缀变化则重新分块/检查缓存 |
| 章节移动 | 重算标题路径与位置；实际输入未变则不生成向量 |
| 章节删除 | 新版本清单不包含该章节及其切片 |
| 仅来源 URL、显示元数据变化 | 发布新元数据版本，输入未变不生成向量 |
| 提取/规范化/分块版本变化 | 重新处理完整文档，实际输入相同仍可复用向量 |
| embedding 指纹变化 | 使用新的向量空间并执行全量重建，不作为普通局部刷新发布 |

分块沿用结构分块预算，标题前缀计入长度，重叠不跨章节。章节内一个段落变化可能改变该章节多个切片边界，这是允许的成本，不承诺“一段只更新一个向量”。

## 6. 更新与发布流程

```text
创建任务 → 获取/编辑候选快照 → 规范化与结构解析
    → 匹配章节 → 计算差异 → 无有效变化则结束
    → 变化章节重分块 → 查询向量缓存 → 嵌入缺失项
    → 写入完整 staging 版本 → 验证记录与快照
    → 比较基础版本并切换 active 指针 → 延迟清理旧版本
```

1. 校验知识库、文档归属、写权限和幂等键，记录 `base_version_id`。相同键相同请求返回原任务；相同键不同请求返回 409。
2. 采集器或编辑器产生不可变候选快照。解析失败保留当前版本，任务失败。
3. 比较规范正文、有效元数据与处理配置；完全一致返回 unchanged，记录检查时间，不创建新活动版本。
4. 保存差异和候选版本，复用未变章节的切片；对变化章节分块，匹配逻辑切片，并计算输入哈希。
5. 按“embedding_cache → 保留版本记录回读 → 重算”取向量。缓存缺失/损坏时，根据同模型指纹及输入哈希的清单定位旧物理 ID，通过公共 `collection.get(ids=[...], include=["embeddings"])` 回读，核对正文、指纹、维数和有限数值后回填缓存。两处均无有效副本才计算唯一缺失输入；分别记录 embedding_cache_hits、vector_readback_hits、embedding_inputs_computed。回读依赖的版本登记为任务保护对象，避免并发清理。显式传 `embeddings` 写 Chroma，禁止隐式重复 embedding。
6. 用新物理 ID 幂等 upsert 完整候选版本。验证实际 ID 集合、数量、文本哈希、metadata、维数与清单一致，不能只比较计数。
7. 获取线程级发布写锁，执行唯一发布事务：`BEGIN IMMEDIATE → 校验 document 未删除、active=base、候选为已验证 staging → CAS 更新活动指针（首次用 IS NULL，必须恰好影响一行）→ 更新新旧版本状态、documents.status=ready、哈希/块数/快照引用、图谱 stale、知识库内容修订号及 job=published → COMMIT`。任一检查或写入失败均 ROLLBACK，禁止中途提交。
8. COMMIT 或 ROLLBACK 后释放写锁；CAS 冲突回滚后用独立短事务记录 job=conflict，不修改当前活动版本。
9. 写锁内不执行网络抓取或 embedding。基础版本冲突时任务置 conflict，保留候选供诊断，由客户端基于新版本重新提交，首期不自动合并。
10. 异步清理过期版本及孤立 staging。清理失败重试，不撤销已成功发布版本。

首次入库也走此协议，base 为 null。整个流程是“预写、验证、指针提交、补偿清理”，不宣称 SQLite 与 Chroma 存在跨库事务。

## 7. 检索一致性

仅增加 SQLite 的 active 指针不足以屏蔽 Chroma 残留数据，必须修改所有检索入口。

首期使用基于 `threading.Condition` 的线程级读写锁，写者优先；不能使用 asyncio.Lock 保护线程池里的同步 Chroma 调用。检索在读取版本快照、召回、图谱扩展和证据物化期间持读锁；发布、删除、版本清理持写锁。异步入口将整个同步临界区交给同一线程执行，不在事件循环阻塞等待锁，也不跨 await 持锁。LLM 生成在证据物化后释放读锁，保留证据版本。

硬性部署前提为 uvicorn workers=1、replicas=1，而非仅单写入进程。官方启动入口固定单 worker，显式多 worker 配置拒绝启动。每个应用进程在 lifespan 写入前独占数据目录 OS 文件锁，持有至退出，第二个 worker/副本打开同一目录必须失败退出，不能仅靠环境变量检测。文件锁语义不可靠的网络文件系统不受支持；不同数据目录的副本不能视作同一资产服务的扩容。

向量查询流程：

1. 在读锁内读取授权范围内每个 document 的活动版本映射。
2. 构造过滤条件：知识库约束 AND `OR(document_id=d1 AND version_id=v1, …)`；无活动文档直接返回空结果。
3. 文档多时将过滤条件分批，每批使用相同候选预算，合并距离排序后再按既有规则 rerank/截取。每批候选预算至少等于本次全局候选预算，避免分批导致漏掉全局应召回项。
4. 只解码该快照中的版本记录；异常记录报告一致性错误并排除，不能回退到不带版本条件的查询。

不能先查询全 collection 的 top-k 再过滤旧版本：旧记录可能占满候选，导致有效召回不足。过滤表达式能力和批大小须通过安装版本的 Chroma 集成测试确认。

向量、聊天、Agentic、切片查看、上下文扩展与图谱检索均使用统一活动版本规则。证据至少返回 `document_id, version_id, section_uid, chunk_uid, source_url, source_anchor`。旧引用读取历史快照需重新校验当前读权限，已删除资源不因历史引用而绕过删除。

## 8. 图谱与缓存

首期不做关系抽取的局部合并。发布时在同一事务将文档图状态设为 stale；所有图谱检索必须依据活动版本和图状态筛除旧 mentions，并排除只由失效来源支持的实体/关系。保留其他有效文档支持的公共实体与关系。

图谱后台按新活动版本重建，完成时再次比较版本，只有仍为该版本才能置 ready；旧版本重建结果不能覆盖新状态。若当前图谱查询链无法完整实施上述过滤，首期应禁用受影响知识库的图谱扩展，待重建成功后恢复。

检索/答案缓存键包含知识库内容修订号与模型/检索配置指纹；发布时同事务递增内容修订号，避免复用旧答案。embedding 缓存以实际输入和模型指纹命中，不随发布整体清空。

## 9. 接口与交互

以下均为拟新增接口，路径前缀为 `/api/v1/knowledge-bases/{kb_id}/documents/{document_id}`。

| 方法与路径 | 用途 |
| --- | --- |
| `POST /update-previews` | 从已接收快照或章节编辑生成不可变候选与差异，不抓取源站、不发布 |
| `POST /update-previews/{preview_id}/publish` | 发布已经预览的候选，携带 base_version 与幂等键 |
| `GET /update-jobs/{job_id}` | 查询阶段、错误、差异和实际处理数量 |
| `GET /versions` | 分页查看版本历史 |
| `GET /sections?version_id=...` | 查看有权限的版本章节；省略版本则读取活动版本 |
| `POST /versions/{version_id}/restore` | 从保留快照创建新候选版本并按相同协议发布 |

刷新入口属于 crawler（§3.1），不提供 RAG `/refresh` 拉取接口。crawler 仅可访问绑定采集源的写入、sync-status 及自身任务状态，不因此取得任意文档读取或人工审核权限。

预览请求示例：

```json
{
  "base_version": "ver_10",
  "operation": "replace_section",
  "section_uid": "sec_refund",
  "content": "退款申请应在购买后 14 天内提交。"
}
```

发布请求示例：

```json
{
  "base_version": "ver_10",
  "idempotency_key": "edit-refund-20261030-001"
}
```

任务结果包含 `sections_added/modified/deleted/moved`、`chunks_reused/created/removed`、`embedding_cache_hits`、`vector_readback_hits`、`embedding_inputs_computed`、`vector_records_written`，明确区分向量计算和写入成本。预览时的缓存命中是估计值，任务完成后返回实际值。

刷新与编辑复用 `documents:write`，历史与差异读取复用 `documents:read`，删除仍使用 `documents:delete`；各接口验证 KB/document/job/version 的归属。预览默认保留 24 小时，过期返回 410；基础版本变化返回 409。

管理页提供“刷新网页”“查看更新差异”“编辑章节”和“版本历史”。差异显示章节新增/修改/删除/移动、正文前后对比、预计重嵌入块数。普通远端刷新可自动发布；人工内容覆盖、异常正文骤减和 manual 切回 remote 必须通过具体候选预览发布。

## 10. 故障恢复与清理

| 故障点 | 对外行为与恢复 |
| --- | --- |
| 抓取/解析失败 | 旧版本继续服务，任务失败，可重试 |
| embedding 部分失败 | 保留已验证缓存；旧版本继续服务，重试只补缺失输入 |
| Chroma 部分写入 | staging 不可检索，按同一候选 ID upsert 补齐并验证 |
| 验证后 SQLite 提交前退出 | 活动指针未变，启动恢复重新校验候选并检查基础版本 |
| SQLite 已提交但响应丢失 | 幂等查询返回 published，不重复发布 |
| 清理失败 | 留下不可见历史记录，记录错误并重试 |
| 活动版本向量缺损 | 标记一致性故障，停止使用该损坏版本；按快照修复，不能无条件查询所有版本 |

恢复任务通过 SQLite 的活动指针判断是否已发布，不以 worker 内存或最后一条日志判断。进程重启后 processing 任务先对账，再决定恢复或失败；不得直接生成第二个候选。

默认保留最近 5 个已发布版本，且至少保留最近 7 天的已发布版本；满足任一保留条件即可保留。活动版本、任务正在使用的版本和未过期预览基础版本不得清理。staging 失败版本默认保留 24 小时。清理采用清单登记、幂等删除物理记录、删除快照、提交清单删除的可恢复步骤；embedding 缓存另按无引用与容量策略回收。

缓存“有引用”包括所有仍保留的 active/retired/staging（含尚未清理的失败候选）版本清单中的 embedding_key、运行任务及未过期预览的保留需求。容量回收只能逐出无引用项；容量不足时暂停新任务并报告可重试资源不足，或按既定保留规则先清理版本，不能删除受保护缓存。引用增删和 GC 判定通过统一锁/事务协调。缓存损坏或旧数据缺缓存时按 §6 回读公开 API，不将缓存缺失直接解释为必须重新嵌入。

资源删除、现有 CLI 全量重建必须与发布互斥。旧的直接 delete-then-add 写入入口不得与新版本协议混用；实施完成前保持维护窗口边界。备份仍整体保存 SQLite、Chroma 与快照目录。

## 11. 示例

v10 有“产品介绍”“退款规则”“联系方式”三个章节，共 12 块。退款章节占 4 块，其中一段从“7 天”改成“14 天”。

1. 完整获取网页，其他两个章节哈希不变，复用其 8 个块。
2. 重新切分退款章节，得到 4 个块；假设其中 2 块实际输入变化，则只计算 2 个向量，其余 2 个命中缓存。
3. 为 v11 写入 12 条 Chroma 记录，其中 10 条复制已有向量。
4. 验证成功，原子切换活动版本到 v11；v10 留作历史，检索过滤只允许 v11。
5. 若新版本删除“联系方式”，新清单不再包含它；即使旧物理记录暂未清理，也不会再召回。

实际变化块数由分块边界决定，上例数字是说明，不是成本保证。

## 12. 实施顺序

| 阶段 | 工作 | 完成标准 |
| --- | --- | --- |
| P1：版本底座 | schema、不可变快照、清单、向量缓存、带版本物理 ID | 首次入库与版本读取闭环，不引入旧格式读取兼容 |
| P2：检索与发布 | 活动过滤、统一读写锁、CAS、崩溃恢复、删除互斥 | 未发布/历史记录对所有检索入口不可见 |
| P3：局部处理 | 稳定章节匹配、差异、章节分块、显式向量复用 | 未变输入零 embedding，增删改移动可验证 |
| P4：网页与界面 | 采集交接、刷新任务、编辑预览、版本历史 | 网页刷新和章节编辑完整闭环 |
| P5：关联能力 | 图谱失效/重建、缓存、清理、回滚与运维说明 | 故障恢复和一致性验收通过 |

建议新增 `services/resource_updates.py`、`services/resource_diff.py`、`services/version_publication.py`、`routers/resource_updates.py`；扩展现有仓储、分块服务、RAGStore 和统一检索链。向量缓存与存储写入接口必须显式接收模型指纹和向量，防止意外自动重嵌入。

## 13. 验收计划

使用固定网页快照与 stub embedding 验证，统计每次实际 embedding 输入；Chroma 过滤与持久化恢复使用真实本地测试实例，不访问外部模型。

- crawler 推送 202 不确认成功；published/unchanged 才确认；重试、needs_review、manual 与版本冲突均不覆盖旧版本。
- 发布事务各写入点注入失败：活动指针、版本状态、文档 ready/哈希/块数、图谱 stale、内容修订号、job published 全部提交或全部回滚。
- 首次入库失败为 failed；已有活动版本刷新失败仍 ready，旧索引继续可用；活动损坏与删除不可检索。
- 单进程多线程检索/发布/删除竞争无混合版本；多 worker 或第二副本打开相同目录必须启动失败。
- 重分块含重复正文、前插块、删除块及多解 LCS 时，身份分配符合唯一对齐规则，重试 ID 不变。
- 缓存容量清理不删除保留清单引用项；缓存缺失但旧记录有效时 embedding=0，回读命中独立计数；两处损坏才重算。
- 完全未变、模板噪声变化：0 次新增 embedding 输入，无新内容版本。
- 单章节编辑：其他章节无重分块、无新增 embedding 输入。
- 开头新增章节：已有章节身份不因序号变化全部重建。
- 同名标题、重复正文、锚点冲突、章节拆分/合并：保守匹配、不串章节、不丢正文。
- 父标题改名、章节移动、长标题截断：以实际输入决定复用，来源位置同步更新。
- 删除章节与新版本块数减少：检索无旧尾部块；历史记录暂留不影响结果。
- staging 数量远多于活动记录：top-k 仍来自活动版本，验证过滤发生于召回前。
- 在每个持久化阶段注入失败并重启：旧版本保持可用，或已提交新版本可恢复，无混合版本。
- 两个任务基于同一版本提交：只有一个发布成功；重复幂等键相同请求复用任务，不同请求 409。
- 发布与检索/删除/清理并发：证据物化使用一致快照，无失效图谱来源。
- manual 模式不被定时刷新覆盖；预览提交后远端再次变化也只能发布预览中的固定快照。
- 无权限、跨知识库 ID、过期预览、回滚历史已清理等场景返回明确错误。
- 模型指纹/维数变化不复用旧向量；缓存缺失/损坏优先回读有效旧记录，仅两处均不可用才重算受影响输入。

实现后执行仓库既有测试、lint 和构建，并记录 100 页固定样本的更新耗时、embedding 输入数、Chroma 写入量、历史存储量、检索延迟及发布等待时间。性能阈值应在基线测量后制定；首期硬性标准是版本正确性与未变输入不重复嵌入。
