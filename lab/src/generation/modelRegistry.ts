import type { ModelId, ModelInfo } from "../core/types.js";

/**
 * Registry of available local paraphrase models.
 */
export const MODEL_REGISTRY: Record<ModelId, ModelInfo> = {
  "humarin/chatgpt_paraphraser_on_T5_base": {
    id: "humarin/chatgpt_paraphraser_on_T5_base",
    name: "ChatGPT Paraphraser T5 Base",
    type: "t5",
    supportedLanes: ["conservative", "natural", "structure", "cleanup"],
    expectedLatency: "medium",
    ramEstimate: "~2 GB",
    loaded: false,
  },
  "Vamsi/T5_Paraphrase_Paws": {
    id: "Vamsi/T5_Paraphrase_Paws",
    name: "T5 Paraphrase PAWS",
    type: "t5",
    supportedLanes: ["conservative", "natural"],
    expectedLatency: "medium",
    ramEstimate: "~2 GB",
    loaded: false,
  },
  "eugenesiow/bart-paraphrase": {
    id: "eugenesiow/bart-paraphrase",
    name: "BART Paraphrase",
    type: "bart",
    supportedLanes: ["natural", "structure"],
    expectedLatency: "slow",
    ramEstimate: "~3 GB",
    loaded: false,
  },
  "google/flan-t5-base": {
    id: "google/flan-t5-base",
    name: "FLAN-T5 Base",
    type: "flan-t5",
    supportedLanes: ["conservative", "natural", "cleanup"],
    expectedLatency: "medium",
    ramEstimate: "~2 GB",
    loaded: false,
  },
  "synonym_bank_v1": {
    id: "synonym_bank_v1",
    name: "V1 Synonym Bank",
    type: "synonym_bank",
    supportedLanes: ["conservative"],
    expectedLatency: "fast",
    ramEstimate: "< 100 MB",
    loaded: true,
  },
};

/**
 * Get model info by ID.
 */
export function getModelInfo(modelId: ModelId): ModelInfo | null {
  return MODEL_REGISTRY[modelId] ?? null;
}

/**
 * Get all available models.
 */
export function getAllModels(): ModelInfo[] {
  return Object.values(MODEL_REGISTRY);
}

/**
 * Get models that support a specific lane.
 */
export function getModelsForLane(lane: string): ModelInfo[] {
  return Object.values(MODEL_REGISTRY).filter((m) =>
    m.supportedLanes.includes(lane as never)
  );
}

/**
 * Get models by type.
 */
export function getModelsByType(type: string): ModelInfo[] {
  return Object.values(MODEL_REGISTRY).filter((m) => m.type === type);
}

export { type ModelId, type ModelInfo } from "../core/types.js";
