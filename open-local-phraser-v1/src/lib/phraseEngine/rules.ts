import type { RewriteMode, StrengthLevel } from "@/lib/types";

export const MODE_OPTIONS: { value: RewriteMode; label: string; hint: string }[] = [
  { value: "personal", label: "Personal", hint: "Warm, clear, and explanatory" },
  { value: "warmth", label: "Warmth", hint: "Noticeably more human, kind, and natural" },
];

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export type StrengthBand = "light" | "balanced" | "strong" | "deep";

/**
 * Keep the visible slider, automatic rewrite policy, and native prompt on
 * one scale. A 0-100 control is easier to tune than four disconnected modes,
 * but the engine still needs explicit bands for safe policy decisions.
 */
export function strengthBand(value: number): StrengthBand {
  const normalized = clamp(Math.round(value), 0, 100);
  if (normalized <= 24) return "light";
  if (normalized <= 49) return "balanced";
  if (normalized <= 74) return "strong";
  return "deep";
}

export function strengthLabel(value: number): string {
  const labels: Record<StrengthBand, string> = {
    light: "Light",
    balanced: "Balanced",
    strong: "Strong",
    deep: "Deep",
  };
  return labels[strengthBand(value)];
}

export function percentToStrengthLevel(value: number): StrengthLevel {
  switch (strengthBand(value)) {
    case "light":
      return 1;
    case "balanced":
      return 2;
    case "strong":
      return 3;
    case "deep":
      return 4;
  }
}

/** Minimum safe lexical/phrase edits to seek per sentence in the fallback. */
export function minimumAutomaticRewrites(value: number): number {
  switch (strengthBand(value)) {
    case "light":
      return 0;
    case "balanced":
    case "strong":
      return 1;
    case "deep":
      return 2;
  }
}

/** Maximum automatic edits per sentence before the final quality gates run. */
export function maximumAutomaticRewrites(value: number): number {
  switch (strengthBand(value)) {
    case "light":
      return 1;
    case "balanced":
      return 2;
    case "strong":
      return 3;
    case "deep":
      return 4;
  }
}

export function rewriteChance(mode: RewriteMode, strength: number, word: string): number {
  const normalizedStrength = clamp(strength, 0, 100) / 100;
  const lengthBonus = clamp((word.length - 4) * 0.015, 0, 0.12);

  const modeBias: Record<RewriteMode, number> = {
    personal: 0.04,
    warmth: 0.12,
    standard: 0.02,
    fluency: 0.06,
    warm: 0.08,
    formal: 0.08,
    simple: -0.05,
    creative: 0.1,
    expand: 0.1,
    shorten: 0.06,
  };

  return clamp(0.08 + normalizedStrength * 0.68 + lengthBonus + modeBias[mode], 0.05, 0.94);
}

export function seededHash(input: string): number {
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function seededFloat(input: string): number {
  return seededHash(input) / 0xffffffff;
}
