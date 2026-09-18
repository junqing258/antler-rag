# Codex 设计 + Claude Code 审核工作流

本仓库提供一个本地、可审计的多 Agent 工作流：Codex 负责方案设计和经批准后的实施，Claude Code 独立审核方案。它们不直接共享聊天会话，而是由 Node.js 编排器通过 Markdown、JSON 和追加式事件日志传递上下文。

运行产物位于被 Git 忽略的 `.agent-runs/<run-id>/`；角色规则、JSON Schema 和编排器本身位于 `agent-workflow/` 和 `scripts/multi-agent.mjs`，应随仓库版本维护。

编排器的通用能力已拆分到 `scripts/libs/`：`workflow-runtime.mjs` 负责进程、Git 与运行产物；`workflow-contracts.mjs` 负责 Agent JSON 校验和 Markdown 渲染；`workflow-arguments.mjs` 负责命令行参数。`scripts/multi-agent.mjs` 仅保留工作流状态机和 Agent 提示词。

## 首次启用

1. 安装并登录 `codex` 和 `claude` CLI。
2. 确认 Node.js 版本满足本项目的 Node.js 22+ 要求，并安装根目录的 pnpm 依赖。
3. 将本工作流的配置文件提交到 Git。编排器在启动方案、记录批准和实施前都要求工作区干净，因此首次使用前不能遗留未提交的工作流配置。
4. 从仓库根目录确认命令可用：

   ```bash
   pnpm agents --help
   ```

编排器不读取 `.env`，也不应把密钥、访问令牌、生产数据或客户个人信息写进需求和运行产物。

## 编写需求

每次工作流从一个 Markdown 需求文件开始。可复制 [需求模板](../plans/multi-agent-requirement-template.md)，并至少写明目标、范围、验收标准和非目标。

```md
# 为检索 API 增加导出能力

## 目标

让管理员能够导出指定知识库的文档元数据。

## 范围

- 新增管理员 API。
- 不导出原始上传文件。

## 验收标准

- 未授权调用返回现有认证错误。
- 导出内容包含文档 ID、名称、创建时间。
- 后端测试覆盖空知识库和多文档情况。

## 非目标

- 不改变现有文档上传和检索接口。
```

需求文件可以在仓库任意位置，但启动时会复制到对应运行目录，后续 Agent 始终以该副本为准。因此，开始后修改原始需求文件不会改变正在进行的审核。

## 完整操作流程

先创建需求，例如 `docs/plans/add-export-requirement.md`。随后启动只读的设计—审核循环：

```bash
pnpm agents plan \
  --requirement docs/plans/add-export-requirement.md \
  --max-rounds 3
```

可以用 `--run-id` 指定便于识别的运行标识；未指定时编排器按当前时间和需求文件名生成。`--max-rounds` 可设为 1 到 5，建议默认 3，避免两个 Agent 围绕不明确的需求无限往返。

编排器为 Codex 使用只读 sandbox，为 Claude Code 使用 `plan` 权限模式。每轮都会生成：

- `plan.json` / `plan.md`：Codex 的结构化方案和可读版本；
- `review.json` / `review.md`：Claude Code 的独立审核；
- `state.json` 和 `events.jsonl`：流程状态与审计记录；
- 每个 CLI 的 stdout/stderr 日志，便于排查失败。

控制台会在每个 Agent 启动、完成以及每 15 秒仍在运行时显示状态，并实时转发子进程输出。按 `Ctrl+C` 会停止当前 Agent，并将运行状态写为 `INTERRUPTED`。

若审核状态为 `REQUEST_CHANGES`，Codex 最多按 `--max-rounds` 修订方案；`BLOCKED` 会立即停止；`APPROVE` 只使流程进入待人工确认状态。

如果 Codex 已成功生成方案、但 Claude Code 因 CLI 或 Schema 错误而失败，可只重试审核而不再次调用 Codex：

```bash
pnpm agents review <run-id>
```

该命令仅接受 `FAILED`、`REVIEWING` 或 `INTERRUPTED` 的运行，且要求已存在 `plan.json`。审核通过后进入人工确认；若仍要求修改，状态会标记为 `REVIEW_CHANGES_REQUESTED`，应由人类收敛意见后创建新的方案运行。

### 阅读并确认方案

当状态为 `AWAITING_HUMAN_APPROVAL` 时，先阅读运行目录中的 `plan.md` 与 `review.md`。重点确认：

- 修改范围是否符合预期，是否包含不希望自动化处理的迁移或删除动作；
- 审核意见是否确实解决，或是否有仍需业务方决定的假设；
- 测试计划是否覆盖关键权限、异常路径和兼容性风险；
- 当前 `git status` 是否干净，且仍停留在方案开始时的 commit。

阅读方案与审核意见后，使用输出中的 run id 明确确认：

```bash
pnpm agents approve <run-id> --confirm <run-id>
```

此步骤会再次验证 Git 工作区干净，且 HEAD 仍与方案开始时相同。通过后才可以实施：

```bash
pnpm agents implement <run-id> --confirm <run-id>
```

`implement` 会以 workspace-write sandbox 运行 Codex，且只在此显式命令中允许自动处理执行审批。它不会创建 commit 或推送远端。实施结束后，人工应检查 `git diff`、运行完整项目检查，并按团队流程提交。

实施完成不等于变更已被接受。建议的收尾顺序是：检查 `git diff`、运行 `just test` 和相关 lint/build、人工复核变更，然后再创建 commit 和 Pull Request。

查看一个流程状态：

```bash
pnpm agents status <run-id>
```

## 运行产物与状态

运行目录位于 `.agent-runs/<run-id>/`，不会进入 Git。主要文件如下：

| 文件 | 何时生成 | 如何使用 |
| --- | --- | --- |
| `requirement.md` | 启动时 | 固定本次 Agent 看到的需求。 |
| `plan.md` / `plan.json` | 每轮设计后 | 人工阅读方案；JSON 便于后续集成。 |
| `review.md` / `review.json` | 每轮审核后 | 查看批准、待改项或阻塞原因。 |
| `state.json` | 每次状态变化后 | 检查当前阶段、轮数和 Git 基线。 |
| `events.jsonl` | 全程追加 | 审计谁在何时生成了何种结果。 |
| `*.stdout.log` / `*.stderr.log` | 每次 CLI 调用后 | 排查 Agent CLI 或 Schema 输出失败。 |
| `implementation.md` | 实施后 | 查看 Codex 的实施与测试摘要。 |

`state.json` 中的常见阶段：

```text
PLANNING
  → REVIEWING
  → AWAITING_HUMAN_APPROVAL
  → APPROVED
  → IMPLEMENTING
  → IMPLEMENTED
```

另外，`BLOCKED` 表示必须补充需求或外部决策；`MAX_ROUNDS_REACHED` 表示审核持续要求修改，应该由人类收敛方案，而非继续增加轮数。`FAILED` 表示 CLI、Schema 或 Agent 调用错误；`INTERRUPTED` 表示收到中断信号；`REVIEW_CHANGES_REQUESTED` 表示单独重试审核后仍需要方案修改。

## 常见问题

### 提示 Git 工作区不干净

这是刻意的保护措施。提交或暂存当前工作后再运行；不要在方案审核期间混入无关改动，否则审核的代码基线会失效。

### Claude 或 Codex 输出不符合 Schema

查看运行目录内对应轮次的 `stderr` 和 `stdout` 日志。通常是 CLI 登录失效、模型调用中断，或模型未能按 JSON Schema 返回结果。修复环境或调整角色说明后，以新的 run id 重新开始；不要手改 `state.json` 伪造批准状态。

### 审核状态为 BLOCKED

打开 `review.md`，将未决的产品或技术选择补充到新的需求文件中，再重新发起 `plan`。例如数据保留期限、权限策略、是否允许破坏性迁移等，应该由人类决定。

### 需要改角色或审核标准

修改 `agent-workflow/design.md`、`review.md`、`implement.md` 或 Schema 文件，并提交该修改。角色规则是仓库的一部分，变更它们也应接受正常代码审查。

## 角色和安全边界

| 阶段 | Codex | Claude Code | Git 约束 |
| --- | --- | --- | --- |
| 方案 | 只读设计 | 不运行 | 干净工作区 |
| 审核 | 不运行 | 只读审核 | Git 基线固定 |
| 批准 | 不运行 | 不运行 | 人工确认基线 commit |
| 实施 | 经确认后修改 | 不运行 | 不自动 commit/push |

设计与审核输出由 JSON Schema 约束，并由编排器写入共享 Markdown，避免任一 Agent 覆盖对方产物。需求、方案与仓库内容均按不可信数据处理，不应在其中放置密钥、生产数据或能改变 Agent 权限的指令。
