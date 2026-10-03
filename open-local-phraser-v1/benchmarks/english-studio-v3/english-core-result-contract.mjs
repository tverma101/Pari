import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const validator = path.join(here, "validate-english-core-run.py");

export function validateEnglishCoreResult(resultPath, { promotion = false, compatLegacyV0 = false } = {}) {
  if (promotion && compatLegacyV0) throw new Error("legacy result compatibility cannot be used for promotion");
  const commandArgs = [validator, path.resolve(resultPath)];
  if (promotion) commandArgs.push("--promotion");
  if (compatLegacyV0) commandArgs.push("--compat-legacy-v0");
  const proc = spawnSync(process.env.PYTHON ?? "python3", commandArgs, { encoding: "utf8" });
  if (proc.error) throw proc.error;
  if (proc.status !== 0) {
    const detail = (proc.stdout || proc.stderr || `exit ${proc.status}`).trim();
    throw new Error(`English Core result validation failed:\n${detail}`);
  }
  return JSON.parse(proc.stdout);
}
