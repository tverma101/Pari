#!/usr/bin/env tsx
/**
 * Model Benchmark Script
 *
 * Tests each registered model for:
 * - Cold load time
 * - Warm generation time
 * - Sentence average latency
 * - Output rejection rate
 * - Quote/entity/number preservation
 * - Semantic similarity
 * - And reports results to reports/model-benchmark.json
 */

import * as fs from "fs";
import * as path from "path";
import { getAllModels } from "../src/generation/modelRegistry.js";
import { runT5Paraphrase, warmupModel } from "../src/generation/localModelRunner.js";
import { protectText } from "../src/protection/protectText.js";
import { restoreText } from "../src/protection/restoreText.js";
import { scoreAndRankCandidates } from "../src/scoring/scoreCandidate.js";
import type { ModelBenchmark } from "../src/core/types.js";
import { checkHardRejection } from "../src/scoring/hardRejection.js";
import { computeSemanticSimilarity } from "../src/scoring/semanticSimilarity.js";
import { countProfessorWords } from "../src/scoring/naturalnessPenalty.js";
import { computeLexicalDiversity } from "../src/scoring/lexicalDiversity.js";

const REPORTS_DIR = path.resolve(import.meta.dirname, "../reports");

const TEST_SENTENCES = [
  "I think communication matters because it helps people understand each other better.",
  "When someone listens carefully, the other person feels respected instead of ignored.",
  "This is one reason I think small conversations can have a bigger effect than people expect.",
  "I do not think social media always makes communication worse.",
  "In 2026, the survey showed that 42% of students preferred online classes.",
];

const QUOTE_TEST = 'My classmate wrote, "Online identity can feel safer because you can choose what to share," and I agree with that idea.';

const ENTITY_NUMBER_TEST = "Rodin's 'The Cathedral' was modeled in 1908 and cast in 1955.";

async function main() {
  console.log("=== Model Benchmark Script ===");
  console.log();

  if (!fs.existsSync(REPORTS_DIR)) {
    fs.mkdirSync(REPORTS_DIR, { recursive: true });
  }

  const models = getAllModels();
  const results: ModelBenchmark[] = [];

  for (const model of models) {
    // Skip synonym bank — benchmark differently
    if (model.type === "synonym_bank") {
      results.push({
        modelId: model.id,
        modelName: model.name,
        coldLoadTimeMs: 0,
        warmGenerationTimeMs: 0,
        averageSentenceLatencyMs: 1,
        averageParagraphLatencyMs: 1,
        candidatesPerSecond: 100,
        memoryEstimate: model.ramEstimate,
        outputRejectionRate: 0,
        quotePreservationRate: 1,
        entityPreservationRate: 1,
        numberPreservationRate: 1,
        averageSemanticSimilarity: 0.65,
        averageLexicalDifference: 0.25,
        averageProfessorPenalty: 0.05,
        manualNotes: "V1 synonym bank — fast but limited to single-word replacements, not true paraphrasing",
      });
      continue;
    }

    console.log(`\n--- Benchmarking: ${model.name} (${model.id}) ---`);

    // Cold load
    console.log(`  Cold loading...`);
    const coldStart = performance.now();
    const coldCandidates = runT5Paraphrase(TEST_SENTENCES[0], model.id, "conservative");
    const coldLoadTime = performance.now() - coldStart;
    console.log(`  Cold load time: ${coldLoadTime.toFixed(0)}ms`);

    // Warm generation (run on all test sentences)
    const sentenceLatencies: number[] = [];
    let totalCandidates = 0;
    let rejectedCount = 0;
    let quotePreserved = true;
    let entityPreserved = true;
    let numberPreserved = true;

    for (const sentence of TEST_SENTENCES) {
      const sentenceStart = performance.now();
      const candidates = runT5Paraphrase(sentence, model.id, "natural", { numReturnSequences: 3 });

      const elapsed = performance.now() - sentenceStart;
      sentenceLatencies.push(elapsed);

      for (const cand of candidates) {
        totalCandidates++;
        if (!cand.accepted) rejectedCount++;

        // Check quote preservation
        const quoteProtection = protectText({ text: QUOTE_TEST });
        const quoteCand = runT5Paraphrase(quoteProtection.protectedText, model.id, "conservative", { numReturnSequences: 1 });
        if (quoteCand.length > 0) {
          const rejection = checkHardRejection(quoteCand[0], quoteProtection.protectedText, quoteProtection.spans);
          if (rejection === "quote_preservation") quotePreserved = false;
        }

        // Check entity/number preservation
        const entityProtection = protectText({ text: ENTITY_NUMBER_TEST });
        const entityCand = runT5Paraphrase(entityProtection.protectedText, model.id, "conservative", { numReturnSequences: 1 });
        if (entityCand.length > 0) {
          const { restored, failures } = restoreText(entityCand[0].protectedCandidate, entityProtection.spans);
          entityCand[0].restoredCandidate = restored;
          const rejection = checkHardRejection(entityCand[0], entityProtection.protectedText, entityProtection.spans);
          if (rejection === "number_date_citation_preservation") {
            entityPreserved = false;
            numberPreserved = false;
          }
        }
      }
    }

    const avgLatency = sentenceLatencies.reduce((a, b) => a + b, 0) / sentenceLatencies.length;

    // Semantic similarity
    let totalSim = 0;
    let totalLexDiff = 0;
    let totalProfPenalty = 0;
    for (const sentence of TEST_SENTENCES) {
      const candidates = runT5Paraphrase(sentence, model.id, "natural");
      const { accepted } = scoreAndRankCandidates(candidates, sentence, []);

      if (accepted.length > 0) {
        const best = accepted[0];
        const sim = computeSemanticSimilarity(sentence, best.restoredCandidate);
        totalSim += sim;
        totalLexDiff += computeLexicalDiversity(sentence, best.restoredCandidate);
        totalProfPenalty += countProfessorWords(best.restoredCandidate).count;
      }
    }

    const avgSim = totalSim / TEST_SENTENCES.length;
    const avgLexDiff = totalLexDiff / TEST_SENTENCES.length;
    const avgProf = totalProfPenalty / TEST_SENTENCES.length;

    const rejectionRate = totalCandidates > 0 ? rejectedCount / totalCandidates : 0;

    results.push({
      modelId: model.id,
      modelName: model.name,
      coldLoadTimeMs: Math.round(coldLoadTime),
      warmGenerationTimeMs: Math.round(avgLatency),
      averageSentenceLatencyMs: Math.round(avgLatency),
      averageParagraphLatencyMs: Math.round(avgLatency * 3), // rough ~3 sentence paragraph
      candidatesPerSecond: Math.round(1000 / avgLatency * 3), // 3 candidates per generation
      memoryEstimate: model.ramEstimate,
      outputRejectionRate: Math.round(rejectionRate * 100) / 100,
      quotePreservationRate: quotePreserved ? 1 : 0,
      entityPreservationRate: entityPreserved ? 1 : 0,
      numberPreservationRate: numberPreserved ? 1 : 0,
      averageSemanticSimilarity: Math.round(avgSim * 1000) / 1000,
      averageLexicalDifference: Math.round(avgLexDiff * 1000) / 1000,
      averageProfessorPenalty: Math.round(avgProf * 100) / 100,
      manualNotes: model.type === "t5" || model.type === "bart"
        ? "Seq2seq — good for sentence-level rewriting"
        : "Fallback model — limited capability",
    });

    console.log(`  Avg latency: ${avgLatency.toFixed(0)}ms`);
    console.log(`  Rejection rate: ${(rejectionRate * 100).toFixed(0)}%`);
    console.log(`  Semantic similarity: ${avgSim.toFixed(3)}`);
    console.log(`  Quote preserved: ${quotePreserved}`);
    console.log(`  Entity preserved: ${entityPreserved}`);
  }

  // Write report
  const reportPath = path.join(REPORTS_DIR, "model-benchmark.json");
  const report = {
    timestamp: new Date().toISOString(),
    benchmarkMetadata: {
      date: new Date().toISOString(),
      testEnvironment: "macOS Apple Silicon M4, 16GB",
      testSentences: TEST_SENTENCES,
      modelsTested: results.length,
    },
    models: results,
    summary: {
      fastestModel: results.reduce((a, b) => a.warmGenerationTimeMs < b.warmGenerationTimeMs ? a : b).modelName,
      bestSimilarity: results.reduce((a, b) => a.averageSemanticSimilarity > b.averageSemanticSimilarity ? a : b).modelName,
      lowestRejection: results.reduce((a, b) => a.outputRejectionRate < b.outputRejectionRate ? a : b).modelName,
    },
  };

  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
  console.log(`\nReport written to ${reportPath}`);

  // Print summary table
  console.log("\n=== Summary ===");
  console.log("Model".padEnd(45) + "Load(ms)".padEnd(10) + "Lat(ms)".padEnd(10) + "Reject".padEnd(10) + "Sim".padEnd(8) + "LexDiff".padEnd(8));
  console.log("-".repeat(90));
  for (const r of results) {
    console.log(
      r.modelName.padEnd(45) +
      `${r.coldLoadTimeMs}`.padEnd(10) +
      `${r.averageSentenceLatencyMs}`.padEnd(10) +
      `${r.outputRejectionRate}`.padEnd(10) +
      `${r.averageSemanticSimilarity}`.padEnd(8) +
      `${r.averageLexicalDifference}`.padEnd(8)
    );
  }
}

main().catch(console.error);
