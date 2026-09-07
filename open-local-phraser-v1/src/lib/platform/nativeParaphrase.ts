import type { RewriteMode } from "@/lib/types";
import type { CustomStyleTweaks } from "@/lib/styles/customStyles";

export interface NativeStyleExample {
  originalText: string;
  finalText: string;
}

export interface NativePreferenceHint {
  original: string;
  replacement: string;
  count: number;
}

export interface NativeStyleContext {
  /** Approved examples are style references only; the current input remains the sole fact source. */
  approvedExamples: NativeStyleExample[];
  preferredReplacements: NativePreferenceHint[];
  avoidedPhrases: string[];
  preferredContractions: string[];
  sentencePreference?: "shorter" | "longer" | "similar";
}

export interface NativeParaphraseRequest {
  originalText: string;
  protectedSpans: string[];
  mode: RewriteMode;
  strength: number;
  maxTokens?: number;
  /** Ask the native worker for a stricter second editorial pass. */
  repairPass?: boolean;
  temperature?: number;
  /** Best-of-N: generate up to 4 candidates in one model load; ranked by gates. */
  candidates?: number;
  styleInstructions?: string;
  styleTweaks?: CustomStyleTweaks;
  styleContext?: NativeStyleContext;
}

export interface NativeCandidate {
  text: string;
  temperature?: number;
}

export type NativeGenerationBackend = "native-mlx" | "freellm-api";

interface NativeBridge {
  postMessage(message: {
    id: number;
    action: "generateParaphrase" | "cancelParaphrase";
    payload?: NativeParaphraseRequest;
  }): void;
}

interface NativeParaphraseResponse {
  ok?: boolean;
  error?: unknown;
  text?: unknown;
  durationMs?: unknown;
  modelId?: unknown;
  backend?: unknown;
  servedModel?: unknown;
  candidates?: unknown;
}

declare global {
  interface Window {
    __openLocalPhraserGenerationResolve?: (id: number, result: unknown) => void;
  }
}

const pendingRequests = new Map<
  number,
  { resolve: (result: NativeParaphraseResponse) => void; reject: (error: Error) => void; timeout: number }
>();

function nativeHandler(): NativeBridge | null {
  if (typeof window === "undefined") return null;
  const handlers = window.webkit?.messageHandlers as
    | { openLocalPhraserNative?: NativeBridge }
    | undefined;
  return handlers?.openLocalPhraserNative ?? null;
}

function installResolver(): void {
  if (typeof window === "undefined" || window.__openLocalPhraserGenerationResolve) return;

  window.__openLocalPhraserGenerationResolve = (id, result) => {
    const pending = pendingRequests.get(id);
    if (!pending) return;

    pendingRequests.delete(id);
    window.clearTimeout(pending.timeout);
    pending.resolve(result && typeof result === "object" ? result as NativeParaphraseResponse : {});
  };
}

function nextRequestID(): number {
  return Date.now() + Math.floor(Math.random() * 1000);
}

function requestNative(
  request: NativeParaphraseRequest,
  signal?: AbortSignal
): Promise<NativeParaphraseResponse> {
  const handler = nativeHandler();
  if (!handler || typeof window === "undefined") {
    return Promise.reject(new Error("The native generative model is unavailable in this environment."));
  }

  installResolver();
  const id = nextRequestID();

  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      pendingRequests.delete(id);
      try {
        handler.postMessage({ id, action: "cancelParaphrase" });
      } catch {
        // The original timeout is the actionable failure.
      }
      reject(new Error("The local generative model timed out. The safe offline rewrite remains available."));
    }, 180_000);

    const abort = () => {
      window.clearTimeout(timeout);
      pendingRequests.delete(id);
      try {
        handler.postMessage({ id, action: "cancelParaphrase" });
      } catch {
        // The request is already being cancelled.
      }
      reject(new DOMException("Paraphrase cancelled", "AbortError"));
    };

    if (signal?.aborted) {
      abort();
      return;
    }

    signal?.addEventListener("abort", abort, { once: true });
    pendingRequests.set(id, {
      resolve: (result) => {
        signal?.removeEventListener("abort", abort);
        resolve(result);
      },
      reject: (error) => {
        signal?.removeEventListener("abort", abort);
        reject(error);
      },
      timeout,
    });

    try {
      handler.postMessage({ id, action: "generateParaphrase", payload: request });
    } catch (error) {
      signal?.removeEventListener("abort", abort);
      window.clearTimeout(timeout);
      pendingRequests.delete(id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

export function nativeParaphraseAvailable(): boolean {
  return Boolean(nativeHandler());
}

export async function generateNativeParaphrase(
  request: NativeParaphraseRequest,
  signal?: AbortSignal
): Promise<{
  text: string;
  durationMs: number;
  modelId: string;
  backend: NativeGenerationBackend;
  servedModel?: string;
  candidates?: NativeCandidate[];
}> {
  const result = await requestNative(request, signal);
  if (result.ok === false) {
    throw new Error(typeof result.error === "string" ? result.error : "The local generative model failed to load.");
  }

  if (typeof result.text !== "string" || !result.text.trim()) {
    throw new Error("The local generative model returned no usable paragraph.");
  }

  const candidates = Array.isArray(result.candidates)
    ? result.candidates
        .map((candidate) => candidate as NativeCandidate)
        .filter((candidate) => typeof candidate?.text === "string" && candidate.text.trim())
    : undefined;

  return {
    text: result.text.trim(),
    durationMs: typeof result.durationMs === "number" ? result.durationMs : 0,
    modelId: typeof result.modelId === "string" ? result.modelId : (typeof result.text === "string" ? "local-model" : "local-model"),
    backend: result.backend === "freellm-api" ? "freellm-api" : "native-mlx",
    ...(typeof result.servedModel === "string" && result.servedModel.trim()
      ? { servedModel: result.servedModel.trim() }
      : {}),
    ...(candidates && candidates.length > 1 ? { candidates } : {}),
  };
}
