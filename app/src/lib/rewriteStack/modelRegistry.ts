export type RewriteAssistantTask = "fill-mask";
export type RewriteAssistantDtype = "q8";

export type RewriteAssistantModelId =
  | "Xenova/distilbert-base-uncased"
  | "Xenova/distilroberta-base";

export interface RewriteAssistantModelDescriptor {
  id: RewriteAssistantModelId;
  label: string;
  task: RewriteAssistantTask;
  dtype: RewriteAssistantDtype;
  role: "phrase-rewrite" | "style-rewrite" | "grammar-prep" | "mask-suggestions";
  estimatedMemoryMb: number;
  bundledPath: string;
  manifestPath: string;
  requiredFiles: string[];
  note: string;
  maskToken?: string;
}

const FILL_MASK_FILES = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "onnx/model_quantized.onnx",
] as const;

export const REWRITE_ASSISTANT_REGISTRY: Record<RewriteAssistantModelId, RewriteAssistantModelDescriptor> = {
  "Xenova/distilbert-base-uncased": {
    id: "Xenova/distilbert-base-uncased",
    label: "DistilBERT Base",
    task: "fill-mask",
    dtype: "q8",
    role: "mask-suggestions",
    estimatedMemoryMb: 250,
    bundledPath: "models/Xenova/distilbert-base-uncased",
    manifestPath: "models/Xenova/distilbert-base-uncased/manifest.json",
    requiredFiles: [...FILL_MASK_FILES],
    maskToken: "[MASK]",
    note: "Fast distilled BERT mask model tuned for lower-latency tap-to-swap synonym suggestions.",
  },
  "Xenova/distilroberta-base": {
    id: "Xenova/distilroberta-base",
    label: "DistilRoBERTa Base",
    task: "fill-mask",
    dtype: "q8",
    role: "mask-suggestions",
    estimatedMemoryMb: 290,
    bundledPath: "models/Xenova/distilroberta-base",
    manifestPath: "models/Xenova/distilroberta-base/manifest.json",
    requiredFiles: [...FILL_MASK_FILES],
    maskToken: "<mask>",
    note: "Second local mask expert that broadens contextual synonym suggestions without loading during the default fast path.",
  },
};

export const REWRITE_MASK_MODEL_IDS: RewriteAssistantModelId[] = [
  "Xenova/distilbert-base-uncased",
  "Xenova/distilroberta-base",
];

export const REWRITE_ASSISTANT_MODEL_IDS: RewriteAssistantModelId[] = [
  ...REWRITE_MASK_MODEL_IDS,
];

export function getRewriteAssistantDescriptor(
  modelId: RewriteAssistantModelId
): RewriteAssistantModelDescriptor {
  return REWRITE_ASSISTANT_REGISTRY[modelId];
}

export function getRewriteAssistantModelIds(): RewriteAssistantModelId[] {
  return [...REWRITE_ASSISTANT_MODEL_IDS];
}

export function getRewriteMaskModelIds(): RewriteAssistantModelId[] {
  return [...REWRITE_MASK_MODEL_IDS];
}

export function getRewriteAssistantEstimatedMemoryMb(): number {
  return REWRITE_ASSISTANT_MODEL_IDS.reduce(
    (total, modelId) => total + REWRITE_ASSISTANT_REGISTRY[modelId].estimatedMemoryMb,
    0
  );
}
