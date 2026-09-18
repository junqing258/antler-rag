import { WorkflowError } from "./workflow-runtime.mjs";

export function parseFlags(tokens, allowed) {
  const values = {};
  for (let index = 0; index < tokens.length; index += 1) {
    const name = tokens[index];
    if (!allowed.has(name)) throw new WorkflowError(`不支持的参数：${name}`);
    const value = tokens[index + 1];
    if (!value || value.startsWith("--")) throw new WorkflowError(`参数 ${name} 缺少值。`);
    if (values[name] !== undefined) throw new WorkflowError(`参数 ${name} 不能重复。`);
    values[name] = value;
    index += 1;
  }
  return values;
}

export function parsePositiveInteger(value, flag, { min, max }) {
  if (!/^\d+$/.test(value)) throw new WorkflowError(`${flag} 必须是整数。`);
  const parsed = Number(value);
  if (parsed < min || parsed > max) throw new WorkflowError(`${flag} 必须介于 ${min} 和 ${max} 之间。`);
  return parsed;
}

export function usage() {
  return `用法：
  node scripts/multi-agent.mjs plan --requirement <需求.md> [--run-id <id>] [--max-rounds 3] [--timeout-seconds 1200]
  node scripts/multi-agent.mjs review <run-id> [--timeout-seconds 1200]
  node scripts/multi-agent.mjs approve <run-id> --confirm <run-id>
  node scripts/multi-agent.mjs implement <run-id> --confirm <run-id> [--timeout-seconds 1200]
  node scripts/multi-agent.mjs status <run-id>`;
}
