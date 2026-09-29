#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = JSON.parse(
  fs.readFileSync(path.join(ROOT_DIR, "benchmarks/paraphrase-v2/corpus.json"), "utf8"),
);
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "pari-meaning-audit-"));
const outDir = path.join(tempDir, "out");
const auditScript = path.join(ROOT_DIR, "benchmarks/paraphrase-v2/meaning-audit.mjs");

try {
  const engines = ["fixture-a", "fixture-b"];
  const scorePaths = engines.map((engine) => {
    const filePath = path.join(tempDir, `${engine}.scored.json`);
    fs.writeFileSync(
      filePath,
      JSON.stringify({
        engine: { name: engine },
        results: corpus.cases.map((item) => ({ id: item.id, output: item.input })),
      }),
    );
    return filePath;
  });

  execFileSync(
    process.execPath,
    [
      auditScript,
      "--scores", scorePaths[0],
      "--scores", scorePaths[1],
      "--out-dir", outDir,
    ],
    { cwd: ROOT_DIR, stdio: "pipe" },
  );

  const keyPath = path.join(outDir, "meaning-audit-key.json");
  const sheetPath = path.join(outDir, "meaning-audit-blinded.csv");
  assert(fs.existsSync(keyPath), "meaning audit did not emit its blinded key");
  assert(fs.existsSync(sheetPath), "meaning audit did not emit its blinded sheet");

  const key = JSON.parse(fs.readFileSync(keyPath, "utf8"));
  const auditEntries = Object.entries(key.audits);
  assert.equal(
    auditEntries.length,
    corpus.cases.length * engines.length,
    "meaning audit key does not contain exactly one candidate per engine/case",
  );
  assert(
    auditEntries.every(([, meta]) => Number.isInteger(meta.expectedItems) && meta.expectedItems > 0),
    "meaning audit key is missing expected mustPreserve item counts",
  );

  const [omittedAuditId, omittedAudit] = auditEntries[0];
  const ratingsRows = [];
  for (const [auditId, meta] of auditEntries) {
    for (let item = 1; item <= meta.expectedItems; item += 1) {
      if (auditId === omittedAuditId && item === meta.expectedItems) continue;
      ratingsRows.push({ auditId, preserveItem: item, preserved: "Y", contradicted: "N" });
    }
  }

  // These rows must be ignored rather than inflating totals or case completeness.
  const [duplicateAuditId, duplicateAudit] = auditEntries[1];
  ratingsRows.push({ auditId: duplicateAuditId, preserveItem: 1, preserved: "Y", contradicted: "N" });
  ratingsRows.push({
    auditId: duplicateAuditId,
    preserveItem: duplicateAudit.expectedItems + 1,
    preserved: "Y",
    contradicted: "N",
  });

  const ratingsPath = path.join(tempDir, "ratings.csv");
  fs.writeFileSync(
    ratingsPath,
    [
      "auditId,preserveItem,preserved,contradicted",
      ...ratingsRows.map((row) => `${row.auditId},${row.preserveItem},${row.preserved},${row.contradicted}`),
    ].join("\n") + "\n",
  );

  execFileSync(
    process.execPath,
    [
      auditScript,
      "--scores", scorePaths[0],
      "--scores", scorePaths[1],
      "--ratings", ratingsPath,
      "--out-dir", outDir,
    ],
    { cwd: ROOT_DIR, stdio: "pipe" },
  );

  const summary = JSON.parse(
    fs.readFileSync(path.join(outDir, "meaning-audit-summary.json"), "utf8"),
  );
  assert.equal(summary.ignoredRows, 2, "duplicate/out-of-range audit rows were not ignored");

  for (const engine of engines) {
    const expectedCompleteCases = corpus.cases.length - (engine === omittedAudit.engine ? 1 : 0);
    assert.equal(
      summary.byEngine[engine].completeCases,
      expectedCompleteCases,
      `${engine}: partially rated case was counted as complete`,
    );
    assert.equal(
      summary.byEngine[engine].fullPreservationCases,
      expectedCompleteCases,
      `${engine}: fully preserved fixture cases were summarized incorrectly`,
    );
    assert.equal(
      summary.byEngine[engine].fullPreservationCaseRate,
      1,
      `${engine}: all completely rated identity rewrites should have 100% full preservation`,
    );
    assert.equal(
      summary.byEngine[engine].contradictionRate,
      0,
      `${engine}: identity rewrites should have zero human-marked contradictions`,
    );
  }

  console.log("qa:meaning-audit passed");
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}
