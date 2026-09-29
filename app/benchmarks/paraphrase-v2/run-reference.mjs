/** Write the original text as the no-rewrite safety reference. */
import fs from "fs";
import os from "os";
import path from "path";
import { DEFAULT_CORPUS_PATH, loadV2Corpus, resolveRepoPath, ROOT_DIR, validateV2Corpus, loadV2Sources } from "./schema.mjs";

const args = process.argv.slice(2);
function argValue(flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

const corpusPath = resolveRepoPath(argValue("--corpus"), DEFAULT_CORPUS_PATH);
const corpus = loadV2Corpus(corpusPath);
const validation = validateV2Corpus(corpus, loadV2Sources());
if (!validation.valid) throw new Error(`v2 corpus is invalid: ${validation.errors.join("; ")}`);
const outPath = path.resolve(argValue("--out") ?? path.join(ROOT_DIR, "benchmarks/paraphrase-v2/results/original-reference.raw.jsonl"));
fs.mkdirSync(path.dirname(outPath), { recursive: true });
const handle = fs.openSync(outPath, "w");
for (const item of corpus.cases) fs.writeSync(handle, JSON.stringify({ id: item.id, output: item.input, seconds: 0, source: "original-reference" }) + "\n");
fs.closeSync(handle);
const metadataPath = path.resolve(argValue("--metadata") ?? `${outPath}.meta.json`);
fs.mkdirSync(path.dirname(metadataPath), { recursive: true });
fs.writeFileSync(metadataPath, JSON.stringify({
  schemaVersion: 1,
  benchmark: "pari-paraphrase-v2",
  generatedAt: new Date().toISOString(),
  corpusPath,
  corpusVersion: corpus.version,
  caseCount: corpus.cases.length,
  productInstruction: corpus.defaultInstruction,
  engine: {
    name: "original-reference",
    role: "no-rewrite-safety-reference",
    runtime: "none",
    license: "source text",
    quantization: "none",
    installedEvidence: false,
  },
  hardware: { platform: process.platform, arch: process.arch, node: process.version, totalMemoryGiB: Number((os.totalmem() / 1024 ** 3).toFixed(2)) },
  timing: { completedCases: corpus.cases.length, totalSeconds: 0, medianCaseSeconds: 0, peakProcessRssGiB: Number((process.memoryUsage().rss / 1024 ** 3).toFixed(3)) },
}, null, 2) + "\n");
console.log(`[v2:reference] wrote ${corpus.cases.length} rows -> ${outPath}`);
console.log(`[v2:reference] metadata -> ${metadataPath}`);
