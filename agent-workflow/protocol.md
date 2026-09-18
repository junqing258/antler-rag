# 多 Agent 协议

运行时产物保存在 `.agent-runs/<run-id>/`，该目录默认不纳入 Git。

| 文件 | 所有者 | 用途 |
| --- | --- | --- |
| `requirement.md` | 用户/编排器 | 本次任务的不可变需求副本。 |
| `plan.json`、`plan.md` | Codex | 机器可读和人工可读的方案。 |
| `review.json`、`review.md` | Claude Code | 针对当前方案版本的审核。 |
| `state.json` | 编排器 | 阶段、轮次、Git 基线和人工确认记录。 |
| `events.jsonl` | 编排器 | 仅追加的审计事件。 |

流程：`PLANNING → REVIEWING → AWAITING_HUMAN_APPROVAL → APPROVED → IMPLEMENTING → IMPLEMENTED`。

- `REQUEST_CHANGES` 最多触发指定轮数的方案修订。
- `BLOCKED` 立即停止，等待人类补充信息。
- `APPROVE` 只代表方案可实施；实施前仍须人工确认，并要求仓库 HEAD 与审核时的 Git 基线一致且工作区干净。
- 所有 Agent 输出必须遵守对应 JSON Schema。编排器负责将 JSON 渲染为 Markdown，不让 Agent 直接写入共享产物。
