import type { AppMode, RewriteMode } from "@/lib/types";

export type CustomStyleBaseMode = "personal" | "warmth";

export interface CustomStyleTweaks {
  /** A bounded strength adjustment applied on top of the saved style strength. */
  strengthOffset: number;
  /** Run the shared warmth polish even when the base engine is Personal. */
  warmthPolish: boolean;
  /** Keep the source sentence count whenever the source is otherwise well-formed. */
  preserveSentenceCount: boolean;
}

export interface CustomStyle {
  id: string;
  name: string;
  description: string;
  instructions: string;
  baseMode: CustomStyleBaseMode;
  strength: number;
  tweaks: CustomStyleTweaks;
  createdAt: string;
  updatedAt: string;
}

export const CUSTOM_STYLE_MODE_PREFIX = "custom:";

export function customModeForStyle(style: Pick<CustomStyle, "id">): AppMode {
  return `${CUSTOM_STYLE_MODE_PREFIX}${style.id}` as AppMode;
}

export function customStyleIdFromMode(mode: AppMode): string | null {
  if (!mode.startsWith(CUSTOM_STYLE_MODE_PREFIX)) return null;
  const id = mode.slice(CUSTOM_STYLE_MODE_PREFIX.length);
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id) ? id : null;
}

export function normalizeCustomStyle(value: unknown): CustomStyle | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<CustomStyle> & { tweaks?: Partial<CustomStyleTweaks> };
  const id = typeof raw.id === "string" ? raw.id.trim() : "";
  const name = typeof raw.name === "string" ? raw.name.trim() : "";
  const instructions = typeof raw.instructions === "string" ? raw.instructions.trim() : "";
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id) || !name || !instructions) return null;

  const baseMode: CustomStyleBaseMode = raw.baseMode === "warmth" ? "warmth" : "personal";
  const rawStrength = typeof raw.strength === "number" ? raw.strength : 56;
  const rawOffset = typeof raw.tweaks?.strengthOffset === "number" ? raw.tweaks.strengthOffset : 0;

  return {
    id,
    name: name.slice(0, 80),
    description: typeof raw.description === "string" ? raw.description.trim().slice(0, 320) : "",
    instructions: instructions.slice(0, 4_000),
    baseMode,
    strength: clampStyleNumber(rawStrength, 0, 100, 56),
    tweaks: {
      strengthOffset: clampStyleNumber(rawOffset, -24, 24, 0),
      warmthPolish: raw.tweaks?.warmthPolish === true,
      preserveSentenceCount: raw.tweaks?.preserveSentenceCount !== false,
    },
    createdAt: typeof raw.createdAt === "string" ? raw.createdAt : "",
    updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt : "",
  };
}

function clampStyleNumber(value: number, min: number, max: number, fallback: number): number {
  return Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback;
}

export function effectiveStyleStrength(style: CustomStyle | null, fallback: number): number {
  if (!style) return fallback;
  return clampStyleNumber(style.strength + style.tweaks.strengthOffset, 0, 100, fallback);
}

export function engineModeForStyle(style: CustomStyle | null): RewriteMode {
  if (!style) return "personal";
  return style.baseMode === "warmth" || style.tweaks.warmthPolish ? "warmth" : "personal";
}
