import type { SemanticModelId } from "./types";

export interface EmbeddingModelDescriptor {
  id: SemanticModelId;
  label: string;
  repoId: string;
  dimensions: number;
  dtype: "q8";
  role: "paraphrase-fit" | "semantic-meaning" | "retrieval-meaning";
  estimatedMemoryMb: number;
  ramTarget: string;
  bundledPath: string;
  manifestPath: string;
  requiredFiles: string[];
  note: string;
}

export const MODEL_REGISTRY: Record<SemanticModelId, EmbeddingModelDescriptor> = {
  "Xenova/paraphrase-mpnet-base-v2": {
    id: "Xenova/paraphrase-mpnet-base-v2",
    label: "Paraphrase MPNet",
    repoId: "Xenova/paraphrase-mpnet-base-v2",
    dimensions: 768,
    dtype: "q8",
    role: "paraphrase-fit",
    estimatedMemoryMb: 280,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/paraphrase-mpnet-base-v2",
    manifestPath: "models/Xenova/paraphrase-mpnet-base-v2/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "Paraphrase-trained MPNet used to score meaning-preserving rewrites with a stronger semantic fit signal.",
  },
  "Xenova/paraphrase-MiniLM-L6-v2": {
    id: "Xenova/paraphrase-MiniLM-L6-v2",
    label: "Paraphrase MiniLM L6",
    repoId: "Xenova/paraphrase-MiniLM-L6-v2",
    dimensions: 384,
    dtype: "q8",
    role: "paraphrase-fit",
    estimatedMemoryMb: 95,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/paraphrase-MiniLM-L6-v2",
    manifestPath: "models/Xenova/paraphrase-MiniLM-L6-v2/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "A compact paraphrase encoder that adds an extra low-cost semantic vote for short phrases and single-word swaps.",
  },
  "Xenova/all-mpnet-base-v2": {
    id: "Xenova/all-mpnet-base-v2",
    label: "All MPNet",
    repoId: "Xenova/all-mpnet-base-v2",
    dimensions: 768,
    dtype: "q8",
    role: "semantic-meaning",
    estimatedMemoryMb: 260,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/all-mpnet-base-v2",
    manifestPath: "models/Xenova/all-mpnet-base-v2/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "General-purpose MPNet sentence encoder used as the main meaning-preservation guard.",
  },
  "Xenova/bge-base-en-v1.5": {
    id: "Xenova/bge-base-en-v1.5",
    label: "BGE Base",
    repoId: "Xenova/bge-base-en-v1.5",
    dimensions: 768,
    dtype: "q8",
    role: "retrieval-meaning",
    estimatedMemoryMb: 300,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/bge-base-en-v1.5",
    manifestPath: "models/Xenova/bge-base-en-v1.5/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "Higher-capacity BGE encoder adds a second semantic view for sentence-level fit ranking.",
  },
  "Xenova/bge-small-en-v1.5": {
    id: "Xenova/bge-small-en-v1.5",
    label: "BGE Small",
    repoId: "Xenova/bge-small-en-v1.5",
    dimensions: 384,
    dtype: "q8",
    role: "retrieval-meaning",
    estimatedMemoryMb: 105,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/bge-small-en-v1.5",
    manifestPath: "models/Xenova/bge-small-en-v1.5/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "A lighter BGE encoder that broadens sentence-similarity voting without a large memory increase.",
  },
  "Xenova/all-MiniLM-L6-v2": {
    id: "Xenova/all-MiniLM-L6-v2",
    label: "MiniLM L6",
    repoId: "Xenova/all-MiniLM-L6-v2",
    dimensions: 384,
    dtype: "q8",
    role: "semantic-meaning",
    estimatedMemoryMb: 92,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/all-MiniLM-L6-v2",
    manifestPath: "models/Xenova/all-MiniLM-L6-v2/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "A small semantic encoder that improves token-level swap stability while keeping the bundled ensemble compact.",
  },
  "Xenova/all-MiniLM-L12-v2": {
    id: "Xenova/all-MiniLM-L12-v2",
    label: "MiniLM L12",
    repoId: "Xenova/all-MiniLM-L12-v2",
    dimensions: 384,
    dtype: "q8",
    role: "semantic-meaning",
    estimatedMemoryMb: 140,
    ramTarget: "< 6 GB total app budget target",
    bundledPath: "models/Xenova/all-MiniLM-L12-v2",
    manifestPath: "models/Xenova/all-MiniLM-L12-v2/manifest.json",
    requiredFiles: [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      "onnx/model_quantized.onnx",
    ],
    note: "A lightweight secondary encoder used as a fourth vote to keep rankings stable across short sentences.",
  },
};

export const RANKING_MODEL_IDS: SemanticModelId[] = [
  "Xenova/paraphrase-mpnet-base-v2",
  "Xenova/paraphrase-MiniLM-L6-v2",
  "Xenova/all-mpnet-base-v2",
  "Xenova/bge-base-en-v1.5",
  "Xenova/bge-small-en-v1.5",
  "Xenova/all-MiniLM-L6-v2",
  "Xenova/all-MiniLM-L12-v2",
];

export const ENTITY_GUARD_MODEL_ID = "Xenova/bert-base-NER" as const;

export const MODEL_MEMORY_BUDGET_MB = 6 * 1024;

export const ENTITY_GUARD_ESTIMATED_MEMORY_MB = 220;

export function getModelDescriptor(modelId: SemanticModelId): EmbeddingModelDescriptor {
  return MODEL_REGISTRY[modelId];
}

export function getRankingModelIds(): SemanticModelId[] {
  return [...RANKING_MODEL_IDS];
}

export function getRankingModelEstimatedMemoryMb(): number {
  return RANKING_MODEL_IDS.reduce(
    (total, modelId) => total + MODEL_REGISTRY[modelId].estimatedMemoryMb,
    ENTITY_GUARD_ESTIMATED_MEMORY_MB
  );
}

export function getDefaultModelId(): SemanticModelId {
  return "Xenova/paraphrase-mpnet-base-v2";
}
