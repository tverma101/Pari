import type { RankingProvider, SemanticModelId } from "@/lib/ranking/types";
import type { RewriteMode, ThemePreference } from "@/lib/types";

export const STRENGTH_STEPS = [
  { id: "minimal", label: "Minimal", value: 12 },
  { id: "light", label: "Light", value: 28 },
  { id: "balanced", label: "Balanced", value: 48 },
  { id: "strong", label: "Strong", value: 72 },
  { id: "max", label: "Max", value: 94 },
] as const;

export interface AppSettings {
  theme: ThemePreference;
  mode: RewriteMode;
  strength: number;
  freezeWords: string;
  rememberFreezeWords: boolean;
  rankingProvider: RankingProvider;
  semanticModel: SemanticModelId;
  compactMode: boolean;
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "light",
  mode: "standard",
  strength: 45,
  freezeWords: "",
  rememberFreezeWords: true,
  rankingProvider: "embedding",
  semanticModel: "Xenova/paraphrase-MiniLM-L6-v2",
  compactMode: true,
};

const STORAGE_KEY = "open-local-phraser-v2.settings";

function isMode(value: unknown): value is RewriteMode {
  return (
    value === "standard" ||
    value === "fluency" ||
    value === "formal" ||
    value === "simple" ||
    value === "creative" ||
    value === "shorten"
  );
}

function isRankingProvider(value: unknown): value is RankingProvider {
  return value === "rule-based" || value === "embedding";
}

function isSemanticModel(value: unknown): value is SemanticModelId {
  return (
    value === "Xenova/paraphrase-mpnet-base-v2" ||
    value === "Xenova/paraphrase-MiniLM-L6-v2" ||
    value === "Xenova/all-mpnet-base-v2" ||
    value === "Xenova/bge-base-en-v1.5" ||
    value === "Xenova/bge-small-en-v1.5" ||
    value === "Xenova/all-MiniLM-L6-v2" ||
    value === "Xenova/all-MiniLM-L12-v2"
  );
}

function normalizeStrength(value: unknown): number {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return DEFAULT_SETTINGS.strength;
  const clamped = Math.min(100, Math.max(0, Math.round(numeric)));
  return STRENGTH_STEPS.reduce((best, step) => {
    return Math.abs(step.value - clamped) < Math.abs(best.value - clamped) ? step : best;
  }, STRENGTH_STEPS[0]).value;
}

function readRaw(): Partial<AppSettings> | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<AppSettings>) : null;
  } catch {
    return null;
  }
}

export function loadSettings(): AppSettings {
  const raw = readRaw();
  if (!raw) return DEFAULT_SETTINGS;

  const rememberFreezeWords =
    typeof raw.rememberFreezeWords === "boolean"
      ? raw.rememberFreezeWords
      : DEFAULT_SETTINGS.rememberFreezeWords;

  return {
    theme:
      raw.theme === "dark"
        ? "dark"
        : raw.theme === "light"
          ? "light"
          : DEFAULT_SETTINGS.theme,
    mode: isMode(raw.mode) ? raw.mode : DEFAULT_SETTINGS.mode,
    strength: normalizeStrength(raw.strength),
    freezeWords:
      rememberFreezeWords && typeof raw.freezeWords === "string" ? raw.freezeWords : "",
    rememberFreezeWords,
    rankingProvider: isRankingProvider(raw.rankingProvider)
      ? raw.rankingProvider
      : DEFAULT_SETTINGS.rankingProvider,
    semanticModel:
      isSemanticModel(raw.semanticModel) &&
      raw.semanticModel === DEFAULT_SETTINGS.semanticModel
        ? raw.semanticModel
        : DEFAULT_SETTINGS.semanticModel,
    compactMode: typeof raw.compactMode === "boolean" ? raw.compactMode : DEFAULT_SETTINGS.compactMode,
  };
}

export function saveSettings(settings: AppSettings): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...settings,
        freezeWords: settings.rememberFreezeWords ? settings.freezeWords : "",
      })
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
