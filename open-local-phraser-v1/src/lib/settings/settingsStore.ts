import type { AppMode, RewriteMode, ThemePreference } from "@/lib/types";

export interface AppSettings {
  theme: ThemePreference;
  mode: AppMode;
  strength: number;
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "light",
  mode: "personal",
  strength: 56,
};

const STORAGE_KEY = "open-local-phraser-v2.settings";

function readRaw(): Partial<AppSettings> | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<AppSettings>) : null;
  } catch {
    return null;
  }
}

const LEGACY_REWRITE_MODES: AppMode[] = [
  "personal",
  "warmth",
  "standard",
  "fluency",
  "warm",
  "formal",
  "simple",
  "creative",
  "expand",
  "shorten",
];

export function normalizeStoredRewriteMode(value: unknown): AppMode {
  if (value === "warmth") return "warmth";
  if (typeof value === "string" && /^custom:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value)) {
    return value as AppMode;
  }
  return typeof value === "string" && LEGACY_REWRITE_MODES.includes(value as RewriteMode)
    ? "personal"
    : DEFAULT_SETTINGS.mode;
}

export function loadSettings(): AppSettings {
  const raw = readRaw();
  if (!raw) return DEFAULT_SETTINGS;

  return {
    theme:
      raw.theme === "dark"
        ? "dark"
        : raw.theme === "light"
          ? "light"
          : DEFAULT_SETTINGS.theme,
    mode: normalizeStoredRewriteMode(raw.mode),
    strength:
      typeof raw.strength === "number"
        ? Math.min(100, Math.max(0, raw.strength))
        : DEFAULT_SETTINGS.strength,
  };
}

export function saveSettings(settings: AppSettings): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(settings)
    );
  } catch {
    // localStorage remains best-effort in the desktop shell.
  }
}

export function resolveTheme(theme: ThemePreference): "light" | "dark" {
  if (theme === "light" || theme === "dark") return theme;

  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: ThemePreference): "light" | "dark" {
  const resolved = resolveTheme(theme);

  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
  }

  return resolved;
}
