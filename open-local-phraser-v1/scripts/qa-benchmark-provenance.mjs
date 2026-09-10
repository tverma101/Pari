#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { buildJudgeProvenance, sha256File } from "../benchmarks/paraphrase-v2/judge-provenance.mjs";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const first = buildJudgeProvenance();
const second = buildJudgeProvenance();

assert.match(first.fingerprint, /^[0-9a-f]{64}$/, "judge fingerprint is not SHA-256 hex");
assert.equal(first.fingerprint, second.fingerprint, "judge fingerprint is not deterministic within one checkout");
assert.equal(first.algorithm, "sha256", "judge fingerprint algorithm is not explicit");
assert.equal(first.runtime.node, process.version, "Node runtime provenance is incorrect");
assert(first.dependencies["@huggingface/transformers"], "transformers dependency version is missing");
assert(first.dependencies["harper.js"], "Harper dependency version is missing");
assert(first.dependencies.typescript, "TypeScript dependency version is missing");

const byPath = new Map(first.files.map((entry) => [entry.path, entry.sha256]));
for (const required of [
  "benchmarks/eval/metrics.mjs",
  "benchmarks/paraphrase-v2/score.mjs",
  "benchmarks/paraphrase-v2/judge-provenance.mjs",
  "src/lib/generation/meaningContract.ts",
  "src/lib/safety/protectedContent.ts",
  "src/lib/scoring/englishQuality.ts",
  "src/lib/scoring/nliJudge.ts",
]) {
  assert(byPath.has(required), `judge provenance omitted ${required}`);
  assert.equal(
    byPath.get(required),
    sha256File(path.join(ROOT_DIR, required)),
    `recorded hash does not match ${required}`,
  );
}

const scoreSource = fs.readFileSync(path.join(ROOT_DIR, "benchmarks/paraphrase-v2/score.mjs"), "utf8");
assert.match(scoreSource, /judge\s*=\s*buildJudgeProvenance\(\)/, "v2 scoring does not build judge provenance");
assert.match(scoreSource, /sha256:\s*sha256File\(corpusPath\)/, "v2 scoring does not hash the corpus");
assert.match(scoreSource, /sha256:\s*sha256File\(outputsPath\)/, "v2 scoring does not hash raw outputs");

console.log("qa:benchmark:provenance passed");
