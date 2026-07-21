import type { ModelId, GenerationLane, GenerationSettings, Candidate } from "../core/types.js";
import { LANE_PRESETS } from "./generationLanes.js";
import * as bridge from "./pythonBridge.js";
import { getModelInfo } from "./modelRegistry.js";

let candidateIdCounter = 0;

function nextCandidateId(): string {
  return `cand-${Date.now()}-${++candidateIdCounter}`;
}

/**
 * Run a single sentence through a T5/BART paraphrase model via Python subprocess.
 */
export function runT5Paraphrase(
  sentence: string,
  model: ModelId,
  lane: GenerationLane,
  settings?: Partial<GenerationSettings>
): Candidate[] {
  const modelInfo = getModelInfo(model);
  if (!modelInfo) return [];

  const laneSettings = { ...LANE_PRESETS[lane], ...settings };
  const startTime = performance.now();

  const result = bridge.paraphrase(sentence, {
    model,
    lane,
    numBeams: laneSettings.numBeams,
    numSequences: laneSettings.numReturnSequences,
    doSample: laneSettings.doSample,
    temperature: laneSettings.temperature,
  });

  const elapsedMs = performance.now() - startTime;

  if (!result.success) {
    // Return a failed candidate
    return [{
      id: nextCandidateId(),
      originalSentence: sentence,
      protectedSentence: sentence,
      protectedCandidate: sentence,
      restoredCandidate: sentence,
      sourceModel: model,
      generationLane: lane,
      generationSettings: {
        model,
        lane,
        ...laneSettings,
      },
      timingMs: elapsedMs,
      rejectionReason: `Python error: ${result.error ?? "unknown"}`,
      accepted: false,
      scores: null,
    }];
  }

  const data = result.data as unknown as bridge.ParaphraseOutput;
  const candidatesList = data.candidates ?? [];

  if (candidatesList.length === 0) {
    return [{
      id: nextCandidateId(),
      originalSentence: sentence,
      protectedSentence: sentence,
      protectedCandidate: sentence,
      restoredCandidate: sentence,
      sourceModel: model,
      generationLane: lane,
      generationSettings: {
        model,
        lane,
        ...laneSettings,
      },
      timingMs: elapsedMs,
      rejectionReason: "No candidates generated",
      accepted: false,
      scores: null,
    }];
  }

  return candidatesList.map((text: string) => ({
    id: nextCandidateId(),
    originalSentence: sentence,
    protectedSentence: sentence,
    protectedCandidate: text,
    restoredCandidate: text,
    sourceModel: model,
    generationLane: lane,
    generationSettings: {
      model,
      lane,
      ...laneSettings,
    },
    timingMs: elapsedMs / candidatesList.length,
    rejectionReason: null,
    accepted: true,
    scores: null,
  }));
}

/**
 * Run multiple lane/model combinations for a single sentence.
 * Returns all candidates across all lanes.
 */
export function runMultiLaneGeneration(
  sentence: string,
  models: ModelId[],
  lanes: GenerationLane[]
): Candidate[] {
  const allCandidates: Candidate[] = [];

  for (const model of models) {
    for (const lane of lanes) {
      const candidates = runT5Paraphrase(sentence, model, lane);
      allCandidates.push(...candidates);
    }
  }

  return allCandidates;
}

/**
 * Check if a model is available locally (can be loaded).
 * Does a quick test load.
 */
export function checkModelAvailability(model: ModelId): boolean {
  try {
    const result = bridge.paraphrase("Test loading.", {
      model,
      lane: "conservative",
    });
    return result.success;
  } catch {
    return false;
  }
}

/**
 * Get load time for a model by doing a cold load.
 */
export function measureModelLoadTime(model: ModelId): number {
  const result = bridge.paraphrase("Load test sentence for timing.", {
    model,
    lane: "conservative",
    numSequences: 1,
  });
  return result.timingMs;
}

/**
 * Run warmup inference on a model (loads it into memory).
 */
export function warmupModel(model: ModelId): boolean {
  try {
    const result = bridge.paraphrase("Warmup sentence for model inference.", {
      model,
      lane: "conservative",
      numSequences: 1,
    });
    return result.success;
  } catch {
    return false;
  }
}
