/**
 * Simple string hash using FNV-1a algorithm.
 */
export function fnv1a(str: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

/**
 * Create a short (6-char) hash for use in IDs.
 */
export function shortHash(str: string): string {
  return fnv1a(str).substring(0, 6);
}

/**
 * Create a deterministic ID from a set of inputs.
 */
export function deterministicId(...parts: string[]): string {
  return shortHash(parts.join("|"));
}
