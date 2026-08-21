import type { RewriteMode, StrengthLevel } from "@/lib/types";

export const MODE_OPTIONS: { value: RewriteMode; label: string; hint: string }[] = [
  { value: "personal", label: "Personal", hint: "Warm, clear, and explanatory" },
  { value: "warmth", label: "Warmth", hint: "Noticeably more human, kind, and natural" },
];

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function strengthLabel(value: number): string {
  if (value <= 18) return "Light";
  if (value <= 40) return "Balanced";
  if (value <= 68) return "Strong";
  return "Deep";
}

export function percentToStrengthLevel(value: number): StrengthLevel {
  if (value <= 24) return 1;
  if (value <= 49) return 2;
  if (value <= 74) return 3;
  return 4;
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
