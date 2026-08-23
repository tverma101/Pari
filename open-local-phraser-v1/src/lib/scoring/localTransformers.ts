type TransformersModule = typeof import("@huggingface/transformers");

type LocalEnvironment = typeof import("@huggingface/transformers").env & {
  localModelPath?: string;
  fetch?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
};

/**
 * Configure Transformers.js for a bundled, local-only model.
 *
 * The evaluator runs from either the app directory or the repository root;
 * the packaged app runs from a loopback/app URL. Keeping this resolution in
 * one place prevents a model from silently switching to a remote source or
 * resolving relative to whichever directory happened to launch the command.
 */
export async function configureLocalTransformers(transformers: TransformersModule): Promise<void> {
  const env = transformers.env as LocalEnvironment;
  env.logLevel = transformers.LogLevel.ERROR;
  env.allowLocalModels = true;
  env.allowRemoteModels = false;

  if (typeof window === "undefined") {
    const [pathMod, fsMod] = await Promise.all([import("path"), import("fs")]);
    const candidates = [
      pathMod.resolve(process.cwd(), "public/models"),
      pathMod.resolve(process.cwd(), "open-local-phraser-v1/public/models"),
    ];
    env.localModelPath = candidates.find((candidate) => fsMod.existsSync(candidate)) ?? candidates[0];
    return;
  }

  env.useBrowserCache = window.location.hostname !== "127.0.0.1";
  const modelRoot = new URL("./models/", window.location.href);
  env.localModelPath = modelRoot.protocol === "app:" ? modelRoot.href : modelRoot.pathname;

  const nativeFetch = window.fetch.bind(window);
  env.fetch = (input, init) => nativeFetch(
    typeof input === "string" ? new URL(input, window.location.href) : input,
    init
  );

  const onnxEnvironment = transformers.env.backends.onnx as {
    wasm?: {
      wasmPaths?: { mjs: string; wasm: string };
    };
  };
  onnxEnvironment.wasm ??= {};
  // Reuse the browser model manager's Vite/WKWebView-safe URLs. Keeping the
  // import lazy also lets the evaluator execute this module in its CommonJS
  // bridge without parsing an import.meta expression.
  const { getWasmPaths } = await import("@/lib/ranking/modelManager");
  onnxEnvironment.wasm.wasmPaths = await getWasmPaths();
}
