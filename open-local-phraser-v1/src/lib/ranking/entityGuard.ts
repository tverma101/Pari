import { ENTITY_GUARD_MODEL_ID } from "./modelRegistry";

type TokenClassificationOutput = Array<{
  word?: string;
  entity?: string;
  entity_group?: string;
  score?: number;
}>;

type TokenClassifier = ((
  input: string,
  options?: Record<string, unknown>
) => Promise<TokenClassificationOutput>) & {
  dispose?: () => void | Promise<void>;
};

type TransformersModule = typeof import("@huggingface/transformers");

const safariWasmModuleUrl = new URL(
  "../../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.mjs",
  import.meta.url
).href;
const safariWasmBinaryUrl = new URL(
  "../../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm",
  import.meta.url
).href;
const asyncifyWasmModuleUrl = new URL(
  "../../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.mjs",
  import.meta.url
).href;
const asyncifyWasmBinaryUrl = new URL(
  "../../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.wasm",
  import.meta.url
).href;

let classifier: TokenClassifier | null = null;
let pendingLoad: Promise<TokenClassifier> | null = null;
const ENTITY_LABEL_PATTERN = /PER|ORG|LOC|MISC/i;
const SENTENCE_START_STOPWORDS = new Set([
  "A",
  "An",
  "And",
  "As",
  "At",
  "But",
  "By",
  "For",
  "From",
  "However",
  "I",
  "If",
  "In",
  "It",
  "Many",
  "My",
  "Of",
  "On",
  "Or",
  "Our",
  "The",
  "Their",
  "There",
  "These",
  "This",
  "Those",
  "To",
  "We",
  "When",
  "With",
]);

function isSafariBrowser(): boolean {
  if (typeof navigator === "undefined") return false;
  const vendor = navigator.vendor || "";
  const userAgent = navigator.userAgent;

  return (
    vendor.includes("Apple") &&
    !/CriOS|FxiOS|EdgiOS|OPiOS|Chrome|Android/i.test(userAgent)
  );
}

function getBrowserModelRoot(): string {
  return new URL("./models/", window.location.href).href;
}

function getWasmPaths(): { mjs: string; wasm: string } {
  return isSafariBrowser()
    ? {
        mjs: safariWasmModuleUrl,
        wasm: safariWasmBinaryUrl,
      }
    : {
        mjs: asyncifyWasmModuleUrl,
        wasm: asyncifyWasmBinaryUrl,
      };
}

async function configureEnvironment(transformers: TransformersModule): Promise<void> {
  const { env, LogLevel } = transformers;
  env.logLevel = LogLevel.ERROR;
  env.allowLocalModels = true;
  env.allowRemoteModels = false;
  env.useBrowserCache = true;
  env.localModelPath = getBrowserModelRoot();
  const onnxEnvironment = env.backends.onnx as {
    wasm?: {
      wasmPaths?: { mjs: string; wasm: string };
    };
  };
  onnxEnvironment.wasm ??= {};
  onnxEnvironment.wasm.wasmPaths = getWasmPaths();
}

async function loadClassifier(): Promise<TokenClassifier> {
  if (classifier) return classifier;
  if (pendingLoad) return pendingLoad;

  pendingLoad = (async () => {
    const transformers = await import("@huggingface/transformers");
    await configureEnvironment(transformers);
    const loaded = await transformers.pipeline("token-classification", ENTITY_GUARD_MODEL_ID, {
      dtype: "q8",
      local_files_only: true,
    });
    classifier = loaded as unknown as TokenClassifier;
    return classifier;
  })();

  try {
    return await pendingLoad;
  } finally {
    pendingLoad = null;
  }
}

function normalizeEntityWord(value: string): string | null {
  const cleaned = value
    .replace(/##/g, "")
    .replace(/\s+/g, " ")
    .replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, "")
    .trim();

  if (cleaned.length < 2) return null;
  if (!/[A-Za-z]/.test(cleaned)) return null;
  return cleaned;
}

function labelType(label: string): string {
  return label.replace(/^[BI]-/i, "").toUpperCase();
}

function normalizeEntityPhrase(parts: string[]): string | null {
  return normalizeEntityWord(parts.join(" ").replace(/\s+##/g, ""));
}

function collectEntityTerms(output: TokenClassificationOutput): string[] {
  const terms = new Set<string>();
  let currentLabel = "";
  let currentParts: string[] = [];

  const flush = () => {
    const normalized = normalizeEntityPhrase(currentParts);
    if (normalized) terms.add(normalized);
    currentLabel = "";
    currentParts = [];
  };

  for (const entity of output) {
    if (typeof entity.score === "number" && entity.score < 0.55) {
      flush();
      continue;
    }

    const rawLabel = entity.entity_group ?? entity.entity ?? "";
    const normalizedLabel = labelType(rawLabel);
    if (!ENTITY_LABEL_PATTERN.test(normalizedLabel)) {
      flush();
      continue;
    }

    const piece = entity.word?.trim();
    if (!piece) {
      flush();
      continue;
    }

    const startsNewEntity =
      currentParts.length === 0 ||
      /^B-/i.test(rawLabel) ||
      normalizedLabel !== currentLabel;

    if (startsNewEntity) {
      flush();
      currentLabel = normalizedLabel;
    }

    currentParts.push(piece);
  }

  flush();
  return [...terms].slice(0, 24);
}

function heuristicProtectedTerms(text: string): string[] {
  const terms = new Set<string>();
  const matches = text.matchAll(/\b(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,}))*\b/g);

  for (const match of matches) {
    const candidate = normalizeEntityWord(match[0] ?? "");
    if (!candidate) continue;
    if (SENTENCE_START_STOPWORDS.has(candidate)) continue;
    terms.add(candidate);
  }

  return [...terms].slice(0, 24);
}

export async function detectProtectedEntityTerms(text: string): Promise<string[]> {
  const trimmed = text.trim();
  if (!trimmed) return [];

  try {
    const ner = await loadClassifier();
    const output = await ner(trimmed);
    const detected = collectEntityTerms(output);
    if (detected.length > 0) {
      return detected;
    }
  } catch {
    // Fall back to simple proper-noun preservation when local NER is unavailable.
  }

  return heuristicProtectedTerms(trimmed);
}

export async function unloadEntityGuardModel(): Promise<void> {
  const current = classifier;
  classifier = null;
  pendingLoad = null;
  if (current?.dispose) {
    await current.dispose();
  }
}
