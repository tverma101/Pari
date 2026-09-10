import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { ROOT_DIR } from "./schema.mjs";

const JUDGE_SOURCE_FILES = [
  "benchmarks/eval/metrics.mjs",
  "benchmarks/paraphrase-v2/score.mjs",
  "benchmarks/paraphrase-v2/judge-provenance.mjs",
  "benchmarks/paraphrase-v2/meaning-contract-bridge.mjs",
  "benchmarks/paraphrase-v2/protected-content-bridge.mjs",
  "src/lib/generation/meaningContract.ts",
  "src/lib/safety/protectedContent.ts",
  "src/lib/nlp/clauseAttachment.ts",
  "src/lib/nlp/grammar.ts",
  "src/lib/scoring/englishQuality.ts",
  "src/lib/scoring/nliJudge.ts",
];

export function sha256Buffer(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export function sha256File(filePath) {
  return sha256Buffer(fs.readFileSync(filePath));
}

export function buildJudgeProvenance() {
  const files = JUDGE_SOURCE_FILES.map((relativePath) => ({
    path: relativePath,
    sha256: sha256File(path.join(ROOT_DIR, relativePath)),
  }));
  const fingerprint = sha256Buffer(
    files.map((entry) => `${entry.path}\0${entry.sha256}`).join("\n"),
  );

  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT_DIR, "package.json"), "utf8"));
  const dependency = (name) =>
    packageJson.dependencies?.[name] ?? packageJson.devDependencies?.[name] ?? null;

  return {
    schemaVersion: 1,
    algorithm: "sha256",
    fingerprint,
    files,
    runtime: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
    },
    dependencies: {
      "@huggingface/transformers": dependency("@huggingface/transformers"),
      "harper.js": dependency("harper.js"),
      typescript: dependency("typescript"),
    },
  };
}
