/**
 * Open Local Phraser v1 - Safe Rewrite Lab
 * Backend-first paraphrase engine with protection, multi-lane generation,
 * scoring, preferences, and alternatives.
 *
 * Main entry point.
 */

import type { RewriteRequest, RewriteResult, Candidate, SentenceSpan, ProtectedSpan, GenerationLane, ModelId } from "./types.js";
import { protectText } from "../protection/protectText.js";
import { restoreText, validateRestoration } from "../protection/restoreText.js";
import { splitSentences } from "../sentence/splitSentences.js";
import { runT5Paraphrase, runMultiLaneGeneration } from "../generation/localModelRunner.js";
import { scoreAndRankCandidates, pickBestCandidate } from "../scoring/scoreCandidate.js";
import { getWordAlternatives } from "../alternatives/getWordAlternatives.js";
import { getBankAlternatives } from "../alternatives/synonymSources.js";
import { recordFeedback } from "../preferences/feedbackStore.js";

export type { AlternativesResult, TokenAlternative } from "../core/types.js";

/**
 * Rewrite a full paragraph with protection, generation, scoring, and ranking.
 */
export function rewriteParagraph(request: RewriteRequest): RewriteResult {
  const startTime = performance.now();
  const warnings: string[] = [];

  // Step 1: Protection
  const protStart = performance.now();
  const protection = protectText({ text: request.text });
  const protectionMs = performance.now() - protStart;

  // Step 2: Sentence splitting
  const splitStart = performance.now();
  const sentences = splitSentences(protection.protectedText);
  const sentenceSplittingMs = performance.now() - splitStart;

  if (sentences.length === 0) {
    return {
      originalText: request.text,
      protectedText: protection.protectedText,
      restoredText: request.text,
      sentences: [],
      candidates: [],
      acceptedCandidates: [],
      bestCandidate: null,
      timing: {
        protectionMs,
        sentenceSplittingMs,
        generationMs: 0,
        scoringMs: 0,
        totalMs: performance.now() - startTime,
      },
      protection,
      warnings: ["No sentences found"],
    };
  }

  // Step 3: Generate candidates per sentence
  const genStart = performance.now();
  const allCandidates: Candidate[] = [];
  const models: ModelId[] = request.model ? [request.model as ModelId] : ["humarin/chatgpt_paraphraser_on_T5_base"];
  const lanes: GenerationLane[] = request.lane ? [request.lane as GenerationLane] : ["conservative", "natural", "structure"];

  for (const sentence of sentences) {
    // Treat the protected text as the source for generation
    const candidates = runMultiLaneGeneration(sentence.text, models, lanes);
    allCandidates.push(...candidates);
  }
  const generationMs = performance.now() - genStart;

  // Step 4: Restore placeholders in candidates
  for (const candidate of allCandidates) {
    const { restored, failures } = restoreText(candidate.protectedCandidate, protection.spans);
    candidate.restoredCandidate = restored;
    if (failures.length > 0) {
      warnings.push(...failures.map((f) => `Restoration failure: ${f}`));
    }
  }

  // Step 5: Score and rank
  const scoringStart = performance.now();
  const { accepted, rejected } = scoreAndRankCandidates(
    allCandidates,
    protection.protectedText,
    protection.spans
  );
  const scoringMs = performance.now() - scoringStart;

  // Step 6: Pick best
  const best = pickBestCandidate(accepted);

  // Restore the full protected text for the final output
  const finalRestore = restoreText(protection.protectedText, protection.spans);

  const totalMs = performance.now() - startTime;

  return {
    originalText: request.text,
    protectedText: protection.protectedText,
    restoredText: finalRestore.restored,
    sentences,
    candidates: allCandidates,
    acceptedCandidates: accepted,
    bestCandidate: best,
    timing: {
      protectionMs,
      sentenceSplittingMs,
      generationMs,
      scoringMs,
      totalMs,
    },
    protection,
    warnings,
  };
}

/**
 * Rewrite a single sentence (convenience wrapper).
 */
export function rewriteSentence(
  sentence: string,
  options: {
    model?: string;
    lane?: string;
  } = {}
): Candidate[] {
  const protection = protectText({ text: sentence });
  const models: ModelId[] = options.model ? [options.model as ModelId] : ["humarin/chatgpt_paraphraser_on_T5_base"];
  const lanes: GenerationLane[] = options.lane ? [options.lane as GenerationLane] : ["conservative", "natural"];

  const candidates = runMultiLaneGeneration(protection.protectedText, models, lanes);

  // Restore placeholders
  for (const candidate of candidates) {
    const { restored } = restoreText(candidate.protectedCandidate, protection.spans);
    candidate.restoredCandidate = restored;
  }

  // Score
  const { accepted } = scoreAndRankCandidates(candidates, protection.protectedText, protection.spans);
  return accepted;
}

/**
 * Get word alternatives (the "tap on a word" API).
 */
export function getAlternatives(
  sentence: string,
  tokenIndex: number,
  options: {
    mode?: string;
    protectedSpans?: ProtectedSpan[];
    preferenceProfile?: { id: string; name: string };
  } = {}
) {
  return getWordAlternatives(
    sentence,
    tokenIndex,
    options.protectedSpans ?? [],
    {
      preferenceProfile: null, // Would need to resolve from profile id
      minAlternatives: 30,
    }
  );
}

/**
 * Submit feedback on a rewrite.
 */
export function submitFeedback(
  type: string,
  originalText: string,
  candidateText: string,
  metadata?: Record<string, unknown>
): void {
  recordFeedback(
    type as Parameters<typeof recordFeedback>[0],
    originalText,
    candidateText,
    metadata
  );
}

/**
 * Benchmark a model by running timed generations.
 */
export function benchmarkModel(
  model: string,
  testSentences: string[]
): Promise<Record<string, unknown>> {
  const results: Record<string, unknown>[] = [];
  const overallStart = performance.now();

  for (const sentence of testSentences) {
    const sentenceStart = performance.now();
    const candidates = runT5Paraphrase(sentence, model, "natural");
    const elapsed = performance.now() - sentenceStart;

    results.push({
      sentence: sentence.substring(0, 60),
      candidatesCount: candidates.length,
      acceptedCount: candidates.filter((c) => c.accepted).length,
      timingMs: elapsed,
      candidates: candidates.map((c) => ({
        text: c.restoredCandidate.substring(0, 80),
        lane: c.generationLane,
        accepted: c.accepted,
        rejectionReason: c.rejectionReason,
      })),
    });
  }

  return Promise.resolve({
    model,
    totalTimeMs: performance.now() - overallStart,
    sentences: results,
    averageMsPerSentence: results.length > 0
      ? results.reduce((sum, r) => sum + (r.timingMs as number), 0) / results.length
      : 0,
  });
}

console.log("=== Open Local Phraser v1 — Safe Rewrite Lab ===");
console.log("Available functions:");
console.log("  rewriteParagraph(request)");
console.log("  rewriteSentence(text, options)");
console.log("  getAlternatives(sentence, tokenIndex)");
console.log("  submitFeedback(type, original, candidate)");
console.log("  benchmarkModel(model, testSentences)");

// Self-test on load
if (process.argv[1]?.includes("index.ts")) {
  const testText = "I think communication matters because it helps people understand each other better.";
  console.log("\n=== Self-test ===");
  console.log("Testing protection on:", testText);

  const protection = protectText({ text: testText });
  console.log(`Protected: ${protection.protectedText}`);
  console.log(`Spans found: ${protection.spans.length}`);

  const sentences = splitSentences(protection.protectedText);
  console.log(`Sentences: ${sentences.length}`);

  if (process.argv.includes("--benchmark")) {
    console.log("\n=== Benchmark mode ===");
    console.log("This would benchmark models (requires Python + models installed)");
  }
}

export { protectText, restoreText, validateRestoration } from "../protection/index.js";
export { splitSentences } from "../sentence/splitSentences.js";
