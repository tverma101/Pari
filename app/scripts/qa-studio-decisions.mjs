import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  appendStudioDecision,
  clearInMemoryDecisions,
  exportSavedDecisionsToJsonl,
  getDefaultDecisionLogPath,
  hashParagraph,
  markParagraphSavedInLog,
} from "../src/lib/persistence/decisionLogger.ts";

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "pari-decision-qa-"));
const testLogPath = path.join(tmpDir, "studio-decisions.jsonl");
const exportPath = path.join(tmpDir, "exported-decisions.jsonl");

try {
  clearInMemoryDecisions();

  const para1 = "Artificial intelligence helps researchers write more clearly.";
  const hash1 = hashParagraph(para1);

  // 1. Record an unsaved choice in paragraph 1
  appendStudioDecision({
    id: "dec-1",
    paragraphId: "para-1",
    paragraphHash: hash1,
    saved: false,
    selectionText: "more clearly",
    selectionRange: { start: 47, end: 59 },
    operation: "alternatives",
    optionsShown: ["with greater clarity", "more effectively", "with ease"],
    optionPicked: "with greater clarity",
    optionsSkipped: ["more effectively", "with ease"],
    modelId: "qwen3-4b",
    adapterId: null,
    timestamp: new Date().toISOString(),
  }, testLogPath);

  // 2. Record an unsaved choice in paragraph 2 (which the user later discards)
  const para2 = "This is a draft that will not be saved.";
  const hash2 = hashParagraph(para2);
  appendStudioDecision({
    id: "dec-2",
    paragraphId: "para-2",
    paragraphHash: hash2,
    saved: false,
    selectionText: "will not be saved",
    selectionRange: { start: 15, end: 32 },
    operation: "shorter",
    optionsShown: ["won't be kept", "is discarded"],
    optionPicked: "is discarded",
    optionsSkipped: ["won't be kept"],
    modelId: "qwen3-4b",
    adapterId: null,
    timestamp: new Date().toISOString(),
  }, testLogPath);

  // 3. User saves paragraph 1 only
  const finalPara1 = "Artificial intelligence helps researchers write with greater clarity.";
  const updated = markParagraphSavedInLog("para-1", hash1, para1, finalPara1, testLogPath);
  assert.equal(updated, 1, "Expected 1 decision in para-1 to be marked saved");

  // 4. Export saved decisions
  const exportRes = exportSavedDecisionsToJsonl(exportPath, testLogPath);
  assert.equal(exportRes.exportedCount, 1, "Only decisions in saved paragraphs must be exported");

  // Verify exported JSONL content
  const exportedLines = fs.readFileSync(exportPath, "utf8").trim().split("\n");
  assert.equal(exportedLines.length, 1);
  const exportedItem = JSON.parse(exportedLines[0]);
  assert.equal(exportedItem.id, "dec-1");
  assert.equal(exportedItem.saved, true);
  assert.equal(exportedItem.originalParagraph, para1);
  assert.equal(exportedItem.finalParagraph, finalPara1);
  assert.equal(exportedItem.optionPicked, "with greater clarity");

  console.log("qa:studio-decisions passed");
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true });
}
