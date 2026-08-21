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

type BootDiagnostics = {
  diagnostics?: {
    modelDirectoryExists?: boolean;
  };
};

export interface LocalModelFailure {
  modelId: RewriteAssistantModelId;
  label: string;
  message: string;
  kind: "missing-assets" | "load-failed";
}

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
let localWasmModuleURL: string | null = null;

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
  // Transformers.js joins this value with model filenames before calling its
  // fetch implementation. An absolute app:// URL is required for the legacy
  // custom-scheme path; the packaged wrapper uses the loopback origin below.
  return modelRoot.protocol === "app:" ? modelRoot.href : modelRoot.pathname;
}

function getBrowserModelPath(modelId: RewriteAssistantModelId): string {
  if (typeof window === "undefined") return modelId;
  const modelPath = new URL(`./models/${modelId}/`, window.location.href);
  return modelPath.protocol === "app:" ? modelPath.href : modelPath.pathname;
}

function getBootDiagnostics(): BootDiagnostics | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as Window & { __OPEN_LOCAL_PHRASER_BOOT__?: BootDiagnostics })
    .__OPEN_LOCAL_PHRASER_BOOT__;
}

async function findMissingBundledFiles(modelId: RewriteAssistantModelId): Promise<string[]> {
  if (typeof window === "undefined") return [];

  // WKURLSchemeHandler-backed app:// fetches are not consistently exposed to
  // Fetch in every WebKit build. The native boot probe has already checked the
  // packaged model directory; let the actual Transformers load report a
  // file-level failure instead of falsely marking every file missing here.
  if (getBootDiagnostics()?.diagnostics?.modelDirectoryExists) return [];

  const descriptor = getRewriteAssistantDescriptor(modelId);
  const modelRoot = new URL(`./models/${modelId}/`, window.location.href);
  const results = await Promise.all(
    descriptor.requiredFiles.map(async (relativePath) => {
      try {
        const response = await fetch(new URL(relativePath, modelRoot), { cache: "no-store" });
        return response.ok ? null : relativePath;
      } catch {
        return relativePath;
      }
    })
  );

  return results.filter((relativePath): relativePath is string => relativePath !== null);
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

async function loadTransformersModule(): Promise<TransformersModule> {
  return import("@huggingface/transformers");
}

async function configureBrowserEnvironment(transformers: TransformersModule): Promise<void> {
  const { env, LogLevel } = transformers;
  env.logLevel = LogLevel.ERROR;
  env.allowLocalModels = true;
  env.allowRemoteModels = false;
  // The packaged wrapper serves immutable model files from loopback. Avoid a
  // stale Cache API miss there and fetch the verified bundle directly.
  env.useBrowserCache = window.location.hostname !== "127.0.0.1";
  env.localModelPath = getBrowserModelRoot();
  if (typeof window.fetch === "function") {
    const nativeFetch = window.fetch.bind(window);
    env.fetch = async (input, init) => {
      const url = typeof input === "string" ? new URL(input, window.location.href) : input;
      try {
        const response = await nativeFetch(url, init);
        if (!response.ok) {
          console.error(`[Pari] local model fetch ${url.href} returned HTTP ${response.status}`);
        }
        return response;
      } catch (error) {
        console.error(`[Pari] local model fetch failed for ${url.href}: ${error instanceof Error ? error.message : String(error)}`);
        throw error;
      }
    };
  }
  const onnxEnvironment = env.backends.onnx as {
    wasm?: {
      wasmPaths?: { mjs: string; wasm: string };
    };
  };
  onnxEnvironment.wasm ??= {};
  onnxEnvironment.wasm.wasmPaths = await getWasmPaths();
}

async function createPipeline(modelId: RewriteAssistantModelId): Promise<PipelineCallable> {
  const descriptor = getRewriteAssistantDescriptor(modelId);
  const missingFiles = await findMissingBundledFiles(modelId);
  if (missingFiles.length > 0) {
    throw new Error(
      `The bundled ${descriptor.label} files are incomplete. Missing: ${missingFiles.join(", ")}. ` +
      `Pari kept the built-in offline suggestions available. In a development checkout, run ` +
      `“npm run models:download” and rebuild the app.`
    );
  }
  const transformers = await loadTransformersModule();
  await configureBrowserEnvironment(transformers);
  try {
    const pipelineInstance = await transformers.pipeline(descriptor.task, getBrowserModelPath(modelId), {
      dtype: descriptor.dtype,
      local_files_only: true,
    });
    return pipelineInstance as PipelineCallable;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `The bundled ${descriptor.label} model could not be loaded. Pari kept the built-in offline ` +
      `suggestions available. In a development checkout, run “npm run models:download” and ` +
      `rebuild the app. Details: ${detail}`
    );
  }
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
