import { execFileSync } from "node:child_process";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const CONFIG = resolve(ROOT, "agent-workflow");
export const RUNS = resolve(ROOT, ".agent-runs");
export const DEFAULT_TIMEOUT_SECONDS = 1_200;

const MAX_BUFFER_BYTES = 10 * 1024 * 1024;

export class WorkflowError extends Error {}

export function utcNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function writeJson(filePath, value) {
  writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export function readJson(filePath) {
  try {
    const value = JSON.parse(readFileSync(filePath, "utf8"));
    if (value === null || Array.isArray(value) || typeof value !== "object") {
      throw new WorkflowError(`JSON 必须是对象：${filePath}`);
    }
    return value;
  } catch (error) {
    if (error instanceof WorkflowError) throw error;
    throw new WorkflowError(`无法读取 JSON：${filePath} (${error.message})`);
  }
}

export function appendEvent(runDir, event, data = {}) {
  appendFileSync(
    resolve(runDir, "events.jsonl"),
    `${JSON.stringify({ at: utcNow(), event, ...data })}\n`,
    "utf8",
  );
}

export function saveState(runDir, state) {
  state.updated_at = utcNow();
  writeJson(resolve(runDir, "state.json"), state);
}

export function runProgram(program, args, { timeoutSeconds, label, runDir }) {
  let stdout = "";
  let stderr = "";
  let error;
  try {
    stdout = execFileSync(program, args, {
      cwd: ROOT,
      encoding: "utf8",
      timeout: timeoutSeconds * 1_000,
      maxBuffer: MAX_BUFFER_BYTES,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (caught) {
    error = caught;
    stdout = caught.stdout?.toString() ?? "";
    stderr = caught.stderr?.toString() ?? "";
  }
  writeFileSync(resolve(runDir, `${label}.stdout.log`), stdout, "utf8");
  writeFileSync(resolve(runDir, `${label}.stderr.log`), stderr, "utf8");
  if (error) {
    const reason = error.code === "ETIMEDOUT" ? "执行超时" : `退出码 ${error.status ?? "未知"}`;
    throw new WorkflowError(`${label} 失败（${reason}）；请查看对应 stderr 日志。`);
  }
  return stdout;
}

export function git(args, { check = true } = {}) {
  try {
    return execFileSync("git", args, {
      cwd: ROOT,
      encoding: "utf8",
      maxBuffer: MAX_BUFFER_BYTES,
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (error) {
    if (!check) return error.stdout?.toString().trim() ?? "";
    throw new WorkflowError(error.stderr?.toString().trim() || `git ${args.join(" ")} 失败`);
  }
}

export function requireCleanRepository(expectedHead) {
  const head = git(["rev-parse", "HEAD"]);
  if (git(["status", "--porcelain"])) {
    throw new WorkflowError("Git 工作区不干净；请提交、暂存或清理现有改动后重试。");
  }
  if (expectedHead && head !== expectedHead) {
    throw new WorkflowError("仓库 HEAD 已变化；现有审核不再对应当前代码，请重新运行 plan。");
  }
  return head;
}

export function requireCli(program) {
  try {
    execFileSync(program, ["--version"], { stdio: "ignore" });
  } catch {
    throw new WorkflowError(`未找到或无法运行 ${program} CLI；请先安装并登录。`);
  }
}

export function runDirFor(runId) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/.test(runId)) {
    throw new WorkflowError("run id 只能包含字母、数字、点、下划线和连字符。");
  }
  return resolve(RUNS, runId);
}

export function generatedRunId(requirement) {
  const stem = basename(requirement, extname(requirement))
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "task";
  const timestamp = utcNow().slice(0, 19).replace(/[-:T]/g, "");
  return `${timestamp.slice(0, 8)}-${timestamp.slice(8)}-${stem.slice(0, 40)}`;
}
