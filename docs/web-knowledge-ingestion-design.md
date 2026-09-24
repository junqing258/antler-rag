# 网页知识采集入库实施文档（支持客户端渲染）

> 状态：设计稿，尚未集成到 Antler Knowledge。  
> 目标：将一个受控网站中的可检索正文采集、清洗、版本化并写入知识库；必须能够处理 React、Vue、Angular 等客户端渲染（CSR）页面。

## 1. 范围与原则

本方案面向产品文档、帮助中心、内部 Wiki 等已获授权的站点。它不是通用网页镜像器，也不试图绕过登录、验证码、付费墙、反爬策略或访问控制。

首期能力：

- 从用户提供的种子 URL 开始，限制在显式允许的域名和路径范围内发现页面；
- 对静态 HTML 优先使用轻量抓取；检测到需要 JavaScript 时，在受控浏览器中渲染后再提取；
- 提取主正文、标题、层级标题、规范 URL、更新时间与链接关系，转换为带来源信息的 Markdown；
- 按内容哈希增量更新，删除或下线过期页面，避免重复向量；
- 将页面以“一个可追溯文档”的形式交给现有或任意兼容知识库的文本入库接口；
- 提供任务、页面和失败原因的可观测状态。

非目标：全网爬取、私有站点自动登录、执行任意页面动作、下载不受限二进制文件、抓取搜索结果页/用户生成内容、绕过 `robots.txt` 或网站条款。

## 2. 推荐架构

将采集器与知识库解耦为两个服务。采集器只负责取得可信的、已规范化的文本及其来源；知识库继续负责分块、嵌入和检索。这样可以独立扩缩容浏览器 worker，且网页解析失败不会影响检索服务。

```text
创建采集源 / 手动触发
          |
          v
Crawler API ----> 任务库 / 调度器 ----> URL frontier
                                            |
                         +------------------+------------------+
                         |                                     |
                         v                                     v
                   HTTP fetcher                         Browser worker
                 （静态页优先）                    （Playwright Chromium）
                         |                                     |
                         +---------------+---------------------+
                                         v
                  URL 规范化 -> 正文提取 -> 清洗/去重 -> Markdown 文档
                                                           |
                                                           v
                                          Ingestion adapter / Outbox
                                                           |
                                                           v
                               知识库文档 API -> 分块 -> Embedding -> Vector DB
```

### 2.1 为什么不能只用 `requests`/`httpx`

CSR 应用的首个 HTML 往往只有根节点和脚本标签；正文在 JavaScript 请求 API、执行路由逻辑和渲染 DOM 后才出现。浏览器 worker 必须加载页面、等待确定的业务就绪条件、读取已渲染 DOM；不能用“固定 sleep 5 秒”代替就绪条件。

### 2.2 推荐技术选型

| 层 | 推荐 | 责任 |
| --- | --- | --- |
| API 与控制面 | FastAPI + SQLite/PostgreSQL | 数据源、任务、页面状态、审计 |
| 调度 | 单进程可用 APScheduler；生产用队列 + worker | 周期运行、重试、并发控制 |
| 静态抓取 | `httpx` | 重定向、条件请求、HTML 获取 |
| 浏览器渲染 | Playwright Python + Chromium | CSR/SSR 混合页的 DOM 渲染和网络拦截 |
| 正文提取 | Trafilatura、Mozilla Readability 或站点专用 CSS 规则 | 去除导航、页脚、广告和脚本 |
| HTML 清洗 | BeautifulSoup/lxml + Markdown 转换器 | 链接、图片、表格、代码块规范化 |
| 状态存储 | PostgreSQL（推荐） | 多 worker 锁、任务与版本记录 |
| 传输 | HTTP 文档 API 或对象存储 + 入库事件 | 与知识库实现解耦 |

若部署规模很小，FastAPI、SQLite 和一个受限的 worker 也可以运行；但 SQLite 不适合多个 crawler worker 同时领取任务。Antler Knowledge 当前也明确是单写入进程，因此首期集成应只运行一个入库 worker，或将采集器部署在其外部并串行调用文档 API。

## 3. 数据模型与状态机

所有时间使用 UTC；URL、内容和请求错误中不得记录 cookie、Authorization 头或 query string 中的敏感值。

```text
crawl_sources
  id, knowledge_base_id, name, seed_urls_json, allowed_hosts_json,
  allowed_path_prefixes_json, extraction_rules_json, schedule,
  max_pages, max_depth, render_mode, enabled, created_at, updated_at

crawl_runs
  id, source_id, trigger(manual|schedule), status,
  discovered_count, fetched_count, indexed_count, unchanged_count,
  failed_count, started_at, finished_at, error_code

crawl_pages
  id, source_id, canonical_url (unique per source), document_id,
  last_content_sha256, etag, last_modified, last_success_at,
  index_status, missing_runs, title, language, updated_at

crawl_attempts
  id, run_id, page_id, requested_url, final_url, fetch_mode,
  http_status, render_ms, extraction_ms, outcome, error_code,
  error_detail_safe, created_at
```

页面状态流转：

```text
queued -> fetching -> extracted -> indexing -> indexed
                 |        |             |
                 v        v             v
              retryable  skipped       failed
                 |
                 v
               queued

indexed --连续 N 次未被发现--> stale -> deleted（删除知识库对应文档）
```

`index_status` 不是爬虫成功与否的替代品：只有知识库确认写入成功后才能标记 `indexed`。写入失败时保留已提取的哈希，以便安全重试，但不能把页面视为已更新。

## 4. URL 边界、发现与去重

### 4.1 创建数据源时的必填限制

- `seed_urls`：一至多个 HTTPS 起始地址；
- `allowed_hosts`：精确主机名列表，不接受 `*.example.com` 这样的宽泛通配；
- `allowed_path_prefixes`：例如 `/docs/`；
- `max_pages`、`max_depth`、每主机并发、每秒请求数与单页超时；
- `render_mode`：`auto`、`always` 或 `never`；
- 是否尊重 `robots.txt`（默认且必须为 `true`）以及采集已获授权的确认记录。

拒绝 `file:`、`data:`、`javascript:`、`ftp:`、非 HTTP(S) URL；阻断解析到 loopback、link-local、RFC1918 私网和云元数据 IP 的 DNS 结果，以防 SSRF。每一次重定向后都要重新校验 scheme、主机、路径和解析 IP，最多允许 5 次重定向。

### 4.2 规范 URL

按以下顺序规范化，产出的 `canonical_url` 才能作为页面的幂等键：

1. 小写 scheme/host，移除默认端口与 fragment；
2. 解析相对链接，移除 `utm_*`、`gclid`、`fbclid` 等明确的跟踪参数；保留其他可能改变内容的 query 参数；
3. 采用页面 `<link rel="canonical">` 前，验证其仍在允许范围内；
4. 不将带不同有意义 query 的 URL 合并；必要时为某数据源设置 query 参数 allowlist；
5. 发现链接时只加入同源、允许路径、未超过深度且未见过的规范 URL。

不要仅靠 URL 去重。最终用正文的 `content_sha256` 去重：不同 URL 相同内容可创建别名/重定向记录，只索引一个主文档。

## 5. 抓取与 CSR 渲染

### 5.1 双通道策略

`auto` 模式先做一次普通 HTTP 获取，满足以下任一条件才升级到浏览器：正文提取结果低于最小字符数（建议 300）；HTML 中存在常见 SPA 根节点且可读正文不足；或站点规则要求浏览器。

```python
async def fetch_page(url: str, source: CrawlSource) -> FetchedPage:
    response = await http_fetch(url, timeout=20, max_redirects=5)
    static_text = extract_main_text(response.html)
    needs_browser = (
        source.render_mode == "always"
        or (source.render_mode == "auto" and len(static_text.strip()) < 300)
    )
    if source.render_mode == "never" or not needs_browser:
        return FetchedPage.from_http(response, static_text)
    return await render_with_browser(response.url, source)
```

HTTP 请求带明确 `User-Agent` 和可联系的站点 URL，遵守每主机的 token bucket 限速。支持 `If-None-Match`/`If-Modified-Since`；`304 Not Modified` 直接记为 `unchanged`，不启动浏览器。

### 5.2 浏览器 worker 的约束

浏览器上下文必须无持久 cookie、无用户凭据、无扩展。每个页面新建 context 或在严格清理后复用 context；禁止下载、弹窗、新开窗口和地理位置/通知权限。请求拦截仅允许文档、样式、脚本、字体与必要的 XHR/fetch；图片、视频、音频、广告/统计域名可中止，以降低成本。

不要使用 `networkidle` 作为唯一完成条件：长轮询、分析脚本和 websocket 会让它永远不稳定。优先级如下：

1. 每站点的 `wait_for_selector`（如 `main article` 或 `.docs-content`）；
2. 通用 `main, article, [role="main"]` 出现且可见；
3. `domcontentloaded` 后在一个短窗口内监测正文文本长度连续稳定；
4. 全局 deadline 到期后，以已得到的 DOM 尝试提取，并记录 `render_timeout_partial`。

```python
async def render_with_browser(url: str, source: CrawlSource) -> FetchedPage:
    context = await browser.new_context(
        user_agent=CRAWLER_UA,
        java_script_enabled=True,
        accept_downloads=False,
        service_workers="block",
    )
    page = await context.new_page()
    await page.route("**/*", allow_only_required_resource_types)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        selector = source.content_selector or "main, article, [role='main']"
        await page.locator(selector).first.wait_for(state="visible", timeout=8_000)
        await wait_until_text_stable(page, selector, samples=3, interval_ms=400)
        html = await page.content()
        return FetchedPage(url=page.url, html=html, mode="browser")
    finally:
        await context.close()
```

`allow_only_required_resource_types` 还须对每个请求 URL 执行与第 4 节相同的 allowlist 和 IP 校验。页面 JavaScript 是不可信输入：不注入采集源提供的 JavaScript，不点击“加载更多”、登录或提交按钮，不执行页面建议的任何操作。

### 5.3 站点专用规则

通用正文提取应有 fallback，但高价值站点应允许管理员配置、版本化审核后的规则，例如：

```json
{
  "content_selector": "main .theme-doc-markdown",
  "remove_selectors": ["nav", ".pagination-nav", ".feedback", "script", "style"],
  "title_selector": "main h1",
  "wait_selector": "main .theme-doc-markdown",
  "include_url_pattern": "^https://docs\\.example\\.com/guide/"
}
```

规则是配置数据，不允许其中包含 JavaScript、正则替换代码或任意 shell 命令。CSS selector、正则表达式长度和运行时间都应受限，防止 ReDoS。

## 6. 内容提取、清洗与文档形态

提取顺序为：站点 `content_selector` → `main/article/[role=main]` → Readability/Trafilatura。若正文不足最小阈值或提取器置信度过低，标记为 `skipped:no_extractable_content`，不要索引导航页或空壳页面。

清洗规则：

- 删除 `script`、`style`、`noscript`、导航、页脚、cookie banner、推荐阅读和重复面包屑；
- 保留标题层级、段落、列表、表格、引用、代码块与代码语言；
- 将相对链接转为绝对链接；图片只保留 alt 文本和 URL，不 OCR 或下载，除非另立图像管线；
- 归一化空白但不破坏代码块；过滤不可见元素；
- 先删除站点模板，再计算正文哈希，避免页脚版权年份变化导致全站重复重建索引；
- 语言检测失败时写 `und`，而非猜测为中文或英文。

推荐生成以下 Markdown，它既能作为知识库原始文档，也可以在检索结果中完整追溯来源：

```markdown
---
source_url: https://docs.example.com/guide/install
canonical_url: https://docs.example.com/guide/install
title: 安装指南
crawled_at: 2026-09-24T10:00:00Z
source_updated_at: 2026-09-20T08:00:00Z
content_sha256: <sha256>
extractor_version: web-extractor/1
---

# 安装指南

正文……
```

这里的 `crawled_at` 仅是采集时间，不能伪装成源站发布时间。若源站未提供可信更新时间，应省略 `source_updated_at`。

## 7. 幂等入库与删除

为每个 `source_id + canonical_url` 生成稳定的外部键，例如 `web:{source_id}:{sha256(canonical_url)}`。同一页面正文哈希未变时，只更新最后检查时间，不调用 embedding。正文变化时按以下补偿流程执行：

```text
1. 将 page 标记为 indexing，创建带 idempotency key 的 outbox 事件。
2. 调用知识库“按 external_id upsert”接口，写入完整 Markdown 与 metadata。
3. 收到成功响应后，在同一采集器事务中更新 hash、document_id、状态和 outbox。
4. 调用超时/连接断开时不猜测结果；保留 outbox，以同一幂等键重试。
```

知识库端必须支持 upsert 语义：新版本先删除该 `external_id` 旧 chunks，再写新 chunks，或使用版本号并在最后原子切换活动版本；不得每次采集都新增一个独立文档。跨向量库和关系库通常无法做到单事务，因此 `indexing`、幂等键和可重试 outbox 是必要的。

删除采用保守策略。一个 run 没发现 URL 并不代表它被删除，可能只是短暂抓取失败或站点导航变化；连续 `N=3` 次成功完成的 run 都没有发现该 URL 后才标记 `stale` 并提交删除事件。删除前再检查该 URL 不在最新 frontier 内，且不要删除人工上传的同名文档。

## 8. 与 Antler Knowledge 的可选集成

当前项目的文档接口是 `POST /api/v1/knowledge-bases/{knowledge_base_id}/documents`（multipart 上传），并在请求内同步解析、分块和写 Chroma。最小集成可以把第 6 节 Markdown 作为 `web-<url-hash>.md` 上传；无需修改现有检索接口。

但该最小方案无法可靠 upsert：现有去重以文件 SHA-256 为依据，正文变化会成为新文档，旧版本不会自动删除。生产集成前建议新增受限的内部/管理员接口，而不是让采集器直接访问数据库：

```text
PUT /api/v1/knowledge-bases/{kb_id}/external-documents/{external_id}
Authorization: service credential with documents:write

{
  "filename": "web-install-guide.md",
  "content_markdown": "...",
  "metadata": {
    "source_type": "web",
    "source_id": "...",
    "canonical_url": "...",
    "content_sha256": "...",
    "crawled_at": "..."
  }
}
```

该端点应只接受服务端认证、长度受限的 `external_id` 和 Markdown；它负责找到并替换同外部键的文档，沿用现有 `RAGStore` 的删除、索引与失败补偿逻辑。Chroma metadata 至少保存 `source_type`、`canonical_url`、`external_id`、`content_sha256`，使 `/retrieve` 返回的片段可展示来源链接。

不建议把 Playwright 及 Chromium 安装进当前应用容器：浏览器依赖、内存和安全边界与现有单容器 RAG 服务不同。以独立 crawler 容器通过 API 对接更易限权、升级和隔离；如果暂时只需要少量网页，也可以在外部运行一次性采集命令后上传 Markdown。

## 9. API、权限与可观测性

控制面 API 示例：

| 操作 | 建议端点 | 权限 |
| --- | --- | --- |
| 创建/修改采集源 | `POST/PATCH /crawl-sources` | admin/editor，且仅允许其可写知识库 |
| 查看源与页面 | `GET /crawl-sources/{id}`、`/pages` | read |
| 手动启动 | `POST /crawl-sources/{id}/runs` | admin/editor，限频 |
| 停止未开始任务 | `POST /crawl-runs/{id}/cancel` | admin/editor |
| 查看安全日志 | `GET /crawl-runs/{id}/attempts` | admin |

采集器身份只能向指定知识库写入，不能读取任意文档、创建用户或调用聊天/Agent 端点。服务端保存凭据引用，不保存明文 API Key；日志把 URL query 参数和错误页正文脱敏/截断。审计事件记录操作者、source、run、页数、结果计数和安全错误码，不记录完整正文。

最少应有以下指标：

- `crawl_run_duration_seconds`、`crawl_pages_total{outcome,mode}`、`crawl_render_duration_seconds`；
- `crawl_queue_depth`、`crawl_retry_total{reason}`、每主机响应码与限速次数；
- `crawl_index_lag_seconds`、`crawl_content_changed_total`、`crawl_stale_deleted_total`；
- 浏览器并发数、内存、崩溃次数及渲染超时率。

对错误码告警，而非对任意单页失败告警：例如连续 3 次 run 的成功率低于阈值、SSRF 拒绝突增、浏览器 crash loop、入库 outbox 堆积、同一站点 401/403/429 突增。

## 10. 安全、合规与资源边界

- 在创建数据源时记录站点授权、用途、负责人和复审日期；默认遵守 `robots.txt`、条款及版权/隐私要求。
- 禁止认证绕过、验证码处理和模拟用户交互。需要受控登录的内部站点应作为独立项目，采用专用低权限服务账号、凭据保险库、审批和更严格审计。
- 所有网络请求经 SSRF 防护；禁止私网、重定向逃逸、非 HTTP scheme 和 DNS rebinding。
- 设置每 run 最大页数/深度/总字节数、每页 HTML 上限（例如 5 MiB）、响应/渲染总超时、每主机并发和速率限制。
- HTML、Markdown、标题、URL、HTTP 错误页和浏览器 DOM 都是不可信数据。渲染管理 UI 时必须转义，绝不将采集正文当作指令执行。
- 不采集页面中的 secret、个人信息或用户生成的敏感数据；发现疑似密钥/凭据时将页面置为 `blocked:sensitive_content`，不入库，并通知负责人。

## 11. 交付阶段与验收

### 阶段 A：受控 MVP

实现单个种子、静态抓取、allowlist、正文提取、Markdown 导出、内容哈希、手动上传/入库。验收：10 个静态文档页可追溯入库；重复运行不产生新向量；域外 URL、私网地址和 `robots.txt` 禁止路径被拒绝。

### 阶段 B：CSR 与增量

加入 Playwright worker、站点 selector、资源拦截、稳定文本等待、条件请求、outbox、页面和 run 状态。验收：在 React/Vue 测试站点上，渲染后的正文与人工浏览器看到的正文一致；超时页面不让任务卡死；变更一页只重建该页；失败后重试不会重复文档。

### 阶段 C：生产化

加入持久队列、多 worker 互斥、调度、监控、审计、stale 删除和灾备演练。验收：worker 重启后任务可恢复；429 限流时退避且不压垮源站；删除页面三次确认后从知识库及向量索引消失；可按来源 URL 审计每条检索结果。

## 12. 测试清单

- 单元测试：URL 规范化、allowlist、私网 IP/重定向拒绝、robots 规则、selector 清洗、Markdown 转换、正文哈希、外部键与状态机；
- 浏览器集成测试：用本地 fixture 提供 CSR、慢请求、长轮询、客户端路由、错误边界和空页面，断言不使用固定 sleep；
- 端到端测试：首次索引、`304`、内容变更、入库超时后幂等重试、连续缺失删除、取消和 worker 重启；
- 安全测试：`file:`/`data:` URL、302 到私网、DNS rebinding mock、超大响应、恶意 selector/正则、含 prompt injection 的正文和含 secret 的样本；
- 质量评测：人工标注 30–50 个目标页面，度量正文覆盖率、导航噪声率、标题正确率、来源链接可用率、索引延迟与检索引用正确率。

## 13. 上线前决策

1. 哪些域名、路径、负责人及授权记录进入首期 allowlist？
2. 运行频率、最大页面数、时延和浏览器资源预算分别是多少？
3. 站点专用 selector 由谁审核、如何版本化和回滚？
4. 选择独立 crawler 服务还是实现 Antler 的 `external-documents` upsert API？
5. `robots.txt`、版权、隐私/个人信息与敏感词命中后分别采用跳过、人工审核还是删除的策略？
