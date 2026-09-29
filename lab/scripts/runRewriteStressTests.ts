#!/usr/bin/env tsx
/**
 * Rewrite Stress Test Script
 *
 * BATCHED version — collects all sentences upfront and generates via paraphraseBatch
 * so the model is loaded ONCE per model/lane combo, not once per sentence.
 *
 * Runs each paragraph from rewriteStressBank.json through:
 * 1. Protection layer
 * 2. Sentence splitting
 * 3. Model generation (all available lanes) — BATCHED
 * 4. Hard rejection + scoring
 * 5. Restoration
 *
 * Reports pass/fail per test and writes to reports/rewrite-stress-results.json
 */

import * as fs from "fs";
import * as path from "path";
import { protectText } from "../src/protection/protectText.js";
import { restoreText, validateRestoration } from "../src/protection/restoreText.js";
import { splitSentences } from "../src/sentence/splitSentences.js";
import { scoreAndRankCandidates, pickBestCandidate } from "../src/scoring/scoreCandidate.js";
import { checkHardRejection } from "../src/scoring/hardRejection.js";
import { countProfessorWords } from "../src/scoring/naturalnessPenalty.js";
import * as bridge from "../src/generation/pythonBridge.js";
import { LANE_PRESETS } from "../src/generation/generationLanes.js";
import type { StressTestResult, Candidate, ModelId, GenerationLane, CandidateScores } from "../src/core/types.js";

const REPORTS_DIR = path.resolve(import.meta.dirname, "../reports");

interface StressTestEntry {
  id: string;
  category: string;
  input: string;
  expected: Record<string, unknown>;
  notes: string;
}

interface BatchGenResult {
  sentence: string;
  candidates: string[];
  time_ms: number;
}

const VERBOSE = process.argv.includes("--verbose");
const MODELS = ["humarin/chatgpt_paraphraser_on_T5_base"] as ModelId[];
const LANES = ["conservative", "natural", "structure"] as GenerationLane[];

let candidateIdCounter = 0;
function nextCandidateId(): string {
  return `cand-${Date.now()}-${++candidateIdCounter}`;
}

/**
 * Generate ALL candidates for all sentences in one batched call per model/lane combo.
 * Returns a Map<sentence, Candidate[]>.
 */
function batchGenerate(
  sentences: string[],
  protectionText: string,
): Candidate[] {
  const allCandidates: Candidate[] = [];

  for (const model of MODELS) {
    for (const lane of LANES) {
      const laneSettings = LANE_PRESETS[lane];
      const result = bridge.paraphraseBatch(sentences, {
        model,
        lane,
      });

      if (!result.success) {
        // Return failed candidates for each sentence
        for (const sentence of sentences) {
          allCandidates.push({
            id: nextCandidateId(),
            originalSentence: sentence,
            protectedSentence: sentence,
            protectedCandidate: sentence,
            restoredCandidate: sentence,
            sourceModel: model,
            generationLane: lane,
            generationSettings: { model, lane, ...laneSettings },
            timingMs: result.timingMs,
            rejectionReason: `Python error: ${result.error ?? "unknown"}`,
            accepted: false,
            scores: null,
          });
        }
        continue;
      }

      const data = result.data as unknown as bridge.ParaphraseBatchOutput;
      const batchResults: BatchGenResult[] = data.results ?? [];

      // Map back to sentences
      for (const br of batchResults) {
        const candidateTexts: string[] = br.candidates ?? [];
        if (candidateTexts.length === 0) {
          allCandidates.push({
            id: nextCandidateId(),
            originalSentence: br.sentence,
            protectedSentence: protectionText,
            protectedCandidate: br.sentence,
            restoredCandidate: br.sentence,
            sourceModel: model,
            generationLane: lane,
            generationSettings: { model, lane, ...laneSettings },
            timingMs: br.time_ms ?? result.timingMs,
            rejectionReason: "No candidates generated",
            accepted: false,
            scores: null,
          });
        } else {
          const timePerCandidate = (br.time_ms ?? result.timingMs) / candidateTexts.length;
          for (const text of candidateTexts) {
            allCandidates.push({
              id: nextCandidateId(),
              originalSentence: br.sentence,
              protectedSentence: protectionText,
              protectedCandidate: text,
              restoredCandidate: text,
              sourceModel: model,
              generationLane: lane,
              generationSettings: { model, lane, ...laneSettings },
              timingMs: timePerCandidate,
              rejectionReason: null,
              accepted: true,
              scores: null,
            });
          }
        }
      }
    }
  }

  return allCandidates;
}

async function runTest(entry: StressTestEntry): Promise<StressTestResult> {
  const startTime = performance.now();
  const failures: string[] = [];
  const warnings: string[] = [];

  try {
    // Step 1: Protection
    const protectionStart = performance.now();
    const protection = protectText({ text: entry.input });
    const protectionMs = performance.now() - protectionStart;

    if (VERBOSE) console.log(`\n  Protection: ${protection.spans.length} spans, ${protectionMs.toFixed(0)}ms`);

    // Step 2: Sentence splitting
    const sentences = splitSentences(entry.input);
    if (VERBOSE) console.log(`  Sentences: ${sentences.length}`);

    if (sentences.length === 0) {
      return {
        testName: entry.id,
        category: entry.category,
        input: entry.input.substring(0, 80),
        candidates: [],
        acceptedCount: 0,
        passed: false,
        failures: ["No sentences found"],
        warnings: [],
        timingMs: Math.round(performance.now() - startTime),
      };
    }

    // Step 3: Batch generate candidates for ALL sentences at once
    const sentenceTexts = sentences.map(s => s.text);
    const allCandidates = batchGenerate(sentenceTexts, protection.protectedText);
    if (VERBOSE) console.log(`  Generated: ${allCandidates.length} total candidates`);

    // Step 4: Restore placeholders in candidates
    for (const candidate of allCandidates) {
      const { restored, failures: restoreFailures } = restoreText(
        candidate.protectedCandidate,
        protection.spans
      );
      candidate.restoredCandidate = restored;
      if (restoreFailures.length > 0) {
        failures.push(...restoreFailures.map((f) => `Restore: ${f}`));
      }
    }

    // Step 5: Score and rank ALL candidates together
    const { accepted, rejected } = scoreAndRankCandidates(
      allCandidates,
      protection.protectedText,
      protection.spans
    );
    if (VERBOSE) console.log(`  Accepted: ${accepted.length}, Rejected: ${rejected.length}`);

    // Step 6: Check preservation requirements
    const expected = entry.expected as Record<string, unknown>;

    // Quote preservation
    if (expected.mustPreserveQuoteExact || expected.mustNotRewriteInsideQuote) {
      const quoteText = expected.mustPreserveQuoteExact as string || "";
      for (const cand of accepted) {
        if (!cand.restoredCandidate.includes(quoteText)) {
          failures.push(`Quote not preserved: "${quoteText}"`);
        }
      }
    }

    // Number/date preservation
    const preserveNumbers = expected.mustPreserveNumbers as string[] || [];
    const preserveExact = expected.mustPreserveExact as string[] || [];
    const allMustPreserve = [...preserveNumbers, ...preserveExact];

    for (const preserve of allMustPreserve) {
      for (const cand of accepted) {
        if (!cand.restoredCandidate.includes(preserve)) {
          failures.push(`Required text not preserved: "${preserve}"`);
        }
      }
    }

    // Professor word check
    const mustNot = expected.mustNot as string[] || [];
    if (mustNot.length > 0) {
      for (const cand of accepted) {
        const profWords = countProfessorWords(cand.restoredCandidate);
        const found = profWords.words.filter((w) => mustNot.includes(w));
        if (found.length > 0) {
          warnings.push(`Professor words found: ${found.join(", ")}`);
        }
      }
    }

    // Negation preservation
    if (expected.mustPreserveNegation) {
      const originalNegations = (entry.input.match(/\b(not|never|no|n't)\b/gi) ?? []).length;
      for (const cand of accepted) {
        const candNegations = (cand.restoredCandidate.match(/\b(not|never|no|n't)\b/gi) ?? []).length;
        if (originalNegations > 0 && candNegations === 0) {
          failures.push("Negation was removed");
        }
        if (originalNegations === 0 && candNegations > 1) {
          failures.push("Negation was added");
        }
      }
    }

    // Check hard rejection rules
    for (const cand of allCandidates) {
      const rejection = checkHardRejection(cand, protection.protectedText, protection.spans);
      if (rejection) {
        failures.push(`Hard rejection: ${rejection} for candidate ${cand.id}`);
      }
    }

    // Minimum acceptance by category
    const category = entry.category;
    let minAccepted = 1;
    if (category === "easy") minAccepted = 3;
    else if (category === "medium") minAccepted = 2;
    else if (category === "hard" || category === "insane") minAccepted = 1;

    if (accepted.length < minAccepted) {
      failures.push(`Only ${accepted.length} accepted candidates (expected ≥${minAccepted})`);
    }

  } catch (err) {
    failures.push(`Test error: ${err instanceof Error ? err.message : String(err)}`);
  }

  const elapsedMs = performance.now() - startTime;

  return {
    testName: entry.id,
    category: entry.category,
    input: entry.input.substring(0, 80),
    candidates: [],
    acceptedCount: 0,
    passed: failures.length === 0,
    failures,
    warnings,
    timingMs: Math.round(elapsedMs),
  };
}

async function main() {
  console.log("=== Rewrite Stress Tests (BATCHED) ===");
  console.log();

  const stressBankPath = path.resolve(import.meta.dirname, "../tests/rewriteStressBank.json");
  const tests: StressTestEntry[] = JSON.parse(fs.readFileSync(stressBankPath, "utf-8"));

  console.log(`Running ${tests.length} stress tests with batched generation...\n`);

  const results: StressTestResult[] = [];
  let passed = 0;
  let failed = 0;

  for (const test of tests) {
    process.stdout.write(`  ${test.id.padEnd(20)} (${test.category.padEnd(12)})... `);
    const result = await runTest(test);
    results.push(result);

    if (result.passed) {
      console.log("PASS");
      passed++;
    } else {
      console.log("FAIL");
      failed++;
      if (result.failures.length > 0) {
        for (const f of result.failures.slice(0, 3)) {
          console.log(`    ✗ ${f}`);
        }
      }
      if (result.warnings.length > 0) {
        for (const w of result.warnings.slice(0, 2)) {
          console.log(`    ⚠ ${w}`);
        }
      }
    }
  }

  // Summary
  const total = tests.length;
  const passRate = total > 0 ? (passed / total * 100).toFixed(0) : "0";

  console.log(`\n=== Results: ${passed}/${total} passed (${passRate}%) ===`);

  // Write report
  if (!fs.existsSync(REPORTS_DIR)) {
    fs.mkdirSync(REPORTS_DIR, { recursive: true });
  }

  const reportPath = path.join(REPORTS_DIR, "rewrite-stress-results.json");
  const report = {
    timestamp: new Date().toISOString(),
    total: total,
    passed,
    failed,
    passRate: `${passRate}%`,
    results,
    testBank: stressBankPath,
  };

  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
  console.log(`Report written to ${reportPath}`);
}

main().catch(console.error);
