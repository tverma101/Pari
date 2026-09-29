interface ClipboardBridge {
  postMessage(message: { id: number; action: "readText" | "writeText"; text?: string }): void;
}

declare global {
  interface Window {
    __openLocalPhraserClipboardResolve?: (id: number, result: unknown) => void;
  }
}

type ClipboardResponse = {
  ok?: boolean;
  error?: unknown;
  text?: unknown;
};

const pendingRequests = new Map<
  number,
  { resolve: (result: ClipboardResponse) => void; reject: (error: Error) => void; timeout: number }
>();

function nativeClipboardBridge(): ClipboardBridge | null {
  if (typeof window === "undefined") return null;
  const handlers = window.webkit?.messageHandlers as
    | { openLocalPhraserClipboard?: ClipboardBridge }
    | undefined;
  return handlers?.openLocalPhraserClipboard ?? null;
}

function installResolver(): void {
  if (typeof window === "undefined" || window.__openLocalPhraserClipboardResolve) return;

  window.__openLocalPhraserClipboardResolve = (id, result) => {
    const pending = pendingRequests.get(id);
    if (!pending) return;

    pendingRequests.delete(id);
    window.clearTimeout(pending.timeout);
    pending.resolve(result && typeof result === "object" ? (result as ClipboardResponse) : {});
  };
}

function requestNative(
  action: "readText" | "writeText",
  text?: string
): Promise<ClipboardResponse> {
  const bridge = nativeClipboardBridge();
  if (!bridge || typeof window === "undefined") {
    return Promise.reject(new Error("Native clipboard is unavailable"));
  }

  installResolver();
  const id = Date.now() + Math.floor(Math.random() * 1000);

  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      pendingRequests.delete(id);
      reject(new Error("Native clipboard timed out"));
    }, 2500);

    pendingRequests.set(id, { resolve, reject, timeout });

    try {
      bridge.postMessage({ id, action, ...(text === undefined ? {} : { text }) });
    } catch (error) {
      window.clearTimeout(timeout);
      pendingRequests.delete(id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

function browserClipboard(): Clipboard {
  if (typeof navigator === "undefined" || !navigator.clipboard) {
    throw new Error("Clipboard is unavailable in this environment.");
  }
  return navigator.clipboard;
}

export async function writeClipboardText(text: string): Promise<void> {
  if (!text.trim()) return;

  try {
    const response = await requestNative("writeText", text);
    if (response.ok !== false) return;
    throw new Error(typeof response.error === "string" ? response.error : "Native clipboard write failed");
  } catch (nativeError) {
    try {
      await browserClipboard().writeText(text);
    } catch {
      throw nativeError instanceof Error ? nativeError : new Error(String(nativeError));
    }
  }
}

export async function readClipboardText(): Promise<string> {
  try {
    const response = await requestNative("readText");
    if (response.ok === false) {
      throw new Error(typeof response.error === "string" ? response.error : "Native clipboard read failed");
    }
    return typeof response.text === "string" ? response.text : "";
  } catch (nativeError) {
    try {
      return await browserClipboard().readText();
    } catch {
      throw nativeError instanceof Error ? nativeError : new Error(String(nativeError));
    }
  }
}
