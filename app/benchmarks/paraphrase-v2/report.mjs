/** Build automatic diagnostics, Pareto table, and a blinded pairwise sheet. */
import crypto from "crypto";
import fs from "fs";
import path from "path";
import { DEFAULT_CORPUS_PATH, loadV2Corpus, resolveRepoPath, ROOT_DIR, validateV2Corpus, loadV2Sources } from "./schema.mjs";

const args = process.argv.slice(2);
function values(flag) {
  const found = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === flag) found.push(args[index + 1]);
  }
  return found.filter(Boolean);
}
function argValue(flag) {
  return values(flag)[0];
}

const scorePaths = values("--scores").flatMap((value) => value.split(",")).map((value) => path.resolve(value));
if (scorePaths.length < 1) throw new Error("usage: node benchmarks/paraphrase-v2/report.mjs --scores <score.json> [--scores <score.json>] [--out-dir <dir>]");
const corpusPath = resolveRepoPath(argValue("--corpus"), DEFAULT_CORPUS_PATH);
const corpusData = loadV2Corpus(corpusPath);
const validation = validateV2Corpus(corpusData, loadV2Sources());
if (!validation.valid) throw new Error(`v2 corpus is invalid: ${validation.errors.join("; ")}`);
const scoreBundles = scorePaths.map((filePath) => JSON.parse(fs.readFileSync(filePath, "utf8")));
const modelStatusPath = resolveRepoPath(argValue("--model-status"), path.join(ROOT_DIR, "benchmarks/paraphrase-v2/model-status.json"));
const modelStatus = fs.existsSync(modelStatusPath) ? JSON.parse(fs.readFileSync(modelStatusPath, "utf8")) : { models: [] };
const names = scoreBundles.map((bundle, index) => String(bundle.engine?.name ?? `engine-${index + 1}`));
if (new Set(names).size !== names.length) throw new Error(`score bundles must have unique engine names: ${names.join(", ")}`);
const outDir = path.resolve(argValue("--out-dir") ?? path.join(ROOT_DIR, "benchmarks/paraphrase-v2/results/report"));
fs.mkdirSync(outDir, { recursive: true });

const pairwise = [];
const pairwiseKey = {};
for (let leftIndex = 0; leftIndex < scoreBundles.length; leftIndex += 1) {
  for (let rightIndex = leftIndex + 1; rightIndex < scoreBundles.length; rightIndex += 1) {
    const left = scoreBundles[leftIndex];
    const right = scoreBundles[rightIndex];
    const leftRows = new Map((left.results ?? []).map((row) => [row.id, row]));
    const rightRows = new Map((right.results ?? []).map((row) => [row.id, row]));
    for (const item of corpusData.cases) {
      const pairId = `${item.id}--${slug(names[leftIndex])}--${slug(names[rightIndex])}`;
      const swap = Number.parseInt(crypto.createHash("sha256").update(pairId).digest("hex").slice(0, 8), 16) % 2 === 1;
      const aEngine = swap ? names[rightIndex] : names[leftIndex];
      const bEngine = swap ? names[leftIndex] : names[rightIndex];
      const aRow = swap ? rightRows.get(item.id) : leftRows.get(item.id);
      const bRow = swap ? leftRows.get(item.id) : rightRows.get(item.id);
      pairwise.push({
        pairId,
        caseId: item.id,
        category: item.category,
        sourceText: item.input,
        candidateA: aRow?.output ?? "",
        candidateB: bRow?.output ?? "",
        preferred: "",
        meaningAdequacyA: "",
        coherenceCohesionA: "",
        grammarFluencyA: "",
        lexicalCollocationA: "",
        editDisciplineA: "",
        meaningAdequacyB: "",
        coherenceCohesionB: "",
        grammarFluencyB: "",
        lexicalCollocationB: "",
        editDisciplineB: "",
        notes: "",
      });
      pairwiseKey[pairId] = { engineA: aEngine, engineB: bEngine };
    }
  }
}

const template = [];
for (const [engineIndex, bundle] of scoreBundles.entries()) {
  for (const item of corpusData.cases) {
    template.push({
      caseId: item.id,
      category: item.category,
      engine: names[engineIndex],
      meaningAdequacy: "",
      coherenceCohesion: "",
      grammarFluency: "",
      lexicalCollocation: "",
      editDiscipline: "",
      notes: "",
    });
  }
}

const automaticRows = scoreBundles.map((bundle, index) => {
  const timingRows = (bundle.results ?? []).map((row) => row.totalSeconds ?? row.seconds).filter((value) => Number.isFinite(value));
  const meta = bundle.metadata ?? {};
  const timing = meta.timing ?? {};
  const peakMemoryGiB = firstNumber(
    meta.hardware?.peakUnifiedMemoryGiB,
    meta.timing?.peakMetalMemoryGiB,
    meta.timing?.peakProcessRssGiB,
    meta.engine?.peakMemoryGiB,
  );
  const medianSeconds = firstNumber(median(timingRows), timing.medianCaseSeconds);
  const diskBytes = firstNumber(meta.engine?.diskBytes, meta.model?.diskBytes);
  return {
    name: names[index],
    role: bundle.engine?.role ?? "unclassified",
    runtime: bundle.engine?.runtime ?? "unknown",
    license: bundle.engine?.license ?? "unknown",
    modelRepo: bundle.engine?.modelRepo ?? meta.engine?.modelRepo ?? null,
    revision: bundle.engine?.revision ?? meta.engine?.revision ?? null,
    cases: bundle.overall?.total ?? bundle.results?.length ?? 0,
    passRate: bundle.overall?.passRate ?? null,
    meaningSafeRate: bundle.overall?.meaningSafeRate ?? null,
    englishQualityRate: bundle.overall?.englishQualityRate ?? null,
    automaticDiagnosticIndex: bundle.overall?.automaticDiagnosticIndex ?? null,
    hardSafetyFailures: bundle.safety?.hardSafetyFailures ?? null,
    medianSeconds,
    peakMemoryGiB,
    diskBytes,
    installedEvidence: Boolean(bundle.engine?.installedEvidence ?? meta.engine?.installedEvidence),
    complete: (bundle.overall?.total ?? 0) === corpusData.cases.length,
  };
});
const pareto = automaticRows.map((row) => ({ ...row, paretoEfficient: isParetoEfficient(row, automaticRows) }));

const humanScoresPath = argValue("--human-scores");
const humanRatings = humanScoresPath ? loadHumanScores(path.resolve(humanScoresPath)) : [];
const humanSummary = summarizeHumanRatings(humanRatings, names);
const autoLeader = [...automaticRows].sort((a, b) => (b.automaticDiagnosticIndex ?? -1) - (a.automaticDiagnosticIndex ?? -1))[0];
const installedRows = automaticRows.filter((row) => row.installedEvidence && row.complete && row.hardSafetyFailures === 0);
const shippableLeader = installedRows.sort((a, b) => (b.automaticDiagnosticIndex ?? -1) - (a.automaticDiagnosticIndex ?? -1))[0] ?? null;

fs.writeFileSync(path.join(outDir, "pairwise-blinded.csv"), toCsv(pairwise) + "\n");
fs.writeFileSync(path.join(outDir, "pairwise-key.json"), JSON.stringify({ warning: "Keep this file separate from pairwise-blinded.csv until ratings are complete.", pairs: pairwiseKey }, null, 2) + "\n");
fs.writeFileSync(path.join(outDir, "human-scores-template.csv"), toCsv(template) + "\n");
const report = {
  schemaVersion: 1,
  benchmark: "pari-paraphrase-v2",
  generatedAt: new Date().toISOString(),
  corpus: { path: corpusPath, version: corpusData.version, cases: corpusData.cases.length },
  modelStatus: modelStatus.models ?? [],
  automaticDiagnostics: automaticRows,
  pareto,
  humanRatings: humanSummary,
  decision: {
    humanQualityWinner: humanSummary.supplied ? humanSummary.winner : null,
    automaticDiagnosticLeader: autoLeader?.name ?? null,
    shippableLeader: shippableLeader?.name ?? null,
    promotionDecision: "not decided by automatic diagnostics; production promotion requires the issue's safety, meaning, human preference, and installed-runtime gates",
  },
};
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(report, null, 2) + "\n");
fs.writeFileSync(path.join(outDir, "report.md"), renderMarkdown(report, scoreBundles, outDir));

console.log(`[v2:report] engines=${names.join(", ")} cases=${corpusData.cases.length}`);
console.log(`[v2:report] automatic leader=${autoLeader?.name ?? "none"} human ratings=${humanSummary.supplied ? "supplied" : "not supplied"}`);
console.log(`[v2:report] pairwise rows=${pairwise.length} -> ${outDir}`);

function slug(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
}
function firstNumber(...values) {
  return values.find((value) => Number.isFinite(value)) ?? null;
}
function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
function isParetoEfficient(candidate, rows) {
  if (!candidate.complete || !Number.isFinite(candidate.automaticDiagnosticIndex)) return false;
  return !rows.some((other) => {
    if (other.name === candidate.name || !other.complete || !Number.isFinite(other.automaticDiagnosticIndex)) return false;
    const qualityNoWorse = other.automaticDiagnosticIndex >= candidate.automaticDiagnosticIndex;
    const memoryNoWorse = !Number.isFinite(candidate.peakMemoryGiB) || !Number.isFinite(other.peakMemoryGiB) || other.peakMemoryGiB <= candidate.peakMemoryGiB;
    const latencyNoWorse = !Number.isFinite(candidate.medianSeconds) || !Number.isFinite(other.medianSeconds) || other.medianSeconds <= candidate.medianSeconds;
    const strict = other.automaticDiagnosticIndex > candidate.automaticDiagnosticIndex ||
      (Number.isFinite(candidate.peakMemoryGiB) && Number.isFinite(other.peakMemoryGiB) && other.peakMemoryGiB < candidate.peakMemoryGiB) ||
      (Number.isFinite(candidate.medianSeconds) && Number.isFinite(other.medianSeconds) && other.medianSeconds < candidate.medianSeconds);
    return qualityNoWorse && memoryNoWorse && latencyNoWorse && strict;
  });
}
function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
function toCsv(rows) {
  if (!rows.length) return "";
  const columns = Object.keys(rows[0]);
  return [columns.join(","), ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(","))].join("\n");
}
function parseCsvLine(line) {
  const cells = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (quoted && char === '"' && line[index + 1] === '"') { current += '"'; index += 1; continue; }
    if (char === '"') { quoted = !quoted; continue; }
    if (char === "," && !quoted) { cells.push(current); current = ""; continue; }
    current += char;
  }
  cells.push(current);
  return cells;
}
function loadHumanScores(filePath) {
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];
  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => Object.fromEntries(parseCsvLine(line).map((value, index) => [headers[index], value])));
}
function summarizeHumanRatings(rows, engineNames) {
  const numericFields = ["meaningAdequacy", "coherenceCohesion", "grammarFluency", "lexicalCollocation", "editDiscipline"];
  const usable = rows.filter((row) => engineNames.includes(row.engine) && numericFields.every((field) => Number(row[field]) >= 1 && Number(row[field]) <= 5));
  const byEngine = {};
  for (const engine of engineNames) {
    const engineRows = usable.filter((row) => row.engine === engine);
    byEngine[engine] = {
      cases: engineRows.length,
      means: Object.fromEntries(numericFields.map((field) => [field, meanField(engineRows, field)])),
    };
  }
  const winner = usable.length ? [...engineNames].sort((a, b) => scoreHuman(byEngine[b]) - scoreHuman(byEngine[a]))[0] : null;
  return { supplied: usable.length > 0, rows: usable.length, byEngine, winner };
}
function meanField(rows, field) {
  if (!rows.length) return null;
  return Number((rows.reduce((sum, row) => sum + Number(row[field]), 0) / rows.length).toFixed(3));
}
function scoreHuman(summary) {
  if (!summary?.means) return -1;
  return ["meaningAdequacy", "coherenceCohesion", "grammarFluency", "lexicalCollocation", "editDiscipline"].reduce((sum, field) => sum + (summary.means[field] ?? 0), 0);
}
function renderMarkdown(payload, bundles, directory) {
  const lines = [
    "# Pari Paraphrase Quality Benchmark v2 report",
    "",
    `Generated: ${payload.generatedAt}`,
    `Corpus: ${payload.corpus.cases} cases, version ${payload.corpus.version}`,
    "",
    "## Decision boundary",
    "",
    payload.humanRatings.supplied
      ? `Human ratings supplied: ${payload.humanRatings.rows} complete engine-case rows. Provisional human leader: **${payload.decision.humanQualityWinner ?? "none"}**.`
      : "Human ratings supplied: **no**. The automatic leader below is diagnostic only; issue #11's human preference gate remains open.",
    `Automatic diagnostic leader: **${payload.decision.automaticDiagnosticLeader ?? "none"}**.`,
    `Shippable candidate with current installed evidence and zero hard-safety failures: **${payload.decision.shippableLeader ?? "none"}**.`,
    "",
    "## Automatic diagnostics",
    "",
    "| Engine | Role | Full gate | Meaning-safe | English-quality | Auto index | Hard safety failures | Median s | Peak GiB | Pareto |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ...payload.pareto.map((row) => `| ${row.name} | ${row.role} | ${formatRate(row.passRate)} | ${formatRate(row.meaningSafeRate)} | ${formatRate(row.englishQualityRate)} | ${formatNumber(row.automaticDiagnosticIndex)} | ${row.hardSafetyFailures ?? "—"} | ${formatNumber(row.medianSeconds)} | ${formatNumber(row.peakMemoryGiB)} | ${row.paretoEfficient ? "yes" : "no"} |`),
    "",
    "The automatic index combines full-gate pass rate, meaning-safe rate, English-quality rate, and the bundled learned judge's English/fluency signals. It is a reproducible diagnostic, not a human-quality score and not a promotion decision.",
    "",
    "## Runtime receipts",
    "",
    "| Engine | Model/revision | Runtime | License | Installed evidence |",
    "|---|---|---|---|:---:|",
    ...payload.automaticDiagnostics.map((row) => `| ${row.name} | ${row.modelRepo ?? "—"}${row.revision ? ` @ ${row.revision}` : ""} | ${row.runtime} | ${row.license} | ${row.installedEvidence ? "yes" : "no"} |`),
    "",
    "## Human handoff",
    "",
    `Use [pairwise-blinded.csv](pairwise-blinded.csv) for blinded A/B judgments and keep [pairwise-key.json](pairwise-key.json) separate until scoring is complete. [human-scores-template.csv](human-scores-template.csv) is the per-engine 1–5 rubric template.`,
    "",
    "## Required comparison-set status",
    "",
    "This status table prevents incomplete or unavailable required candidates from disappearing from the decision record.",
    "",
    "| Model | Status | v2 coverage | Old suite | Note |",
    "|---|---|---|---|---|",
    ...payload.modelStatus.map((row) => `| ${row.name ?? "—"} | ${row.status ?? "—"} | ${row.v2 ?? "—"} | ${row.oldSuite ?? "—"} | ${String(row.note ?? "—").replaceAll("|", "\\|")} |`),
    "",
    "## Safety and promotion",
    "",
    "Every raw output remains available through the score bundle's `results` rows. A hard-safety failure means the candidate is not eligible to win that case. No production model selection or promotion was performed by this report.",
    "",
    "## Source score bundles",
    "",
    ...bundles.map((bundle) => `- ${bundle.engine?.name ?? "engine"}: [${path.basename(bundle.outputs?.path ?? "score bundle")}](${path.relative(directory, bundle.outputs?.path ?? "")})`),
    "",
  ];
  return lines.join("\n");
}
function formatRate(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}
function formatNumber(value) {
  return Number.isFinite(value) ? Number(value).toFixed(3) : "—";
}
