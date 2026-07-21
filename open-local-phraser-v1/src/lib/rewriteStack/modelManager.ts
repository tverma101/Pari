import {
  getRewriteAssistantDescriptor,
  getRewriteAssistantModelIds,
  type RewriteAssistantModelId,
} from "./modelRegistry";

type TransformersModule = typeof import("@huggingface/transformers");

type FillMaskOutput =
  | Array<{ token_str?: string; sequence?: string; score?: number }>
  | { token_str?: string; sequence?: string; score?: number };

type PipelineCallable = ((input: string | string[], options?: Record<string, unknown>) => Promise<unknown>) & {
  dispose?: () => void | Promise<void>;
};

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

const cachedPipelines = new Map<RewriteAssistantModelId, PipelineCallable>();
const pendingLoads = new Map<RewriteAssistantModelId, Promise<PipelineCallable>>();

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

async function loadTransformersModule(): Promise<TransformersModule> {
  return import("@huggingface/transformers");
}

async function configureBrowserEnvironment(transformers: TransformersModule): Promise<void> {
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

async function createPipeline(modelId: RewriteAssistantModelId): Promise<PipelineCallable> {
  const descriptor = getRewriteAssistantDescriptor(modelId);
  const transformers = await loadTransformersModule();
  await configureBrowserEnvironment(transformers);
  const pipelineInstance = await transformers.pipeline(descriptor.task, modelId, {
    dtype: descriptor.dtype,
    local_files_only: true,
  });
  return pipelineInstance as PipelineCallable;
}

async function getPipeline(modelId: RewriteAssistantModelId): Promise<PipelineCallable> {
  const cached = cachedPipelines.get(modelId);
  if (cached) return cached;

  const pending = pendingLoads.get(modelId);
  if (pending) return pending;

  const next = createPipeline(modelId).then((pipelineInstance) => {
    cachedPipelines.set(modelId, pipelineInstance);
    pendingLoads.delete(modelId);
    return pipelineInstance;
  }).catch((error) => {
    pendingLoads.delete(modelId);
    throw error;
  });

  pendingLoads.set(modelId, next);
  return next;
}

export async function warmRewriteAssistantModels(
  modelIds: RewriteAssistantModelId[] = getRewriteAssistantModelIds()
): Promise<void> {
  for (const modelId of modelIds) {
    try {
      await getPipeline(modelId);
    } catch {
      // The rewrite stack tolerates partial model availability and can still use
      // the remaining bundled experts when one browser pipeline fails.
    }
  }
}

export async function generateMaskSuggestions(
  modelId: RewriteAssistantModelId,
  maskedSentence: string,
  topK = 5
): Promise<Array<{ token: string; score: number; sequence: string }>> {
  const unmasker = await getPipeline(modelId);
  const output = await unmasker(maskedSentence, { top_k: topK }) as FillMaskOutput;
  const items = Array.isArray(output) ? output : [output];

  return items
    .map((item) => ({
      token: item.token_str?.trim() ?? "",
      score: item.score ?? 0,
      sequence: item.sequence?.trim() ?? "",
    }))
    .filter((item) => item.token.length > 0);
}
