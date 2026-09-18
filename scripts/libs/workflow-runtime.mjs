import { execFileSync, spawn } from "node:child_process";
import { appendFileSync, createWriteStream, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const CONFIG = resolve(ROOT, "agent-workflow");
export const RUNS = resolve(ROOT, ".agent-runs");
export const DEFAULT_TIMEOUT_SECONDS = 1_200;

const MAX_BUFFER_BYTES = 10 * 1024 * 1024;

export class WorkflowError extends Error {}
export class WorkflowInterruptedError extends WorkflowError {}

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

export async function runProgram(program, args, { timeoutSeconds, label, runDir, signal }) {
  if (signal?.aborted) throw new WorkflowInterruptedError(`${label} 已中断。`);
  const startedAt = Date.now();
  const stdoutLog = createWriteStream(resolve(runDir, `${label}.stdout.log`), { encoding: "utf8" });
  const stderrLog = createWriteStream(resolve(runDir, `${label}.stderr.log`), { encoding: "utf8" });
  const stdoutChunks = [];
  let stdoutBytes = 0;
  let timedOut = false;
  let aborted = signal?.aborted ?? false;

  console.log(`[${utcNow()}] ${label} 已启动。`);
  const child = spawn(program, args, { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] });
  const progress = setInterval(() => {
    const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1_000);
    console.log(`[${utcNow()}] ${label} 仍在运行（${elapsedSeconds}s）。`);
  }, 15_000);
  progress.unref();

  const onAbort = () => {
    aborted = true;
    child.kill("SIGTERM");
  };
  signal?.addEventListener("abort", onAbort, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    child.kill("SIGTERM");
  }, timeoutSeconds * 1_000);

  try {
    const result = await new Promise((resolveResult, reject) => {
      child.stdout.on("data", (chunk) => {
        stdoutLog.write(chunk);
        process.stdout.write(chunk);
        if (stdoutBytes + chunk.length <= MAX_BUFFER_BYTES) {
          stdoutChunks.push(chunk);
          stdoutBytes += chunk.length;
        }
      });
      child.stderr.on("data", (chunk) => {
        stderrLog.write(chunk);
        process.stderr.write(chunk);
      });
      child.on("error", reject);
      child.on("close", (code, childSignal) => resolveResult({ code, childSignal }));
    });

    if (aborted) throw new WorkflowInterruptedError(`${label} 已中断。`);
    if (timedOut) throw new WorkflowError(`${label} 执行超时；请查看对应日志。`);
    if (result.code !== 0) {
      throw new WorkflowError(`${label} 失败（退出码 ${result.code ?? "未知"}）；请查看对应 stderr 日志。`);
    }
    const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1_000);
    console.log(`[${utcNow()}] ${label} 已完成（${elapsedSeconds}s）。`);
    return Buffer.concat(stdoutChunks).toString("utf8");
  } finally {
    clearInterval(progress);
    clearTimeout(timeout);
    signal?.removeEventListener("abort", onAbort);
    stdoutLog.end();
    stderrLog.end();
  }
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
