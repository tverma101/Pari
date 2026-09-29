import type { GenerationLane, GenerationSettings, ModelId } from "../core/types.js";

/**
 * Generation settings presets for each lane.
 */
export const LANE_PRESETS: Record<GenerationLane, Omit<GenerationSettings, "model" | "lane">> = {
  conservative: {
    numBeams: 5,
    numReturnSequences: 3,
    doSample: false,
    temperature: 1.0,
    topK: 50,
    topP: 0.95,
    repetitionPenalty: 1.0,
    maxLength: 128,
    minLength: 5,
  },
  natural: {
    numBeams: 3,
    numReturnSequences: 3,
    doSample: true,
    temperature: 0.8,
    topK: 50,
    topP: 0.9,
    repetitionPenalty: 1.1,
    maxLength: 128,
    minLength: 5,
  },
  structure: {
    numBeams: 2,
    numReturnSequences: 3,
    doSample: true,
    temperature: 1.2,
    topK: 80,
    topP: 0.95,
    repetitionPenalty: 1.2,
    maxLength: 150,
    minLength: 5,
  },
  cleanup: {
    numBeams: 4,
    numReturnSequences: 2,
    doSample: false,
    temperature: 0.5,
    topK: 30,
    topP: 0.85,
    repetitionPenalty: 1.0,
    maxLength: 128,
    minLength: 5,
  },
};

/**
 * Generate a cache key for a lane/settings combination.
 */
export function laneSettingsKey(model: ModelId, lane: GenerationLane): string {
  return `${model}|${lane}`;
}

/**
 * Create a fully resolved GenerationSettings object.
 */
export function createGenerationSettings(
  model: ModelId,
  lane: GenerationLane,
  overrides?: Partial<GenerationSettings>
): GenerationSettings {
  const preset = LANE_PRESETS[lane];
  if (!preset) throw new Error(`Unknown lane: ${lane}`);

  return {
    model,
    lane,
    ...preset,
    ...overrides,
  };
}

export type { GenerationLane } from "../core/types.js";
