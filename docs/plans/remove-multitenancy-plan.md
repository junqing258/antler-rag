# Antler RAG：下线多租户架构实施计划

> 状态：Draft
>
> 本文定义将当前多租户 RAG 管理服务收敛为单实例、单全局工作区的范围、迁移方案、实施顺序与验收标准；不包含业务代码实现。

## 1. 背景与目标

当前系统的租户边界贯穿 SQLite、FastAPI 鉴权、Chroma metadata、上传目录和 Vue 管理端：每个请求需携带或解析 `tenant_id`，普通用户经由成员关系获得租户内角色，API Key 也绑定租户。

目标是将产品调整为单组织部署：一套服务中只有一个全局知识资产空间。系统仍保留多用户协作、角色权限、多个知识库、API Key、文档管理、审计、检索和问答能力，但不再提供租户创建、切换、隔离或跨租户管理能力。

### 1.1 成功标准

1. 浏览器会话和 API Key 调用均不再要求或发送 `X-Tenant-ID`。
2. 任一授权用户可在其全局角色许可的范围内访问知识库与文档；不存在租户选择、成员关系或平台/租户两级权限概念。
3. SQLite、上传文件与 Chroma 向量索引均不再存储或依赖 `tenant_id`。
4. 已有部署的数据能以可预演、可校验、可回退的流程迁移；迁移期间不产生三类存储之间的不一致。
5. 前端、API 文档、部署/备份文档和自动化测试不再宣称或验证多租户隔离。
6. 不再存在隐式“默认知识库”：所有知识库均可由有权限的用户删除，首个知识库由管理员显式创建。

## 2. 范围与目标模型

### 2.1 保留能力

- 本地用户登录、会话、改密、退出。
- 全局角色：`admin`、`editor`、`viewer`。
- 全局用户管理、API Key 管理、知识库与文档管理。
- API Key scopes：`retrieve`、`chat`、`documents:read`、`documents:write`、`documents:delete`。
- 审计事件、Chroma 持久化检索、上传文件存储和现有的健康检查。

### 2.2 移除能力

- `tenants` 与 `memberships` 数据实体，`TenantContext`、租户状态和成员归属校验。
- `platform_admin` / `tenant_admin` 双层权限、租户创建/启停/切换。
- `is_default`、全局或租户级默认知识库约束，以及默认知识库不可删除的限制。
- `/api/v1/tenants`、`/api/v1/auth/me/tenants` 和平台管理员管理接口。
- 前端租户页、租户选择器、session 中的 `tenantId`、路由租户前置条件和 `X-Tenant-ID` 请求头。
- SQLite、Chroma metadata、文件目录和文档说明中的 `tenant_id` / tenant 概念。

### 2.3 权限映射

新角色作用于整个实例。

| 现有身份/角色 | 迁移后角色 |
| --- | --- |
| `is_platform_admin=1` 或任一活动 `tenant_admin` | `admin` |
| 任一活动 `editor`，且未成为管理员 | `editor` |
| 仅有活动 `viewer` | `viewer` |
| 没有活动成员关系 | `role=NULL`，不授予访问权限；保留用户记录供管理员按需授予全局角色 |

当同一用户在多个租户角色不同，按 `admin > editor > viewer` 取权限最高者。`users.role` 定义为 `NULL | admin | editor | viewer`，并以 `CHECK(role IS NULL OR role IN ('admin','editor','viewer'))` 限制取值；没有角色的用户不会获得正常会话，登录接口返回明确的“账号尚未获授权”错误，前端停留在登录页而不进入管理台。`admin` 可管理全局用户、API Key、知识库和文档；`editor` 可管理知识库和文档；`viewer` 仅可读和检索。

## 3. 迁移原则与发布策略

### 3.1 推荐的数据处置决策

默认方案为合并所有现有租户数据到全局空间，而不是静默丢弃数据。知识库和文档 UUID 目前全局唯一，可直接保留。若多个租户内出现同名知识库，迁移前生成冲突清单，并将后续冲突名称改为 `<原租户名称> - <知识库名称>`；名称截断和二次重名以稳定后缀处理。

迁移会移除 `is_default` 字段、`one_default_kb_per_tenant` 索引以及默认知识库不可删除规则；所有存量知识库都以普通知识库迁入。因此不会出现多租户默认知识库合并到单一全局唯一约束时的冲突，也不会隐式指定某个租户的默认知识库为全局默认。

所有旧 session 和 API Key 在切换时撤销。旧 API Key 的 scope 在单租户模型下将影响全局资源，继续保留会扩大原授权范围；管理员应在迁移后重新创建并分发 Key。

若业务要求只保留某一个租户、或要求旧 API Key 无中断继续可用，必须在实施前单独确认，并调整本计划的迁移与风险控制。

### 3.2 停机与回退

SQLite、`data/tenants/` 和 `data/chroma/` 是同一个一致性单元。迁移必须在维护窗口内停止应用写入，先完成全量目录备份，再操作生产数据。迁移失败或验收不通过时，停止新版本、恢复完整数据目录、以旧镜像启动；不得只回滚其中一个存储组件。

向量数据不做就地 metadata 修改。迁移后从 SQLite 文档记录及原始上传文件重建全局 Chroma collection，以保证 metadata、文件和关系记录一致。

## 4. 实施步骤

### 阶段 A：迁移前预检与演练

1. 新增离线迁移命令，支持 `--dry-run`，只输出租户、用户、知识库、文档、文件、API Key 和名称冲突统计，不写任何数据。
2. 备份整个 `RAG_DATA_DIR`，并校验 SQLite 可读取、上传文件存在性、文档记录数、Chroma collection 数量和向量数。
3. 在备份副本上完整演练迁移，生成迁移报告：重命名知识库、无法映射的用户、缺失文件、失败文档和撤销 Key 数量。
4. 将演练报告和备份校验结果作为生产切换的准入条件。

### 阶段 B：数据库演进

1. 将 `Database.migrate()` 从固定执行 `001_initial.sql` 改为按版本顺序读取、事务执行并记录 `schema_migrations` 的迁移执行器。对需要重建表的 `002`，迁移执行器必须在开启事务前执行 `PRAGMA foreign_keys=OFF`；完成建表、复制、删除旧表和改名后，先执行 `PRAGMA foreign_key_check`，仅在检查无结果时恢复 `PRAGMA foreign_keys=ON` 并记录该版本。不得在已开始的事务中切换该 pragma。
2. 保留历史 `001_initial.sql`，新增 `002_remove_multitenancy.sql`，以 SQLite 重建表的方式完成以下变更：
   - 删除 `tenants`、`memberships`；
   - 将 `tenant_api_keys` 重建为 `api_keys`，移除 `tenant_id`；
   - 重建 `knowledge_bases`、`documents`、`audit_events` 并删除 `tenant_id`；删除 `is_default` 与 `one_default_kb_per_tenant`，同步替换依赖这些字段的索引和唯一约束；
   - 将 `users.is_platform_admin` 转为允许 `NULL` 的 `users.role`，按第 2.3 节回填；
   - 保留用户 ID、知识库 ID、文档 ID、API Key 哈希和审计时间；撤销所有未撤销 Key，撤销所有未撤销 session；
   - 不复制租户记录和成员关系。迁移报告应留存原租户到合并结果的映射，不写入在线业务表。
3. 为全新安装保留“创建首个管理员”的 bootstrap 行为，但不再创建默认租户或默认知识库；管理员显式创建第一个知识库。

### 阶段 C：文件与向量数据迁移

1. 将上传文件从 `data/tenants/<tenant-id>/knowledge-bases/<kb-id>/uploads/` 移至 `data/uploads/<kb-id>/`。先复制、校验 SHA-256 与记录数，再切换路径；成功验收后再由发布窗口清理旧目录。
2. 创建新的 collection（或清空并重建现有 collection），按已迁移且状态可索引的文档重新解析、切块、写入向量。新 chunk metadata 只写入 `knowledge_base_id`、`document_id`、文件名、摘要与 chunk 序号，不写入 `tenant_id`；完成后比较每份文档的 chunk 数和总向量数。
4. 仅在数据库、文件和新 collection 的校验全部通过后，切换应用读取新路径和新 collection。

### 阶段 D：后端收敛

1. 以 `AccessContext` 或直接 `Principal` 替代 `TenantContext`；移除 `tenant_context()`、`active_tenant()`、成员归属与租户状态判断。
2. 会话鉴权从用户全局 `role` 获取授权；API Key 仅检查有效期、撤销状态和 scope。所有数据 API 忽略并不再记录 `X-Tenant-ID`。
3. 重写 repository 方法签名和 SQL：知识库、文档与 Key 查询不再传递 `tenant_id`；审计函数不再接收该字段。
4. RAG store 的 `index`、`retrieve`、删除函数与 where filter 移除 `tenant_id`，只以知识库及文档标识过滤；`upload_path()` 调整为全局目录。
5. 下线租户和平台管理员路由；成员路由改名或改语义为全局用户管理。全局用户管理必须禁止降级、禁用或删除最后一个活跃 `admin`，并返回稳定的 `last_active_admin` 冲突错误。更新 OpenAPI 描述、错误码，以及临时密码过期提示中“tenant administrator”的文案。

### 阶段 E：前端与文档收敛

1. 删除 `TenantsPage.vue` 和 `/tenants` 路由，删除顶部租户选择器、相关状态与导航入口。
2. 精简 `useAuth.ts` 中的 `tenantId`、`setTenant()` 和 session 序列化；请求封装停止注入 `X-Tenant-ID`。
3. 更新成员页角色选择、权限提示、Dashboard、检索示例、API Key 页与 API 代码片段中的全部租户文案。
4. 更新 README、`docs/operations`、`.env.example`、后端项目描述和历史计划中仍对当前产品构成误导的说明。历史设计文档可保留，但须标注“已废弃的多租户设计”。

## 5. 测试与验收

### 5.1 自动化测试

- 迁移：空库、单租户库、多租户库、知识库重名、多默认知识库、同一用户多角色、无活动成员关系用户、缺失上传文件、重复执行迁移与回退备份；重建表后执行外键完整性检查。
- 鉴权：`admin`、`editor`、`viewer` 和 `role=NULL` 的全局权限矩阵；过期/撤销 API Key 和每项 API scope；不能降级、禁用或删除最后一个活跃 `admin`。
- 数据：知识库/文档 CRUD、文件路径、Chroma 查询过滤、删除后的向量清理、索引重建。
- API 契约：数据路由不带 `X-Tenant-ID` 即可正常工作；已移除的租户路由返回 404；旧会话和旧 API Key 被拒绝。
- 前端：登录后不请求租户列表、不存储 tenant ID、不发送租户头；无租户导航和切换控件；全局角色对应正确菜单与操作。

### 5.2 发布验收清单

1. 生产完整备份可在隔离环境恢复并启动旧版本。
2. 干跑报告与生产数据统计一致，所有名称冲突和缺失文件都有明确处理结果。
3. 迁移后 SQLite 的表结构、记录数、文件哈希和向量/切块统计通过校验。
4. 管理员可重新登录、创建用户和 API Key，编辑者可管理文档，只读用户无写入权限；无角色用户无法进入管理台，且最后一个活跃管理员不能被降级、禁用或删除。
5. 浏览器和程序 API 全程不要求 `X-Tenant-ID`，前端无租户 UI 或文案残留。
6. 健康检查、上传、检索、问答、删除和备份恢复 smoke test 全部通过。

## 6. 影响文件

后端重点为 `apps/backend/src/antler_rag/app.py`、`db/repository.py`、`db/migrations/`、`rag/store.py` 与 `config.py`；前端重点为 `useAuth.ts`、`lib/request.ts`、`router.ts`、`layouts/AdminLayout.vue`、`routes/TenantsPage.vue`、成员/API Key/概览/检索页面。还需要同步更新 `README.md`、`docs/operations/`、后端测试与前端权限测试。

## 7. 待确认事项

1. 是否按默认方案合并所有租户数据；如否，明确唯一保留的租户及其他租户数据的归档或删除要求。
2. 旧 API Key 是否必须保持无中断可用；若是，需要接受其权限从租户范围扩大为全局范围，或在 API 层引入临时兼容策略。
