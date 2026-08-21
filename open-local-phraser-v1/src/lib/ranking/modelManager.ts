import { cosineSimilarity } from "./similarity";
import { MODEL_MEMORY_BUDGET_MB, getDefaultModelId, getModelDescriptor } from "./modelRegistry";
import type {
  ModelInfo,
  ModelSource,
  SemanticModelId,
  SemanticSelfTestResult,
} from "./types";

type FeatureExtractorOutput = {
  data: Float32Array | number[];
  dims?: number[];
  size?: number;
};

type FeatureExtractor = ((
  input: string | string[],
  options?: Record<string, unknown>
) => Promise<FeatureExtractorOutput>) & {
  dispose?: () => void | Promise<void>;
};

type TokenizerConfig = {
  tokenizer_class?: string;
  [key: string]: unknown;
};

type TransformersModule = typeof import("@huggingface/transformers");

type EnsureModelOptions = {
  allowRemoteFallback?: boolean;
  forceReload?: boolean;
  onUpdate?: (info: ModelInfo) => void;
};

type BootDiagnostics = {
  diagnostics?: {
    assetsDirectoryExists?: boolean;
    indexExists?: boolean;
    modelDirectoryExists?: boolean;
  };
};

const DEFAULT_MODEL_ID = getDefaultModelId();
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

const SELF_TEST_SENTENCES = [
  "This shows how perception affects communication.",
  "This demonstrates how perception influences communication.",
  "The refrigerator is making a loud noise.",
] as const;

let cachedExtractors = new Map<SemanticModelId, FeatureExtractor>();
let cachedInfo: ModelInfo = {
  id: DEFAULT_MODEL_ID,
  source: "missing",
  status: "not-loaded",
};
let cachedInfos = new Map<SemanticModelId, ModelInfo>([[DEFAULT_MODEL_ID, cachedInfo]]);
let pendingLoads = new Map<SemanticModelId, Promise<{ extractor: FeatureExtractor; info: ModelInfo }>>();
let localWasmModuleURL: string | null = null;

async function disposeCachedExtractor(modelId?: SemanticModelId): Promise<void> {
  if (modelId) {
    const extractor = cachedExtractors.get(modelId);
    cachedExtractors.delete(modelId);

    if (extractor?.dispose) {
      await extractor.dispose();
    }
    return;
  }

  const extractors = [...cachedExtractors.values()];
  cachedExtractors = new Map();

  for (const extractor of extractors) {
    if (extractor.dispose) {
      await extractor.dispose();
    }
  }
}

async function cacheLoadedExtractor(
  modelId: SemanticModelId,
  extractor: FeatureExtractor
): Promise<void> {
  const current = cachedExtractors.get(modelId);
  if (current && current !== extractor) {
    await disposeCachedExtractor(modelId);
  }

  cachedExtractors.set(modelId, extractor);
}

function cachedEstimatedMemoryMb(nextModelId?: SemanticModelId): number {
  const modelIds = new Set(cachedExtractors.keys());
  if (nextModelId) modelIds.add(nextModelId);

  return [...modelIds].reduce(
    (total, modelId) => total + getModelDescriptor(modelId).estimatedMemoryMb,
    0
  );
}

function assertMemoryBudget(modelId: SemanticModelId): void {
  const estimated = cachedEstimatedMemoryMb(modelId);
  if (estimated > MODEL_MEMORY_BUDGET_MB) {
    throw new Error(
      `Loading ${modelId} would exceed the ${MODEL_MEMORY_BUDGET_MB} MB model budget (estimated ${estimated} MB).`
    );
  }
}

function encodeModelPath(relativePath: string): string {
  return relativePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function cloneInfo(info: ModelInfo): ModelInfo {
  return { ...info };
}

function emitInfo(next: Partial<ModelInfo>, onUpdate?: (info: ModelInfo) => void): ModelInfo {
  const id = next.id ?? cachedInfo.id;
  const current = cachedInfos.get(id) ?? {
    id,
    source: "missing",
    status: "not-loaded",
  };
  cachedInfo = {
    ...current,
    ...next,
    id,
  };
  cachedInfos.set(id, cachedInfo);

  const snapshot = cloneInfo(cachedInfo);
  onUpdate?.(snapshot);
  return snapshot;
}

function isSafariBrowser(): boolean {
  if (typeof navigator === "undefined") return false;
  const vendor = navigator.vendor || "";
  const userAgent = navigator.userAgent;

  return (
    vendor.includes("Apple") &&
    !/CriOS|FxiOS|EdgiOS|OPiOS|Chrome|Android/i.test(userAgent)
  );
}

function isLocalNativeRuntime(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
}

function getBrowserModelRoot(): string {
  const modelRoot = new URL("./models/", window.location.href);
  return modelRoot.protocol === "app:" ? modelRoot.href : modelRoot.pathname;
}

function getBrowserModelPath(modelId: SemanticModelId): string {
  if (typeof window === "undefined") return modelId;
  const modelPath = new URL(`./models/${modelId}/`, window.location.href);
  return modelPath.protocol === "app:" ? modelPath.href : modelPath.pathname;
}

function getBundledModelRoot(modelId: SemanticModelId): URL {
  return new URL(`./${getModelDescriptor(modelId).bundledPath}/`, window.location.href);
}

function getRemoteModelFileURL(modelId: SemanticModelId, filePath: string): string {
  const descriptor = getModelDescriptor(modelId);
  return `https://huggingface.co/${descriptor.repoId}/resolve/main/${encodeModelPath(filePath)}?download=1`;
}

async function getWasmPaths(): Promise<{ mjs: string; wasm: string }> {
  const paths = isSafariBrowser() && !isLocalNativeRuntime()
    ? {
        mjs: safariWasmModuleUrl,
        wasm: safariWasmBinaryUrl,
      }
    : {
        mjs: asyncifyWasmModuleUrl,
        wasm: asyncifyWasmBinaryUrl,
      };

  if (!isLocalNativeRuntime() || localWasmModuleURL) {
    return { ...paths, ...(localWasmModuleURL ? { mjs: localWasmModuleURL } : {}) };
  }

  try {
    const response = await fetch(paths.mjs, { cache: "no-store" });
    if (response.ok) {
      localWasmModuleURL = URL.createObjectURL(
        new Blob([await response.text()], { type: "text/javascript" })
      );
      return { ...paths, mjs: localWasmModuleURL };
    }
  } catch {
    // Keep the direct bundle URL so the runtime can report its normal failure.
  }

  return paths;
}

function getBootDiagnostics(): BootDiagnostics | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as Window & { __OPEN_LOCAL_PHRASER_BOOT__?: BootDiagnostics })
    .__OPEN_LOCAL_PHRASER_BOOT__;
}

async function fetchJSON<T>(url: string | URL, cache: RequestCache): Promise<T> {
  const response = await fetch(url, { cache });

  if (!response.ok) {
    throw new Error(`Failed to fetch ${String(url)}: HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

async function loadTransformersModule(): Promise<TransformersModule> {
  return import("@huggingface/transformers");
}

async function configureBrowserEnvironment(
  transformers: TransformersModule,
  allowRemoteModels: boolean
): Promise<void> {
  const { env, LogLevel } = transformers;
  env.logLevel = LogLevel.ERROR;
  env.allowLocalModels = true;
  env.allowRemoteModels = allowRemoteModels;
  env.useBrowserCache = window.location.hostname !== "127.0.0.1";
  env.localModelPath = getBrowserModelRoot();
  if (typeof window.fetch === "function") {
    const nativeFetch = window.fetch.bind(window);
    env.fetch = (input, init) => nativeFetch(
      typeof input === "string" ? new URL(input, window.location.href) : input,
      init
    );
  }
  const onnxEnvironment = env.backends.onnx as {
    wasm?: {
      wasmPaths?: { mjs: string; wasm: string };
    };
  };
  onnxEnvironment.wasm ??= {};
  onnxEnvironment.wasm.wasmPaths = await getWasmPaths();
}

async function probeBundledModel(modelId: SemanticModelId): Promise<boolean> {
  if (typeof window === "undefined") return false;

  const descriptor = getModelDescriptor(modelId);
  const bootDiagnostics = getBootDiagnostics();

  if (bootDiagnostics?.diagnostics?.modelDirectoryExists) {
    return true;
  }

  const manifestUrl = new URL(`./${descriptor.manifestPath}`, window.location.href).href;

  try {
    const manifestResponse = await fetch(manifestUrl, { cache: "no-store" });
    if (manifestResponse.ok) {
      return true;
    }
  } catch {
    // Fall through to file-level checks.
  }

  const baseUrl = new URL(`./${descriptor.bundledPath}/`, window.location.href);
  const checks = await Promise.all(
    descriptor.requiredFiles.map(async (filePath) => {
      try {
        const response = await fetch(new URL(filePath, baseUrl), { cache: "no-store" });
        return response.ok;
      } catch {
        return false;
      }
    })
  );

  return checks.every(Boolean);
}

function toVectors(output: FeatureExtractorOutput, count: number): number[][] {
  const values = Array.from(output.data);
  const dims = output.dims ?? [];
  const width = dims[dims.length - 1] ?? (Math.floor(values.length / count) || 1);

  const vectors: number[][] = [];
  for (let index = 0; index < count; index += 1) {
    const start = index * width;
    vectors.push(values.slice(start, start + width));
  }
  return vectors;
}

function vectorWidth(output: FeatureExtractorOutput, count: number): number {
  const dims = output.dims ?? [];
  const widthFromDims = dims[dims.length - 1];
  if (typeof widthFromDims === "number") {
    return widthFromDims;
  }

  return count > 0 ? Math.floor(Array.from(output.data).length / count) : 0;
}

async function loadTokenizerArtifacts(
  modelId: SemanticModelId,
  source: ModelSource
): Promise<{ tokenizerJSON: Record<string, unknown>; tokenizerConfig: TokenizerConfig }> {
  if (source === "bundled") {
    const modelRoot = getBundledModelRoot(modelId);
    const [tokenizerJSON, tokenizerConfig] = await Promise.all([
      fetchJSON<Record<string, unknown>>(new URL("tokenizer.json", modelRoot), "no-store"),
      fetchJSON<TokenizerConfig>(new URL("tokenizer_config.json", modelRoot), "no-store"),
    ]);

    return { tokenizerJSON, tokenizerConfig };
  }

  const tokenizerURL = getRemoteModelFileURL(modelId, "tokenizer.json");
  const tokenizerConfigURL = getRemoteModelFileURL(modelId, "tokenizer_config.json");

  try {
    const [tokenizerJSON, tokenizerConfig] = await Promise.all([
      fetchJSON<Record<string, unknown>>(tokenizerURL, "force-cache"),
      fetchJSON<TokenizerConfig>(tokenizerConfigURL, "force-cache"),
    ]);

    return { tokenizerJSON, tokenizerConfig };
  } catch {
    const [tokenizerJSON, tokenizerConfig] = await Promise.all([
      fetchJSON<Record<string, unknown>>(tokenizerURL, "no-store"),
      fetchJSON<TokenizerConfig>(tokenizerConfigURL, "no-store"),
    ]);

    return { tokenizerJSON, tokenizerConfig };
  }
}

function resolveTokenizerClass(transformers: TransformersModule, tokenizerConfig: TokenizerConfig) {
  const tokenizerName = tokenizerConfig.tokenizer_class?.replace(/Fast$/, "") ?? "PreTrainedTokenizer";
  const candidate = (transformers as unknown as Record<string, unknown>)[tokenizerName];

  if (typeof candidate === "function") {
    return candidate as new (
      tokenizerJSON: Record<string, unknown>,
      tokenizerConfig: TokenizerConfig
    ) => unknown;
  }

  return transformers.PreTrainedTokenizer as new (
    tokenizerJSON: Record<string, unknown>,
    tokenizerConfig: TokenizerConfig
  ) => unknown;
}

async function createFeatureExtractor(
  transformers: TransformersModule,
  modelId: SemanticModelId,
  source: ModelSource,
  options: {
    local_files_only: boolean;
    progress_callback?: (payload: unknown) => void;
  }
): Promise<FeatureExtractor> {
  const descriptor = getModelDescriptor(modelId);
  const modelPath = source === "bundled" ? getBrowserModelPath(modelId) : modelId;
  const [config, tokenizerArtifacts] = await Promise.all([
    transformers.AutoConfig.from_pretrained(modelPath, options),
    loadTokenizerArtifacts(modelId, source),
  ]);

  const tokenizerClass = resolveTokenizerClass(transformers, tokenizerArtifacts.tokenizerConfig);
  const tokenizer = new tokenizerClass(
    tokenizerArtifacts.tokenizerJSON,
    tokenizerArtifacts.tokenizerConfig
  ) as unknown;

  const model = await transformers.AutoModel.from_pretrained(modelPath, {
    ...options,
    config,
    dtype: descriptor.dtype,
  });

  return new transformers.FeatureExtractionPipeline({
    task: "feature-extraction",
    model,
    tokenizer: tokenizer as never,
  }) as unknown as FeatureExtractor;
}

async function loadLocalExtractor(
  transformers: TransformersModule,
  modelId: SemanticModelId,
  source: ModelSource,
  onUpdate?: (info: ModelInfo) => void
): Promise<{ extractor: FeatureExtractor; info: ModelInfo }> {
  const descriptor = getModelDescriptor(modelId);
  const startedAt = performance.now();

  emitInfo(
    {
      id: modelId,
      source,
      status: "loading",
      lastError: undefined,
    },
    onUpdate
  );

  const extractor = await createFeatureExtractor(transformers, modelId, source, {
    local_files_only: true,
  });

  const info = emitInfo(
    {
      id: modelId,
      source,
      status: "ready",
      loadTimeMs: Math.round(performance.now() - startedAt),
      vectorDimensions: descriptor.dimensions,
      lastError: undefined,
    },
    onUpdate
  );

  return { extractor, info };
}

async function loadRemoteExtractor(
  transformers: TransformersModule,
  modelId: SemanticModelId,
  onUpdate?: (info: ModelInfo) => void
): Promise<{ extractor: FeatureExtractor; info: ModelInfo }> {
  const descriptor = getModelDescriptor(modelId);
  const startedAt = performance.now();

  emitInfo(
    {
      id: modelId,
      source: "remote-cache",
      status: "downloading",
      lastError: undefined,
    },
    onUpdate
  );

  const extractor = await createFeatureExtractor(transformers, modelId, "remote-cache", {
    local_files_only: false,
    progress_callback: () => {
      emitInfo(
        {
          id: modelId,
          source: "remote-cache",
          status: "downloading",
        },
        onUpdate
      );
    },
  });

  const info = emitInfo(
    {
      id: modelId,
      source: "remote-cache",
      status: "ready",
      loadTimeMs: Math.round(performance.now() - startedAt),
      vectorDimensions: descriptor.dimensions,
      lastError: undefined,
    },
    onUpdate
  );

  return { extractor, info };
}

export async function probeModelInfo(
  modelId: SemanticModelId = DEFAULT_MODEL_ID
): Promise<ModelInfo> {
  const bundled = await probeBundledModel(modelId);

  return emitInfo({
    id: modelId,
    source: bundled ? "bundled" : "missing",
    status: cachedExtractors.has(modelId) ? "ready" : "not-loaded",
    loadTimeMs: cachedInfos.get(modelId)?.loadTimeMs,
    vectorDimensions:
      cachedExtractors.has(modelId)
        ? cachedInfos.get(modelId)?.vectorDimensions ?? getModelDescriptor(modelId).dimensions
        : undefined,
    lastError: undefined,
  });
}

export function getModelInfoSnapshot(): ModelInfo {
  return cloneInfo(cachedInfo);
}

export async function ensureModelReady(
  modelId: SemanticModelId = DEFAULT_MODEL_ID,
  options: EnsureModelOptions = {}
): Promise<{ extractor: FeatureExtractor; info: ModelInfo }> {
  const { allowRemoteFallback = true, forceReload = false, onUpdate } = options;

  if (
    !forceReload &&
    cachedExtractors.has(modelId) &&
    cachedInfos.get(modelId)?.status === "ready"
  ) {
    const snapshot = cloneInfo(cachedInfos.get(modelId) ?? cachedInfo);
    onUpdate?.(snapshot);
    return {
      extractor: cachedExtractors.get(modelId)!,
      info: snapshot,
    };
  }

  const pendingLoad = pendingLoads.get(modelId);
  if (!forceReload && pendingLoad) {
    return pendingLoad;
  }

  const nextLoad = (async () => {
    if (forceReload) {
      await disposeCachedExtractor(modelId);
    }

    assertMemoryBudget(modelId);
    const bundled = await probeBundledModel(modelId);
    const transformers = await loadTransformersModule();
    const errors: string[] = [];

    try {
      if (bundled) {
        await configureBrowserEnvironment(transformers, false);
        const local = await loadLocalExtractor(transformers, modelId, "bundled", onUpdate);
        await cacheLoadedExtractor(modelId, local.extractor);
        return local;
      }

      if (!allowRemoteFallback) {
        const failed = emitInfo(
          {
            id: modelId,
            source: "missing",
            status: "failed",
            loadTimeMs: undefined,
            lastError: "Bundled model files were not found and remote fallback is disabled.",
          },
          onUpdate
        );
        throw new Error(failed.lastError);
      }

      await configureBrowserEnvironment(transformers, true);
      const remote = await loadRemoteExtractor(transformers, modelId, onUpdate);
      await cacheLoadedExtractor(modelId, remote.extractor);
      return remote;
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));

      if (bundled && allowRemoteFallback) {
        await configureBrowserEnvironment(transformers, true);

        try {
          const remote = await loadRemoteExtractor(transformers, modelId, onUpdate);
          await cacheLoadedExtractor(modelId, remote.extractor);
          return remote;
        } catch (remoteError) {
          errors.push(remoteError instanceof Error ? remoteError.message : String(remoteError));
        }
      }

      const failed = emitInfo(
        {
          id: modelId,
          source: bundled ? "bundled" : "missing",
          status: "failed",
          loadTimeMs: undefined,
          vectorDimensions: undefined,
          lastError: errors.join("\n"),
        },
        onUpdate
      );
      throw new Error(failed.lastError);
    } finally {
      pendingLoads.delete(modelId);
    }
  })();

  pendingLoads.set(modelId, nextLoad);
  return nextLoad;
}

export async function getEmbeddingExtractor(
  modelId: SemanticModelId = DEFAULT_MODEL_ID,
  options: EnsureModelOptions = {}
): Promise<FeatureExtractor> {
  const loaded = await ensureModelReady(modelId, options);
  return loaded.extractor;
}

export async function unloadSemanticModel(
  onUpdate?: (info: ModelInfo) => void,
  targetModelId?: SemanticModelId
): Promise<ModelInfo> {
  const modelId = targetModelId ?? cachedInfo.id;
  const inFlight = pendingLoads.get(modelId);
  if (inFlight) {
    try {
      await inFlight;
    } catch {
      // The unload action should still reset local model state after a failed load.
    }
  }

  pendingLoads.delete(modelId);
  await disposeCachedExtractor(modelId);
  const bundled = await probeBundledModel(modelId);

  return emitInfo(
    {
      id: modelId,
      source: bundled ? "bundled" : "missing",
      status: "not-loaded",
      loadTimeMs: undefined,
      vectorDimensions: undefined,
      lastError: undefined,
    },
    onUpdate
  );
}

export async function runSemanticSelfTest(
  modelId: SemanticModelId = DEFAULT_MODEL_ID,
  options: EnsureModelOptions = {}
): Promise<SemanticSelfTestResult> {
  try {
    const { extractor, info } = await ensureModelReady(modelId, {
      allowRemoteFallback: options.allowRemoteFallback ?? true,
      onUpdate: options.onUpdate,
      forceReload: options.forceReload,
    });

    const startedAt = performance.now();
    const embeddings = await extractor([...SELF_TEST_SENTENCES], {
      pooling: "mean",
      normalize: true,
    });

    const vectors = toVectors(embeddings, SELF_TEST_SENTENCES.length);
    const similarity12 = cosineSimilarity(vectors[0] ?? [], vectors[1] ?? []);
    const similarity13 = cosineSimilarity(vectors[0] ?? [], vectors[2] ?? []);
    const dimensions = vectorWidth(embeddings, SELF_TEST_SENTENCES.length);

    const passed = similarity12 > similarity13;
    const result: SemanticSelfTestResult = {
      modelId,
      passed,
      vectorDimensions: dimensions,
      loadTimeMs: Math.round((info.loadTimeMs ?? 0) + (performance.now() - startedAt)),
      similarity12,
      similarity13,
      source: info.source,
      errorMessage: passed
        ? undefined
        : "Related sentence similarity did not exceed unrelated sentence similarity.",
    };

    emitInfo(
      {
        id: modelId,
        source: info.source,
        status: passed ? "ready" : "failed",
        vectorDimensions: dimensions,
        loadTimeMs: result.loadTimeMs,
        lastError: result.errorMessage,
      },
      options.onUpdate
    );

    return result;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emitInfo(
      {
        id: modelId,
        status: "failed",
        loadTimeMs: undefined,
        vectorDimensions: undefined,
        lastError: message,
      },
      options.onUpdate
    );

    return {
      modelId,
      passed: false,
      vectorDimensions: 0,
      loadTimeMs: 0,
      similarity12: 0,
      similarity13: 0,
      source: cachedInfo.source,
      errorMessage: message,
    };
  }
}
