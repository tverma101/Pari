#!/usr/bin/env node
/** Build a blinded, item-level human meaning-preservation audit from v2 score bundles. */
import crypto from "crypto";
import fs from "fs";
import path from "path";
import {
  DEFAULT_CORPUS_PATH,
  loadV2Corpus,
  loadV2Sources,
  resolveRepoPath,
  ROOT_DIR,
  validateV2Corpus,
} from "./schema.mjs";

const args = process.argv.slice(2);

function values(flag) {
  const found = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === flag && args[index + 1]) found.push(args[index + 1]);
  }
  return found;
}

function argValue(flag) {
  return values(flag)[0];
}

const scorePaths = values("--scores")
  .flatMap((value) => value.split(","))
  .filter(Boolean)
  .map((value) => path.resolve(value));

if (scorePaths.length < 1) {
  throw new Error(
    "usage: node benchmarks/paraphrase-v2/meaning-audit.mjs --scores <score.json> [--scores <score.json>] [--out-dir <dir>] [--ratings <completed.csv>]",
  );
}

const corpusPath = resolveRepoPath(argValue("--corpus"), DEFAULT_CORPUS_PATH);
const corpus = loadV2Corpus(corpusPath);
const validation = validateV2Corpus(corpus, loadV2Sources());
if (!validation.valid) throw new Error(`v2 corpus is invalid: ${validation.errors.join("; ")}`);

const bundles = scorePaths.map((filePath) => JSON.parse(fs.readFileSync(filePath, "utf8")));
const engineNames = bundles.map((bundle, index) => String(bundle.engine?.name ?? `engine-${index + 1}`));
if (new Set(engineNames).size !== engineNames.length) {
  throw new Error(`score bundles must have unique engine names: ${engineNames.join(", ")}`);
}

const outDir = path.resolve(
  argValue("--out-dir") ?? path.join(ROOT_DIR, "benchmarks/paraphrase-v2/results/meaning-audit"),
);
fs.mkdirSync(outDir, { recursive: true });

const key = {};
const rows = [];

for (const [engineIndex, bundle] of bundles.entries()) {
  const engine = engineNames[engineIndex];
  const outputByCase = new Map((bundle.results ?? []).map((row) => [row.id, row.output ?? ""]));

  for (const item of corpus.cases) {
    const auditId = `audit-${hash(`${item.id}--${engine}`).slice(0, 12)}`;
    key[auditId] = {
      engine,
      caseId: item.id,
      expectedItems: item.mustPreserve.length,
    };
    const candidateText = String(outputByCase.get(item.id) ?? "");

    for (const [itemIndex, mustPreserve] of item.mustPreserve.entries()) {
      rows.push({
        auditId,
        caseId: item.id,
        category: item.category,
        sourceText: item.input,
        candidateText,
        preserveItem: itemIndex + 1,
        mustPreserve,
        preserved: "",
        contradicted: "",
        notes: "",
      });
    }
  }
}

// Keep engine identity blinded while avoiding a predictable engine-by-engine
// ordering that could let a rater infer which rows belong to the same system.
rows.sort((left, right) =>
  hash(`${left.auditId}:${left.preserveItem}`).localeCompare(hash(`${right.auditId}:${right.preserveItem}`)),
);

const sheetPath = path.join(outDir, "meaning-audit-blinded.csv");
const keyPath = path.join(outDir, "meaning-audit-key.json");
fs.writeFileSync(sheetPath, toCsv(rows) + "\n");
fs.writeFileSync(
  keyPath,
  JSON.stringify(
    {
      warning: "Keep this file separate from meaning-audit-blinded.csv until ratings are complete.",
      ratings: {
        preserved: ["Y", "N", "UNCLEAR"],
        contradicted: ["Y", "N"],
      },
      audits: key,
    },
    null,
    2,
  ) + "\n",
);

const ratingsPath = argValue("--ratings");
if (ratingsPath) {
  const ratings = loadCsv(path.resolve(ratingsPath));
  const summary = summarizeRatings(ratings, key, engineNames);
  fs.writeFileSync(path.join(outDir, "meaning-audit-summary.json"), JSON.stringify(summary, null, 2) + "\n");
  fs.writeFileSync(path.join(outDir, "meaning-audit-summary.md"), renderSummary(summary));
}

console.log(`[v2:meaning-audit] engines=${engineNames.join(", ")} cases=${corpus.cases.length} items=${rows.length}`);
console.log(`[v2:meaning-audit] blinded sheet -> ${sheetPath}`);
if (ratingsPath) console.log(`[v2:meaning-audit] ratings summarized -> ${outDir}`);

function hash(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function toCsv(items) {
  if (!items.length) return "";
  const columns = Object.keys(items[0]);
  return [
    columns.join(","),
    ...items.map((item) => columns.map((column) => csvCell(item[column])).join(",")),
  ].join("\n");
}

function parseCsv(text) {
  const records = [];
  let record = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      record.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      record.push(field);
      field = "";
      if (record.some((cell) => cell.length > 0)) records.push(record);
      record = [];
    } else {
      field += char;
    }
  }

  if (field.length > 0 || record.length > 0) {
    record.push(field);
    if (record.some((cell) => cell.length > 0)) records.push(record);
  }
  if (quoted) throw new Error("Unterminated quoted field in ratings CSV");
  if (!records.length) return [];

  const headers = records[0];
  return records.slice(1).map((cells) =>
    Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""])),
  );
}

function loadCsv(filePath) {
  return parseCsv(fs.readFileSync(filePath, "utf8"));
}

function normalizePreserved(value) {
  const normalized = String(value ?? "").trim().toUpperCase();
  return ["Y", "N", "UNCLEAR"].includes(normalized) ? normalized : null;
}

function normalizeBinary(value) {
  const normalized = String(value ?? "").trim().toUpperCase();
  return ["Y", "N"].includes(normalized) ? normalized : null;
}

function summarizeRatings(ratings, auditKey, names) {
  const byEngine = Object.fromEntries(names.map((name) => [name, emptySummary()]));
  const caseItems = new Map();
  const seenRows = new Set();
  let ignoredRows = 0;

  for (const row of ratings) {
    const audit = auditKey[row.auditId];
    const itemIndex = Number(row.preserveItem);
    const rowKey = `${row.auditId}:${row.preserveItem}`;
    if (
      !audit ||
      !byEngine[audit.engine] ||
      !Number.isInteger(itemIndex) ||
      itemIndex < 1 ||
      itemIndex > audit.expectedItems ||
      seenRows.has(rowKey)
    ) {
      ignoredRows += 1;
      continue;
    }
    seenRows.add(rowKey);

    const preserved = normalizePreserved(row.preserved);
    const contradicted = normalizeBinary(row.contradicted);
    const target = byEngine[audit.engine];

    target.totalRows += 1;
    if (preserved) {
      target.preservationRatings += 1;
      if (preserved === "Y") target.preserved += 1;
      if (preserved === "N") target.missing += 1;
      if (preserved === "UNCLEAR") target.unclear += 1;
    }
    if (contradicted) {
      target.contradictionRatings += 1;
      if (contradicted === "Y") target.contradicted += 1;
    }

    const caseKey = `${audit.engine}::${audit.caseId}`;
    if (!caseItems.has(caseKey)) caseItems.set(caseKey, new Map());
    caseItems.get(caseKey).set(itemIndex, { preserved, contradicted });
  }

  for (const [caseKey, items] of caseItems.entries()) {
    const separator = caseKey.indexOf("::");
    const engine = caseKey.slice(0, separator);
    const caseId = caseKey.slice(separator + 2);
    const target = byEngine[engine];
    const audit = Object.values(auditKey).find((entry) => entry.engine === engine && entry.caseId === caseId);
    const expectedItems = audit?.expectedItems ?? 0;
    const itemValues = [...items.values()];
    const fullyRated =
      expectedItems > 0 &&
      items.size === expectedItems &&
      itemValues.every((item) => item.preserved && item.contradicted);
    if (!fullyRated) continue;

    target.completeCases += 1;
    if (itemValues.every((item) => item.preserved === "Y" && item.contradicted === "N")) {
      target.fullPreservationCases += 1;
    }
  }

  for (const target of Object.values(byEngine)) {
    target.preservationRate = rate(target.preserved, target.preservationRatings);
    target.contradictionRate = rate(target.contradicted, target.contradictionRatings);
    target.fullPreservationCaseRate = rate(target.fullPreservationCases, target.completeCases);
  }

  return {
    schemaVersion: 1,
    benchmark: "pari-paraphrase-v2-human-meaning-audit",
    generatedAt: new Date().toISOString(),
    ignoredRows,
    byEngine,
    interpretation: {
      preservationRate: "Share of rated mustPreserve items judged explicitly retained.",
      contradictionRate: "Share of rated items judged contradicted by the candidate.",
      fullPreservationCaseRate: "Share of completely rated cases where every expected mustPreserve item was retained and none was contradicted.",
      ignoredRows: "Rows ignored because the audit id/item index was invalid or duplicated.",
      promotionUse: "Diagnostic human evidence. Do not replace blinded pairwise preference, grammar/fluency review, or hard-safety gates with this score alone.",
    },
  };
}

function emptySummary() {
  return {
    totalRows: 0,
    preservationRatings: 0,
    preserved: 0,
    missing: 0,
    unclear: 0,
    contradictionRatings: 0,
    contradicted: 0,
    completeCases: 0,
    fullPreservationCases: 0,
    preservationRate: null,
    contradictionRate: null,
    fullPreservationCaseRate: null,
  };
}

function rate(numerator, denominator) {
  if (!denominator) return null;
  return Number((numerator / denominator).toFixed(4));
}

function renderSummary(summary) {
  const lines = [
    "# Pari v2 human meaning audit",
    "",
    `Generated: ${summary.generatedAt}`,
    `Ignored malformed/duplicate rating rows: ${summary.ignoredRows}`,
    "",
    "| Engine | Preservation | Contradiction | Fully preserved cases | Rated items | Complete cases |",
    "|---|---:|---:|---:|---:|---:|",
    ...Object.entries(summary.byEngine).map(([engine, row]) =>
      `| ${engine} | ${formatRate(row.preservationRate)} | ${formatRate(row.contradictionRate)} | ${formatRate(row.fullPreservationCaseRate)} | ${row.preservationRatings} | ${row.completeCases} |`,
    ),
    "",
    "This audit measures item-level recoverable meaning from the corpus `mustPreserve` anchors. It is supporting human evidence, not a standalone promotion score.",
    "",
  ];
  return lines.join("\n");
}

function formatRate(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}
