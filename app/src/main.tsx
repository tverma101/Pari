import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { applyTheme, loadSettings } from "@/lib/settings/settingsStore";

import "./index.css";
import App from "./App";

applyTheme(loadSettings().theme);

let startupGuardActive = true;

  /** Human-readable summary only — stacks and raw payloads go to the console. */
  function formatErrorDetails(error: unknown): string {
    if (error instanceof Error) {
      return error.message;
    }

  if (error && typeof error === "object") {
    try {
      const serialized = JSON.stringify(error, Object.getOwnPropertyNames(error));
      if (serialized && serialized !== "{}") return serialized;
    } catch {
      // Fall through to a safe string representation for host objects.
    }
  }

  return String(error);
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderStartupError(title: string, details: string): void {
  const root = document.getElementById("root");
  if (!root) return;

  root.innerHTML = `
    <div style="min-height:100vh;display:grid;place-items:center;padding:24px;background:linear-gradient(180deg,#09131f 0%,#142033 100%);color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <div style="width:min(720px,100%);border-radius:24px;border:1px solid rgba(148,163,184,0.28);background:rgba(15,23,42,0.88);padding:28px;box-shadow:0 24px 80px rgba(15,23,42,0.45);">
        <p style="margin:0 0 10px;font-size:12px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:#93c5fd;">Startup error</p>
        <h1 style="margin:0 0 12px;font-size:28px;line-height:1.2;">${escapeHtml(title)}</h1>
        <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#cbd5e1;">The app shell loaded, but the frontend could not finish booting.</p>
        <pre style="margin:0;overflow:auto;white-space:pre-wrap;word-break:break-word;border-radius:18px;background:rgba(15,23,42,0.72);padding:16px;font-size:13px;line-height:1.55;color:#e2e8f0;">${escapeHtml(details)}</pre>
      </div>
    </div>
  `;
}

function StartupErrorCard({ title, details }: { title: string; details: string }) {
  return (
    <div className="grid min-h-screen place-items-center bg-[linear-gradient(180deg,#09131f_0%,#142033_100%)] p-6 text-slate-50">
      <div className="w-full max-w-3xl rounded-[24px] border border-slate-700/60 bg-slate-950/85 p-7 shadow-[0_24px_80px_rgba(15,23,42,0.45)]">
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-sky-300">
          Startup error
        </p>
        <h1 className="mb-3 text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mb-4 text-sm leading-6 text-slate-300">
          The app shell loaded, but the frontend could not finish booting.
        </p>
        <pre className="overflow-auto whitespace-pre-wrap break-words rounded-[18px] bg-slate-900/80 p-4 text-xs leading-6 text-slate-200">
          {details}
        </pre>
      </div>
    </div>
  );
}

class StartupErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("React startup failure", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <StartupErrorCard
          title="Pari could not start"
          details={formatErrorDetails(this.state.error)}
        />
      );
    }

    return this.props.children;
  }
}

window.addEventListener("error", (event) => {
  const error = event.error ?? new Error(event.message);
  if (startupGuardActive) {
    renderStartupError("Pari could not start", formatErrorDetails(error));
    return;
  }

  console.error("Runtime error", error);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason ?? "Unhandled promise rejection";
  if (startupGuardActive) {
    renderStartupError(
      "Pari could not start",
      formatErrorDetails(reason)
    );
    return;
  }

  console.error("Unhandled runtime rejection", formatErrorDetails(reason));
});

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Could not find the #root element.");
}

try {
  createRoot(rootElement).render(
    <StrictMode>
      <StartupErrorBoundary>
        <App />
      </StartupErrorBoundary>
    </StrictMode>
  );
  window.setTimeout(() => {
    startupGuardActive = false;
  }, 0);
} catch (error) {
  renderStartupError("Pari could not start", formatErrorDetails(error));
}
