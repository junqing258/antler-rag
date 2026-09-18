import { WorkflowError } from "./workflow-runtime.mjs";

function requireString(value, field, { emptyOk = false } = {}) {
  if (typeof value !== "string" || (!emptyOk && !value.trim())) {
    throw new WorkflowError(`Agent 输出的 ${field} 必须是${emptyOk ? "" : "非空"}字符串。`);
  }
  return value;
}

function requireArray(value, field) {
  if (!Array.isArray(value)) throw new WorkflowError(`Agent 输出的 ${field} 必须是数组。`);
  return value;
}

function requireExactKeys(value, keys, label) {
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new WorkflowError(`${label} 必须是对象。`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new WorkflowError(`${label} JSON 字段不匹配：${actual.join(", ")}`);
  }
}

export function validatePlan(value) {
  requireExactKeys(value, ["summary", "assumptions", "changes", "risks", "tests", "open_questions", "revision_notes"], "方案");
  requireString(value.summary, "summary");
  requireString(value.revision_notes, "revision_notes", { emptyOk: true });
  for (const field of ["assumptions", "risks", "tests", "open_questions"]) {
    for (const item of requireArray(value[field], field)) requireString(item, field);
  }
  const changes = requireArray(value.changes, "changes");
  if (!changes.length) throw new WorkflowError("方案至少需要一项 changes。");
  for (const [index, change] of changes.entries()) {
    requireExactKeys(change, ["path", "purpose", "steps"], `changes[${index}]`);
    requireString(change.path, `changes[${index}].path`);
    requireString(change.purpose, `changes[${index}].purpose`);
    const steps = requireArray(change.steps, `changes[${index}].steps`);
    if (!steps.length) throw new WorkflowError(`changes[${index}].steps 不能为空。`);
    for (const step of steps) requireString(step, `changes[${index}].steps`);
  }
  return value;
}

export function validateReview(value) {
  requireExactKeys(value, ["status", "summary", "findings", "required_changes", "questions", "approval_conditions"], "审核");
  if (!new Set(["APPROVE", "REQUEST_CHANGES", "BLOCKED"]).has(value.status)) {
    throw new WorkflowError("审核 status 不正确。");
  }
  requireString(value.summary, "summary");
  for (const field of ["required_changes", "questions", "approval_conditions"]) {
    for (const item of requireArray(value[field], field)) requireString(item, field);
  }
  for (const [index, finding] of requireArray(value.findings, "findings").entries()) {
    requireExactKeys(finding, ["severity", "path", "issue", "recommendation"], `findings[${index}]`);
    if (!new Set(["critical", "high", "medium", "low"]).has(finding.severity)) {
      throw new WorkflowError(`findings[${index}].severity 不正确。`);
    }
    for (const field of ["path", "issue", "recommendation"]) {
      requireString(finding[field], `findings[${index}].${field}`);
    }
  }
  return value;
}

function markdownList(items, empty = "无") {
  return items.length ? items.map((item) => `- ${item}`) : [`- ${empty}`];
}

export function renderPlan(plan) {
  const lines = ["# 技术方案", "", "## 摘要", "", plan.summary, "", "## 假设", "", ...markdownList(plan.assumptions), "", "## 变更", ""];
  for (const change of plan.changes) {
    lines.push(`### \`${change.path}\``, "", change.purpose, "");
    change.steps.forEach((step, index) => lines.push(`${index + 1}. ${step}`));
    lines.push("");
  }
  lines.push("## 风险与兼容性", "", ...markdownList(plan.risks), "", "## 验证", "", ...markdownList(plan.tests), "", "## 待确认问题", "", ...markdownList(plan.open_questions), "", "## 修订说明", "", plan.revision_notes, "");
  return lines.join("\n");
}

export function renderReview(review) {
  const lines = ["# 方案审核", "", `**状态：${review.status}**`, "", "## 摘要", "", review.summary, "", "## 发现", ""];
  if (!review.findings.length) {
    lines.push("- 无", "");
  } else {
    for (const finding of review.findings) {
      lines.push(`### [${finding.severity.toUpperCase()}] \`${finding.path}\``, "", `问题：${finding.issue}`, "", `建议：${finding.recommendation}`, "");
    }
  }
  lines.push("## 必须修改", "", ...markdownList(review.required_changes), "", "## 待回答问题", "", ...markdownList(review.questions), "", "## 批准条件", "", ...markdownList(review.approval_conditions), "");
  return lines.join("\n");
}

export function parseClaudeResult(raw) {
  let envelope;
  try {
    envelope = JSON.parse(raw);
  } catch {
    throw new WorkflowError("Claude Code 未返回 JSON 输出。");
  }
  if (envelope?.structured_output && typeof envelope.structured_output === "object") return envelope.structured_output;
  if (envelope && typeof envelope.result === "object" && !Array.isArray(envelope.result)) return envelope.result;
  if (typeof envelope?.result === "string") {
    try {
      const value = JSON.parse(envelope.result);
      if (value && !Array.isArray(value) && typeof value === "object") return value;
    } catch {
      throw new WorkflowError("Claude Code result 不是 JSON 对象。");
    }
  }
  if (envelope && !Array.isArray(envelope) && typeof envelope === "object") return envelope;
  throw new WorkflowError("无法解析 Claude Code 审核输出。");
}
