import * as bridge from "../generation/pythonBridge.js";

/**
 * Compute semantic similarity between original and candidate text.
 * Returns a score between 0 and 1.
 *
 * Uses sentence-transformers via Python subprocess.
 * Falls back to simple Jaccard/word-overlap similarity if Python is unavailable.
 */
export function computeSemanticSimilarity(
  original: string,
  candidate: string,
  model = "all-MiniLM-L6-v2"
): number {
  try {
    const result = bridge.embeddingSimilarity(original, candidate, model);
    if (result.success) {
      const data = result.data as unknown as bridge.EmbeddingOutput;
      if (data.similarity !== undefined) {
        // Normalize from [-1, 1] to [0, 1]
        return Math.max(0, Math.min(1, (data.similarity + 1) / 2));
      }
    }
  } catch {
    // Fall through to fallback
  }

  // Fallback: normalized word overlap (Jaccard)
  return computeJaccardSimilarity(original, candidate);
}

/**
 * Jaccard-like word overlap similarity (fallback when no embedding model).
 */
export function computeJaccardSimilarity(text1: string, text2: string): number {
  const words1 = new Set(text1.toLowerCase().split(/\s+/).filter((w) => w.length > 2));
  const words2 = new Set(text2.toLowerCase().split(/\s+/).filter((w) => w.length > 2));

  if (words1.size === 0 || words2.size === 0) return 0;

  let intersection = 0;
  for (const w of words1) {
    if (words2.has(w)) intersection++;
  }

  const union = words1.size + words2.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

/**
 * Compute embedding vectors for a text (returns as number array).
 */
export function getEmbedding(
  text: string,
  model = "all-MiniLM-L6-v2"
): number[] | null {
  try {
    const result = bridge.encodeSentences([text], model);
    if (result.success) {
      const data = result.data as unknown as bridge.EmbeddingOutput;
      if (data.embeddings && data.embeddings.length > 0) {
        return data.embeddings[0];
      }
    }
  } catch {
    // Not available
  }
  return null;
}
