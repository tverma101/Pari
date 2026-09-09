/**
 * Normalize punctuation spacing without breaking common meridiem
 * abbreviations such as "3 a.m." and "5 p.m.".
 *
 * The finalizer runs several conservative text passes. Keeping this rule in
 * one place prevents a later pass from undoing an earlier abbreviation fix.
 */
function isMeridiemContinuation(text: string, offset: number): boolean {
  const before = text.slice(0, offset + 1);
  const after = text.slice(offset + 1);
  return /(?:^|\s)(?:a|p)\.$/i.test(before) && /^\s*m(?:\b|[.\s])/i.test(after);
}

function isMeridiemSentenceBoundary(text: string, offset: number): boolean {
  const before = text.slice(0, offset + 1);
  return /\b(?:a|p)\.m\.$/i.test(before);
}

export function repairMeridiemAbbreviations(text: string): string {
  return text.replace(/\b([ap])\.\s*m\.?/gi, (_match, marker: string) => `${marker.toLowerCase()}.m.`);
}

export function repairPunctuationSpacing(text: string): string {
  const normalized = repairMeridiemAbbreviations(text);
  return normalized.replace(/([,.;!?])(?=[A-Za-z])/g, (match, punctuation: string, offset: number, fullText: string) => {
    if (punctuation === "." && isMeridiemContinuation(fullText, offset)) return match;
    return `${punctuation} `;
  });
}

export function capitalizeSentenceStarts(text: string): string {
  return text.replace(/(^|[.!?]\s+)([a-z])/g, (match, prefix: string, letter: string, offset: number, fullText: string) => {
    if (isMeridiemContinuation(fullText, offset) || isMeridiemSentenceBoundary(fullText, offset)) return match;
    return `${prefix}${letter.toUpperCase()}`;
  });
}
