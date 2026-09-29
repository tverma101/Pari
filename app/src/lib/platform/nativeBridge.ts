export type NativeBridgeAction = "loadState" | "saveApproval" | "loadCustomStyles";

interface NativeRequest {
  id: number;
  action: NativeBridgeAction;
  payload?: unknown;
}

interface NativeBridge {
  postMessage(message: NativeRequest): void;
}

interface PendingRequest {
  resolve: (result: unknown) => void;
  reject: (error: Error) => void;
  timeout: number;
}

declare global {
  interface Window {
    __openLocalPhraserNativeResolve?: (id: number, result: unknown) => void;
    webkit?: {
      messageHandlers?: {
        openLocalPhraserNative?: NativeBridge;
      };
    };
  }
}

const pendingRequests = new Map<number, PendingRequest>();

function nativeHandler(): NativeBridge | null {
  if (typeof window === "undefined") return null;
  return window.webkit?.messageHandlers?.openLocalPhraserNative ?? null;
}

function installResolver(): void {
  if (typeof window === "undefined" || window.__openLocalPhraserNativeResolve) return;

  window.__openLocalPhraserNativeResolve = (id, result) => {
    const pending = pendingRequests.get(id);
    if (!pending) return;
    pendingRequests.delete(id);
    window.clearTimeout(pending.timeout);
    if (result && typeof result === "object" && "ok" in result) {
      const response = result as { ok?: boolean; error?: unknown };
      if (response.ok === false) {
        pending.reject(new Error(typeof response.error === "string" ? response.error : "Native bridge request failed"));
        return;
      }
    }
    pending.resolve(result);
  };
}

export function nativeBridgeAvailable(): boolean {
  return nativeHandler() !== null;
}

export function requestNativeBridge(
  action: NativeBridgeAction,
  payload?: unknown,
  timeoutMs = 2_500,
): Promise<unknown> {
  const handler = nativeHandler();
  if (!handler || typeof window === "undefined") {
    return Promise.reject(new Error("The native bridge is unavailable in this environment."));
  }

  installResolver();
  const id = Date.now() + Math.floor(Math.random() * 1000);
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      pendingRequests.delete(id);
      reject(new Error("The native bridge request timed out."));
    }, timeoutMs);
    pendingRequests.set(id, { resolve, reject, timeout });

    try {
      handler.postMessage({ id, action, payload });
    } catch (error) {
      window.clearTimeout(timeout);
      pendingRequests.delete(id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}
