import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { ROOT_DIR } from "./schema.mjs";

// Some judge modules are loaded dynamically through the TypeScript bridge, so
// keep those entry points explicit. From each entry point, recursively follow
// local static imports/exports/requires so a helper change cannot silently
// alter judge behavior without changing the fingerprint.
const JUDGE_ENTRY_FILES = [
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

const SOURCE_EXTENSIONS = ["", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json"];

export function sha256Buffer(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export function sha256File(filePath) {
  return sha256Buffer(fs.readFileSync(filePath));
}

function relativeRepoPath(absolutePath) {
  return path.relative(ROOT_DIR, absolutePath).split(path.sep).join("/");
}

function resolveLocalSpecifier(fromRelativePath, specifier) {
  let basePath;
  if (specifier.startsWith("@/")) {
    basePath = path.join(ROOT_DIR, "src", specifier.slice(2));
  } else if (specifier.startsWith(".")) {
    basePath = path.resolve(ROOT_DIR, path.dirname(fromRelativePath), specifier);
  } else {
    return null;
  }

  const rootWithSeparator = `${path.resolve(ROOT_DIR)}${path.sep}`;
  for (const extension of SOURCE_EXTENSIONS) {
    const candidate = `${basePath}${extension}`;
    const resolved = path.resolve(candidate);
    if (resolved !== path.resolve(ROOT_DIR) && !resolved.startsWith(rootWithSeparator)) continue;
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) return relativeRepoPath(resolved);
  }

  for (const extension of SOURCE_EXTENSIONS.slice(1)) {
    const candidate = path.join(basePath, `index${extension}`);
    const resolved = path.resolve(candidate);
    if (!resolved.startsWith(rootWithSeparator)) continue;
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) return relativeRepoPath(resolved);
  }

  return null;
}

function localSpecifiers(source) {
  const found = new Set();
  const patterns = [
    /\b(?:import|export)\s+(?:[^"'()]*?\s+from\s+)?["']([^"']+)["']/g,
    /\bimport\(\s*["']([^"']+)["']\s*\)/g,
    /\brequire\(\s*["']([^"']+)["']\s*\)/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) found.add(match[1]);
  }
  return [...found];
}

export function judgeSourceFiles() {
  const pending = [...JUDGE_ENTRY_FILES];
  const seen = new Set();

  while (pending.length) {
    const relativePath = pending.pop();
    if (!relativePath || seen.has(relativePath)) continue;
    const absolutePath = path.join(ROOT_DIR, relativePath);
    if (!fs.existsSync(absolutePath) || !fs.statSync(absolutePath).isFile()) {
      throw new Error(`judge provenance source is missing: ${relativePath}`);
    }
    seen.add(relativePath);

    const source = fs.readFileSync(absolutePath, "utf8");
    for (const specifier of localSpecifiers(source)) {
      const resolved = resolveLocalSpecifier(relativePath, specifier);
      if (resolved && !seen.has(resolved)) pending.push(resolved);
    }
  }

  return [...seen].sort();
}

export function buildJudgeProvenance() {
  const files = judgeSourceFiles().map((relativePath) => ({
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
    schemaVersion: 2,
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
