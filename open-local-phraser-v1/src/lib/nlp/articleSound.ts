export type ArticleSound = "vowel" | "consonant" | "ambiguous";

/**
 * Conservative pronunciation class for choosing English indefinite articles.
 *
 * `a`/`an` follows the initial sound, not the first written letter. This
 * helper intentionally returns `ambiguous` when spelling alone is not enough
 * to choose safely (notably initialisms and dialect-sensitive `herb`). A
 * deterministic paraphraser should preserve the writer's article in those
 * cases rather than guess a pronunciation.
 */
export function articleSound(value: string): ArticleSound {
  const raw = value.trim();
  if (!raw) return "ambiguous";

  // Initialisms and letter names cannot be classified safely from their first
  // written character alone: compare MRI, URL, NASA, and X-ray.
  if (/^[A-Z]{2,}(?:[0-9]*|[-'][A-Za-z0-9-]+)?$/.test(raw) || /^[A-Z]-[A-Za-z]/.test(raw)) {
    return "ambiguous";
  }

  const normalized = raw.toLowerCase();

  // Cambridge records `herb` with /h/ in UK English and without /h/ in US
  // English. Related forms such as herbal share the same dialect split, so do
  // not force either article without an explicit dialect preference.
  if (/^herb(?:$|al\b|age\b|ology\b)/.test(normalized)) return "ambiguous";

  if (/^(?:honest|honor|honour|hour|heir)\b/.test(normalized)) return "vowel";
  if (/^(?:ewe|euro|one|once|uniform|unique|unit|united|university|use|useful|usefully|user|usual)\b/.test(normalized)) {
    return "consonant";
  }

  return /^[aeiou]/.test(normalized) ? "vowel" : "consonant";
}

export function preferredIndefiniteArticle(value: string): "a" | "an" | null {
  const sound = articleSound(value);
  if (sound === "vowel") return "an";
  if (sound === "consonant") return "a";
  return null;
}

export function isIndefiniteArticleCompatible(article: string, value: string): boolean {
  const expected = preferredIndefiniteArticle(value);
  return expected === null || article.trim().toLowerCase() === expected;
}
