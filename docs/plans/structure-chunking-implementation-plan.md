# Antler RAG：结构分块实施方案

> 状态：已实施；代码与回归测试已落地，验收记录见 [structure-chunking-validation.md](structure-chunking-validation.md)。真实业务语料的模型质量评估仍需另行执行。
> 日期：2026-10-14
> 首期范围：新增可选的 `structure` 分块策略，优先支持 Markdown 与 DOCX 的标题、章节、段落结构。保留现有 `recursive` 策略及检索接口。

## 1. 目标与范围

结构分块先根据标题层级划定内容所属章节，再在章节内按完整段落组合；单个内容单元过长时继续拆分。每个切片携带标题路径和来源位置，向量化文本包含标题上下文。

首期交付：

- 知识库创建时可选择 `recursive` 或 `structure`，配置持久化并在页面中展示。
- Markdown 识别标题层级、段落、围栏代码、列表和常见管道表格。
- DOCX 识别明确的标题样式、段落和表格，保持正文中的原始排列顺序。
- TXT 使用段落边界；PDF 使用页边界和提取文本中的段落边界，明确标记能力限制。
- 切片详情、向量检索、问答来源传递结构元数据。
- 上传和现有重建入口使用同一分块规则，重建时清理旧向量与图谱引用。

首期不实现 `semantic`、`hybrid`、OCR、PDF 版面标题推断、HTML 入库、父子块检索、后台任务队列或在线无停机索引切换。DOCX 的文本框、页眉页脚和复杂自动编号还原不在首期承诺中。

## 2. 当前实现模块

| 环节 | 行为 | 文件 |
| --- | --- | --- |
| 文档解析 | Markdown/DOCX 结构解析，TXT 段落与 PDF 真实页号；DOCX 提取保持原始 body 顺序 | `utils/documents.py` |
| 分块 | recursive 与 structure 两个纯函数，标题前缀计入字符预算 | `rag/chunking.py` |
| 配置 | 创建时持久化策略、块大小和重叠，创建后固定 | `models/schemas.py`、`db/repository.py` |
| 数据库 | 空库直接初始化当前 schema，非空库必须匹配当前结构；无版本迁移 | `db/schema.sql`、`db/schema.py`、`db/repository.py` |
| 索引 | 公共服务负责预检、状态、图清理、源文件所有权与补偿 | `services/document_indexing.py` |
| 存储 | 仅 `index_drafts()` 写入，读取当前格式元数据 | `rag/store.py` |
| 运维 | 全量 embedding 重建与只读预检，只支持当前数据库结构 | `reindex_embeddings.py` |
| UI | 实际策略/字符预算，切片分页与来源结构字段 | 知识库页、切片弹窗、检索页 |

本方案已按最新要求移除版本升级与向下兼容。旧数据目录需保留原副本，在新的当前 schema 数据目录中重新上传源文件。

## 3. 配置与当前接口

### 3.1 知识库配置

新增 `chunk_strategy: Literal["recursive", "structure"] = "recursive"`。

```json
{
  "name": "员工制度",
  "description": "公司制度知识库",
  "chunk_strategy": "structure",
  "chunk_size": 900,
  "chunk_overlap": 150
}
```

`chunk_size` 范围继续为 100～4000 字符，`chunk_overlap` 范围继续为 0～1000，并校验 `chunk_overlap < chunk_size`。API 与 UI 默认均保持 `recursive`，用户显式选择 `structure`。

首期分块配置在创建后固定，现有 PATCH 仍只更新名称和描述；不能只修改策略字段而让已有切片继续使用旧策略。已有知识库迁移到 `structure` 的首期操作方式是新建结构策略知识库并重新上传原文件，验证完成后再处理旧知识库。原地切换策略及批量迁移 UI 留待后续方案。

### 3.2 当前接口

- `recursive` 与 `structure` 均为可用策略；默认 `recursive` 是产品配置，不是旧版本适配分支。
- 索引写入只使用 `RAGStore.index_drafts()`，HTTP 上传与重建统一使用 `DocumentIndexingService`。
- 不提供旧 `index(text=...)`、旧模块导入转发或 `/chat` 的 `query` 别名。
- 所有索引记录必须包含 `chunk_strategy`、`chunker_version` 和 `heading_path_json`；读取不为旧格式补默认值。
- 来源位置不可确定时仍为空，例如 recursive 没有页号/行号，DOCX 不伪造页码。
- chunk ID 为 `{document_id}:{chunk_index}`，按原文顺序从 0 编号。
- 检索保留过滤、阈值、rerank、Top-K 和 `{results}` / `{answer, sources}` 包装。

## 4. 处理流程与模块边界

```text
上传文件 / 原始文件重建
  -> DocumentIndexingService：读取知识库配置，管理状态与清理
      -> recursive：extract_text() -> 原递归分块
      -> structure：parse_document() -> DocumentElement 序列
                   -> 标题栈与章节归属
                   -> 章节内组合 / 拆分 -> ChunkDraft 序列
  -> RAGStore：给切片分配 ID，写入正文、metadata 和向量
  -> 完成索引，文档与图状态提交
```

### 4.1 分块与写入接口

使用 `index_drafts()` 作为唯一存储写入接口，分块由独立纯函数完成：

```python
# rag/chunking.py：纯分块函数
def chunk_recursive(
    text: str, *, chunk_size: int, chunk_overlap: int
) -> list[ChunkDraft]: ...

def chunk_structure(
    document: ParsedDocument, *, chunk_size: int, chunk_overlap: int
) -> list[ChunkDraft]: ...

# RAGStore：两种策略共用的实际写入接口
def index_drafts(
    self, *, knowledge_base_id: str, document_id: str, filename: str,
    drafts: Sequence[ChunkDraft], digest: str,
    chunk_strategy: Literal["recursive", "structure"]
) -> int: ...
```

- `DocumentIndexingService` 在准备阶段按知识库策略分派：recursive 调用 `extract_text()` 和 `chunk_recursive()`；structure 调用 `parse_document()` 和 `chunk_structure()`。两者均先得到 drafts，再进入删除旧索引和写入阶段，避免破坏性操作后才发现解析失败。
- 服务的写入阶段统一调用 `index_drafts()`，不会对预检过的文本再次分块。策略由知识库配置决定，版本由存储端当前常量映射写入，不接受外部版本字符串。
- `index_drafts()` 只校验非空切片、分配 ID、序列化 metadata 并调用 Chroma；不识别标题、不重新分块、不删除旧记录，也不修改 SQLite 或图谱。删除、重试和失败补偿由服务承担。
- HTTP 上传和重建必须使用服务，不能绕过其生命周期管理。

### 4.2 内部类型

新增以下内部类型，首期不对外暴露 Python 类型：

```text
DocumentElement
  kind: heading | paragraph | list | table | code
  text: 保留有效内容及代码内部空白
  heading_level: 可空
  position: 文档内元素序号
  page_number: 可空，仅确实来自 PDF 时设置
  line_start / line_end: 可空，仅文本类文档可确定时设置

ParsedDocument
  elements: 有序 DocumentElement 序列
  structure_quality: headings | paragraphs | page_text

ChunkDraft
  content: 实际用于 embedding、检索和问答的文本
  heading_path: 完整标题层级，recursive 为 []
  structure_quality: headings | paragraphs | page_text，可空，recursive 为 None
  section_id: 可空，structure 使用文档内章节序号，例如 s000003
  element_start / element_end: 可空，structure 正文覆盖的元素区间
  page_start / page_end: 可空
  line_start / line_end: 可空
  split_reason: section | size | oversized_element，可空，recursive 为 None
```

解析器与分块器保持纯函数，不访问数据库、不调用 embedding 或 LLM。服务负责业务状态，RAGStore 负责 Chroma 存取。GraphBuildService 继续读取索引中的实际切片，不自行重新解析或分块。

## 5. 各文档格式的解析规则

| 格式 | 首期结构能力 | 规则和限制 |
| --- | --- | --- |
| `.md` / `.markdown` | 标题、段落、代码、列表、常见表格 | 支持 ATX `#`～`######` 和 Setext 一级/二级标题；标题识别避开围栏代码与缩进代码；支持反引号和波浪号围栏。原始 HTML 块按普通内容保存，不解释其标题 |
| `.docx` | 明确的标题层级、段落、列表项、表格 | 遍历文档 body 中段落和表格的实际顺序；读取 Heading 1～9 及可确定的样式 outline level；不凭字号或加粗猜测标题。自动编号保留可取得的文本与列表边界，复杂编号展示值还原不在首期范围 |
| `.txt` | 段落 | 空行分段；不默认把短句、“一、”或“第一章”识别为标题，避免把正文误判为章节 |
| `.pdf` | 页与可提取的段落 | 记录真实页号，单页文本按空行分段；页边界是首期处理边界，不宣称是章节。无标题路径，不通过字体/位置推断标题；没有可提取文本时继续返回 invalid_document |

Markdown 首期采用受限的块级解析：顺序识别代码块、标题、表格、列表、普通段落，明确测试支持范围；不宣称实现完整 CommonMark/GFM。沿用现有依赖，避免为本轮引入新解析平台。未识别的非空内容保留为普通正文，不能静默丢弃。

DOCX 表格按行序列化，每行按单元格顺序输出；合并单元格可去除相邻重复文本，但不能删除不同单元格的有效内容。DOCX 页码依赖排版，首期不得根据段落编号伪造页码。

## 6. 分块算法与边界

### 6.1 标题和章节

1. 按元素顺序扫描，维护 `(level, title)` 标题栈。
2. 遇到新标题时先输出当前正文块，再弹出级别大于或等于新标题的栈项，并加入新标题。
3. 所有标题都产生章节边界，正文属于其当前完整标题路径。同名标题用不同 `section_id` 区分；标题跳级不补造标题。
4. 父标题下的导言单独属于父章节，不与子章节正文合并；文档开头没有标题的导言使用空标题路径。
5. 连续标题不产生空正文切片，但其层级保留给后续正文；整个文档只有标题、没有正文时返回明确的 invalid_document。
6. 标题路径写入每个正文切片的文本前缀，避免只有 metadata 而 embedding 缺失章节上下文。

**硬约束：一个切片不包含两个不同 `section_id` 的正文；重叠也不跨章节。** PDF 首期另以页边界结束当前块，不跨页重叠。

### 6.2 长度预算

- `chunk_size` 限制最终 `content` 长度，包含标题前缀、分隔符和正文。
- 标题显示前缀最多占总预算的 25%；过长时保留路径尾部并用省略标记表示截断，完整路径仍保存在 metadata。标题中的换行规范化为单个空格。
- 计算正文可用预算后再合并段落，不能先生成达到上限的正文、最后追加标题而导致超长。
- 同章节相邻段落在预算允许时合并，段落之间保留空行；短章节不为了凑长度跨章节合并。

### 6.3 超长内容和重叠

| 内容单元 | 首期处理 |
| --- | --- |
| 普通段落 | 超长时优先按中文/英文句末边界拆分，仍超长再按字符拆分；不删除有效字符 |
| 列表 | 优先在列表项之间拆分；单项超长按段落规则处理，保留可取得的项目符号和缩进 |
| Markdown / DOCX 表格 | 能放下时整表保留；超长时优先按行切分，存在明确表头时重复表头，并将重复部分计入长度；不得猜测 DOCX 第一行一定是表头 |
| 表头加单行仍超长 | 保留内容并按字符兜底，标记 oversized_element；此时不承诺切片保持完整表格格式 |
| 代码块 | 能放下时整块保留；超长时按行切分，必要时按字符兜底；重复围栏和语言标记也计入预算，保留内部空白 |

重叠主要用于同章节长正文的连续切片。优先复制上块末尾的完整句子或段落，重叠长度不超过 `chunk_overlap`；没有合适的完整单元时允许实际重叠为 0。表格与代码的连续切片不叠加通用正文重叠。

正文预算小于配置重叠时，再把实际重叠限制为正文预算的一半，确保每个新块都包含新内容。循环必须持续推进源位置，不能因重叠、长标题或超长单元产生空块或无限循环。

### 6.4 示例

```markdown
# 员工手册
## 请假制度
### 年假
员工连续工作满一年后，可以申请年假。

年假申请需要提前三个工作日提交。
### 病假
申请病假需要提供相关证明。
```

正文长度允许时输出两个切片：

| 切片 | 标题路径 | 正文 |
| --- | --- | --- |
| 0 | 员工手册 → 请假制度 → 年假 | 年假的两个段落 |
| 1 | 员工手册 → 请假制度 → 病假 | 病假证明要求 |

切片 0 的实际索引文本为：

```text
员工手册 > 请假制度 > 年假

员工连续工作满一年后，可以申请年假。

年假申请需要提前三个工作日提交。
```

## 7. 元数据、API 和 UI

Chroma 保留原 `knowledge_base_id`、`document_id`、`filename`、`sha256`、`chunk_index`。两种策略的新写入均包含 `chunk_strategy` 和 `chunker_version`，其余结构字段仅在确实可确定时写入：

```text
chunk_strategy        recursive | structure
chunker_version       recursive-v1 | structure-v1
structure_quality     headings | paragraphs | page_text
heading_path_json     JSON 字符串，例如 ["员工手册", "请假制度", "年假"]
section_id            s000003
element_start/end     正文元素位置
page_start/end        仅有可靠页号时写入
line_start/end        仅有可靠文本行号时写入
split_reason          section | size | oversized_element
```

标题路径在 Chroma 中序列化为 JSON 字符串，API 解码为 `heading_path: list[str]`；未知页码/行号不写入 Chroma metadata，响应使用 `null`。元素位置指解析后的正文位置，不能被展示成原文件字节偏移。

recursive 新写入明确记录 `chunk_strategy="recursive"`、`chunker_version="recursive-v1"`、`heading_path_json="[]"`，不写 structure_quality、section_id、元素位置、页码/行号或 split_reason。没有调用结构解析器就不能宣称恢复了结构；metadata 增量不会改变原 chunk 文本和编号。structure 新写入记录 `chunk_strategy="structure"`、`chunker_version="structure-v1"` 和实际可取得的结构字段。

结构元数据要经过 `IndexedChunk`、`RetrievedChunk`、`Evidence.from_vector()`、`chunk_payload()` 完整传递，并更新返回类型，不能只改 Chroma 写入。读取要求当前策略/分块器/标题路径字段，缺失或格式不符直接拒绝；不可确定的来源位置仍为空，不能由知识库配置推测解析能力。

新增 `GET /api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}/chunks?offset=0&limit=100`，返回 `{items: [...], total: N}`，保留原文档详情响应。`offset >= 0`，`limit` 范围 1～100。复用 `documents:read` scope / 已授权工作区角色，校验活动知识库和文档归属；文档非 ready 时返回空列表。读取 Chroma 实际记录、按 chunk_index 排序并分页，不重新分块，也不读取 Chroma 私有存储。首期可复用 `document_chunks()` 后分页；该方式仍会加载单文档全部记录，大文件的底层读取优化另行处理。

知识库页新增策略、块大小和重叠配置；策略说明使用“按标题、章节和段落分块”。卡片和详情显示实际配置，移除固定 token 数和固定策略文案。切片弹窗显示标题路径、可用页码和解析能力；PDF 显示“按页/段落”，不显示“已识别章节”。检索来源使用同样的结构字段辅助定位。

切片弹窗改为调用上述专用端点并支持翻页，编号使用实际 chunk_index；关键词搜索仅作用于当前页并明确标注范围，不假装对尚未加载的切片进行全文搜索。

## 8. 当前 SQLite schema

`db/schema.sql` 直接定义当前全局工作区、文档与图谱的全部表和索引，知识库包含 `chunk_strategy`，其 CHECK 约束只允许 `recursive` 与 `structure`。

`Database.initialize()` 在空库中通过一个 `BEGIN IMMEDIATE` 事务逐条创建 schema，验证结构与外键后提交，失败回滚。非空库只校验所需当前表和列名，不要求物理列顺序一致，不拒绝无关附加表；不做 ALTER、复制、版本判断或自动升级。不创建 `schema_migrations`，也不包含旧工作区转换命令。

不符合当前结构的数据目录不会自动重置或转换。保留旧目录和完整备份，在新数据目录中初始化并重新上传源文件。

## 9. 索引重建与图谱一致性

### 9.1 首期操作边界

上传与全量 embedding 重建接入公共服务，逐知识库读取持久化策略。structure 重建从原文件重新解析，不能再次切分历史切片。

全量重建要求停用 HTTP 服务及其他写入者、备份完整数据目录并在单进程中执行。`--confirm` 删除整个活动 collection，不是单知识库命令；不承诺在线替换或跨 SQLite/Chroma 原子切换。

`--dry-run` 与 `--confirm` 互斥。预检只读取当前 schema、知识库配置和原文件，校验 SHA256、解析并报告预期块数量/失败原因。不创建 RAGStore、不初始化 Chroma、不调用 embedding、不修改状态。使用 SQLite `mode=ro`，缺库或不匹配当前 schema 时直接退出，不复用会设置 WAL/创建目录的 `Database.connection()`。不检查或转换数据库历史版本。

CLI 保留外部 embedding 配置要求；普通上传仍支持 Chroma 默认 embedding。正式执行重新预检全部文件和配置，过去的 dry-run 不能作为本次检查结果。

操作顺序：停写与完整备份，确认数据库符合当前 schema，运行 `--dry-run`，修复预检失败，再运行 `--confirm`；完成文档状态与图谱检查后恢复服务。旧格式数据库需使用新数据目录重新入库。

### 9.2 成功、失败与图清理

1. 尽可能在删除旧索引前完成文件存在性校验、解析和切片生成，失败时保留现有数据；全量 collection 重建在删除前预检全部目标文件。
2. 进入替换阶段后，标记文档 indexing；先调用 `GraphStore.cleanup_document()` 清理旧 mentions 和孤儿关系/实体，使旧 chunk 引用不可查询。
3. 删除该文档所有旧 Chroma 切片，再写入新切片。不能直接 add/upsert 相同 ID：新块数减少时会留下旧尾部记录。
4. 向量写入成功后，在同一个 SQLite 事务中提交文档 ready、chunk_count 与图状态 not_built。由 `DocumentIndexingService` 打开并持有连接，调用 §9.3 定义的两个 `_in_tx` helper，全部成功后提交；不能调用现有两个各自打开连接的方法来模拟单事务。
5. 写入失败时清理该文档可能已写入的部分切片，文档标 failed、图谱保持不可查询；清理失败保留可重试错误信息。服务端源文件按 §9.4 的操作类型与所有权处理：首次上传失败仍删除本请求新建副本；重建/已有源文件替换失败保留已有副本。
6. 索引重建成功后，图谱只能由现有管理员 rebuild 流程重新生成。SHA256 不变也必须执行图清理，因为切片边界可能已改变。

全量重建开始时，要把所有将受 collection 删除影响的文档从 ready 转入 indexing 并使其图状态失效；中断后未完成文档不得继续显示 ready。首次处理后续文档时再逐一清理旧 provenance。若需要恢复旧索引，使用与旧镜像匹配的完整数据备份；首期不做逐文档自动回滚。

当前向量查询主要依赖 Chroma 的 KB/document 过滤，不能假设只修改 SQLite 文档状态就能屏蔽残留向量。因此 destructive CLI 在服务停止时运行；上传失败路径必须实际清理部分写入的 Chroma 记录。维护窗口内若有清理失败，完成修复或恢复备份后才恢复服务。

### 9.3 SQLite 连接与事务所有权

新增以下接口，`conn` 类型明确为 `sqlite3.Connection`：

```python
Database.set_document_ready_in_tx(
    conn, *, knowledge_base_id, document_id, chunk_count, expected_sha256
) -> None

GraphStore.mark_not_built_in_tx(
    conn, *, knowledge_base_id, document_id, source_sha256
) -> None
```

服务通过 `with database.connection() as conn` 取得唯一连接，执行 `BEGIN IMMEDIATE`；先调用 `set_document_ready_in_tx()`，再调用 `mark_not_built_in_tx()`，最后 `conn.commit()`，任一失败均由服务 `conn.rollback()`。helper 不打开新连接，不 BEGIN、不提交/回滚、不关闭调用方连接。

文档 helper 条件更新必须检查 KB/document 归属、`status='indexing'` 和预期 SHA256，更新行数必须等于 1，否则抛错并回滚。图 helper 在同一连接中校验文档为 ready、SHA256 与 source_sha256 一致，再执行状态 upsert。先更新的 ready 对其他连接在提交前不可见，但本事务中的图 helper 可以读取它。

现有 `GraphStore.mark_not_built()` 保留独立调用契约：自行开连接/事务，委托 `mark_not_built_in_tx()` 后提交或回滚。公共索引服务使用外部连接 helper；`Database.set_document_status()` 保留其他场景用途，不用于这次成功事务。事务失败后的 Chroma 清理与 failed 状态更新是后续补偿操作，不冒充跨存储原子回滚。

### 9.4 源文件所有权与失败清理

这里的“原文件”指服务器 uploads 中的源副本，不是用户设备上的文件。首期不将所有上传失败改成保留副本，具体约定如下：

| 操作 | 失败后的文件处理 |
| --- | --- |
| 首次 HTTP 上传 | 保留当前行为：清理部分向量、标记 failed，删除本请求新建的服务端副本；删除失败记录清理错误，不能误报清理成功 |
| CLI 重建或对已有源副本重新索引 | 保留原路径与文件，便于维护重试；不适用上传请求的 unlink 分支 |
| failed/deleted 记录同 SHA 重传 | 只允许删除本请求新建且未被成功索引使用的副本；不能因为复用了 document ID 就删除此前已有的副本 |

服务保存 `operation`（upload/rebuild）、`created_source_in_this_attempt` 和操作前的记录/源路径快照，按文件所有权清理。不能仅依据文档状态或 document ID 判断某路径能否删除。

同 SHA 重传目前会复用记录并覆盖 stored_filename，因此要同时处理记录引用：失败前若存在旧源副本，保留它并恢复文档对旧 stored_filename 的引用，状态仍为 failed；若原来没有源文件，只清理本次副本，允许 failed 记录没有可重建源文件。成功后记录指向新副本，再清理旧的无引用副本；清理失败记录明确错误并允许维护重试，不撤销已成功索引。合法路径复用时 `created_source_in_this_attempt=false`，失败不得 unlink。

异常清理不能删除当前记录仍需要的既有源文件。保留的失败源副本由后续重建/重传重试复用，或由既有文档删除流程清理；不引入自动按 failed 状态删除源文件的任务。

## 10. 文件改动清单

当前实现文件：

| 文件 | 改动 |
| --- | --- |
| `utils/documents.py` | 文本提取与结构化解析，DOCX 始终保持正文原顺序 |
| `rag/chunking.py`（新增） | 标题栈、章节边界、预算、段落组合和超长单元拆分 |
| `services/document_indexing.py`（新增） | 按策略准备 drafts 后统一调用 index_drafts；持有成功事务连接；记录源文件所有权和旧记录快照，管理清理/失败补偿 |
| `rag/store.py` | 仅保留 index_drafts 写入接口；两种策略新写入均记录策略/版本，读回结构 metadata |
| `models/schemas.py` | 创建知识库策略枚举与默认值 |
| `db/schema.sql`、`db/schema.py`、`db/repository.py` | 当前 schema 初始化、策略持久化；新增 set_document_ready_in_tx(conn, ...) 及重传失败的源引用恢复 |
| `routers/knowledge_bases.py` | 创建时传入策略，返回实际配置 |
| `routers/documents.py` | 上传调用公共索引服务，新增带权限校验和分页的切片读取端点 |
| `rag/graph_store.py` | 新增 mark_not_built_in_tx(conn, ...)；现有 mark_not_built 自持事务并委托 helper；重建清理旧 provenance |
| `rag/retrieval.py`、`utils/security.py` | 当前索引来源结构字段透传 |
| `reindex_embeddings.py` | 使用公共流程，读取每库策略，全量重建预检与状态管理；embedding CLI 增加 dry-run |
| `KnowledgeBasesPage.vue` | 创建表单和真实策略/字符配置显示 |
| `ChunkViewerModal.vue`、`RetrievalPage.vue` | 标题路径、来源位置和解析能力显示 |
| `README.md`、运维说明 | 策略能力、字符单位、重新上传与重建说明 |

## 11. 实施顺序

1. **锁定当前行为**：保存 recursive 与 structure 样例，包括 Markdown、DOCX 正文顺序与结构边界。
2. **实现解析与纯分块模块**：先完成 Markdown，再完成 DOCX，最后补 TXT/PDF 能力标记；验证内容覆盖、顺序和长度。
3. **接入配置与数据链路**：完成当前 schema 初始化、API 策略、Chroma metadata 和来源透传。
4. **贯通生命周期**：上传与重建共用服务，补失败清理、全量中断状态和图谱引用失效。
5. **接入管理界面**：增加选择和配置，展示真实切片结构，修正字符/token 文案。
6. **运行回归与真实样例验收**：先验证边界和数据一致性，再比较真实问答召回；不预先承诺检索指标提升。

## 12. 验收与测试

### 功能验收

- 年假和病假示例生成不同章节的切片，每块包含正确标题路径。
- 父章节导言、标题跳级、同名标题、连续标题均有确定行为；代码中的 `#` 不成为标题。
- DOCX 段落—表格—段落顺序与文档一致，已知标题样式被识别。
- 无标题文档仍可按段落入库；TXT/PDF 不被标记为已恢复标题层级。
- 任何 chunk 最终长度不超过 chunk_size；长标题、超长句子、表头和代码围栏均计入预算。
- 重叠不跨章节；长单元拆分覆盖所有有效内容且持续推进；允许重复标题、重叠句和表头，但不能丢失有效正文。
- API 默认策略为 recursive；所有已索引切片必须使用当前元数据格式。
- 两种分块函数生成的 drafts 均经 index_drafts 原样写入；不再提供旧 index(text=...) 入口。
- recursive 新切片包含 recursive/recursive-v1 标识且没有虚构结构字段；structure 新切片包含 structure/structure-v1 标识；缺失必需标识时直接拒绝读取。
- UI 展示持久化配置与实际元数据，页码仅在可靠时出现。
- 切片读取端点正确分页，并拒绝跨知识库文档访问和缺少 documents:read 的 API Key；文档详情只返回文档信息，切片使用专用端点。

### 一致性与回归

- 空库直接初始化当前 schema，重复启动不重复创建；创建失败可回滚，不匹配当前结构时拒绝启动。
- 重建后 chunk 数减少时不存在旧尾部记录；相同 SHA256 重建也清理旧 graph mentions。
- 解析失败、部分 embedding 成功后失败、Chroma 清理失败分别有明确状态和重试路径。
- 图状态只在索引成功后进入 not_built；旧图引用在替换开始时失效。
- 图状态 upsert 注入异常时，同一连接中的文档 ready 更新随事务回滚；两个 helper 不获取第二条连接或自行提交。
- 首次上传失败只删除本请求副本，重建失败保留原文件；同 SHA 重传失败恢复旧源引用且不误删旧文件，成功后清理无引用副本。
- 原 recursive 分块、检索过滤、rerank 与 API 认证权限回归通过。
- CLI dry-run/预检不删除 collection、不修改文档或图状态；确认执行后的中断不会把未完成文档保留为 ready。
- dry-run 校验当前 schema，不匹配时只读拒绝；只读路径不执行 initialize、建库或 WAL 配置。

建议新增 `test_structure_chunking.py`、结构化 Markdown/DOCX/PDF 合成 fixture 和文档索引服务集成测试；扩充现有 `test_documents.py`、`test_repository.py`、`test_embeddings.py`、`test_graph_store.py`、`test_api_contract.py`。测试使用 stub embedding，不访问真实上游服务。

实现完成后执行项目既有 `just test`、`just lint` 和 `just build`。使用一组固定问题比较 recursive 与 structure 的证据召回及上下文完整性，记录块数量、长度分布和入库耗时；结构边界正确是首期硬性标准，质量比较结果据实报告。

## 13. 后续扩展

`DocumentElement` 和 `ChunkDraft` 为未来章节内语义分块提供输入，但首期 API 枚举不预留不可用的 semantic/hybrid 选项。后续可独立增加 PDF 版面分析、复杂 DOCX 编号恢复、父章节上下文扩展及有检查点的知识库原地策略迁移。
