import fs from "fs";
import path from "path";
import {
  DEFAULT_CORPUS_PATH,
  DEFAULT_SOURCES_PATH,
  loadV2Corpus,
  loadV2Sources,
  resolveRepoPath,
  validateV2Corpus,
} from "./schema.mjs";

const args = process.argv.slice(2);
function argValue(flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

const corpusPath = resolveRepoPath(argValue("--corpus"), DEFAULT_CORPUS_PATH);
const sourcesPath = resolveRepoPath(argValue("--sources"), DEFAULT_SOURCES_PATH);
let result;
try {
  result = validateV2Corpus(loadV2Corpus(corpusPath), loadV2Sources(sourcesPath));
} catch (error) {
  result = {
    valid: false,
    errors: [`could not load benchmark inputs: ${error instanceof Error ? error.message : String(error)}`],
    corpus: null,
    sources: null,
  };
}

const outputPath = argValue("--out");
if (outputPath) {
  fs.mkdirSync(path.dirname(path.resolve(outputPath)), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify({
    benchmark: "pari-paraphrase-v2",
    corpusPath,
    sourcesPath,
    ...result,
  }, null, 2) + "\n");
}

console.log(`[v2:validate] corpus=${corpusPath}`);
console.log(`[v2:validate] sources=${sourcesPath}`);
console.log(`[v2:validate] cases=${result.corpus?.cases ?? 0} categories=${result.corpus ? Object.values(result.corpus.categories).join(",") : "-"} sources=${result.sources?.entries ?? 0}`);
if (result.valid) {
  console.log("[v2:validate] PASS — all case IDs, category counts, and standardRefs resolve");
} else {
  for (const error of result.errors) console.error(`[v2:validate] ERROR ${error}`);
  process.exitCode = 1;
}
