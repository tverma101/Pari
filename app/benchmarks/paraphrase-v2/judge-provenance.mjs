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

// These three local assets directly affect v2 automatic quality/meaning scores.
// Hashing bytes is intentionally separate from inference: provenance must change
// if a model/config/tokenizer changes under the same local path.
const JUDGE_MODEL_DIRS = [
  "public/models/Xenova/all-MiniLM-L6-v2",
  "public/models/Xenova/nli-deberta-v3-xsmall",
  "public/models/Xenova/distilbert-base-uncased",
];

const SOURCE_EXTENSIONS = ["", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json"];
const IGNORED_ARTIFACT_FILES = new Set([".DS_Store"]);

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

function walkFiles(directory) {
  const files = [];
  if (!fs.existsSync(directory)) return files;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (IGNORED_ARTIFACT_FILES.has(entry.name)) continue;
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(absolutePath));
    else if (entry.isFile()) files.push(absolutePath);
  }
  return files;
}

export function judgeModelArtifacts() {
  return JUDGE_MODEL_DIRS.map((relativeDirectory) => {
    const absoluteDirectory = path.join(ROOT_DIR, relativeDirectory);
    if (!fs.existsSync(absoluteDirectory) || !fs.statSync(absoluteDirectory).isDirectory()) {
      return {
        path: relativeDirectory,
        present: false,
        fingerprint: sha256Buffer(`missing\0${relativeDirectory}`),
        files: [],
      };
    }

    const files = walkFiles(absoluteDirectory)
      .map((absolutePath) => ({
        path: relativeRepoPath(absolutePath),
        size: fs.statSync(absolutePath).size,
        sha256: sha256File(absolutePath),
      }))
      .sort((left, right) => left.path.localeCompare(right.path));
    const fingerprint = sha256Buffer(
      files.map((entry) => `${entry.path}\0${entry.size}\0${entry.sha256}`).join("\n"),
    );
    return {
      path: relativeDirectory,
      present: true,
      fingerprint,
      files,
    };
  });
}

export function buildJudgeProvenance() {
  const files = judgeSourceFiles().map((relativePath) => ({
    path: relativePath,
    sha256: sha256File(path.join(ROOT_DIR, relativePath)),
  }));
  const sourceFingerprint = sha256Buffer(
    files.map((entry) => `${entry.path}\0${entry.sha256}`).join("\n"),
  );
  const modelArtifacts = judgeModelArtifacts();
  const modelFingerprint = sha256Buffer(
    modelArtifacts.map((entry) => `${entry.path}\0${entry.present}\0${entry.fingerprint}`).join("\n"),
  );

  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT_DIR, "package.json"), "utf8"));
  const dependency = (name) =>
    packageJson.dependencies?.[name] ?? packageJson.devDependencies?.[name] ?? null;
  const runtime = {
    node: process.version,
    platform: process.platform,
    arch: process.arch,
  };
  const dependencies = {
    "@huggingface/transformers": dependency("@huggingface/transformers"),
    "harper.js": dependency("harper.js"),
    typescript: dependency("typescript"),
  };

  const fingerprint = sha256Buffer(JSON.stringify({
    sourceFingerprint,
    modelFingerprint,
    runtime,
    dependencies,
  }));

  return {
    schemaVersion: 3,
    algorithm: "sha256",
    fingerprint,
    sourceFingerprint,
    modelFingerprint,
    files,
    modelArtifacts,
    runtime,
    dependencies,
  };
}
