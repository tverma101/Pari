export type RewriteMode =
  | "personal"
  | "warmth"
  | "standard"
  | "fluency"
  | "warm"
  | "formal"
  | "simple"
  | "creative"
  | "expand"
  | "shorten";

export type AppMode = RewriteMode | `custom:${string}`;

export type StrengthLevel = 1 | 2 | 3 | 4;

export type RiskLevel = "low" | "medium" | "high";

export type PartOfSpeech = "verb" | "noun" | "adjective" | "adverb" | "phrase" | "unknown";

export type ThemePreference = "light" | "dark" | "system";

export function isWarmthMode(mode: RewriteMode): boolean {
  return mode === "warmth" || mode === "warm";
}
