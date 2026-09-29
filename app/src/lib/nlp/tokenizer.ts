export interface RawToken {
  type: "word" | "gap";
  text: string;
  start: number;
  end: number;
}

const WORD_RE = /([A-Za-z]+(?:[-'][A-Za-z]+)*)|([^A-Za-z]+)/g;

export function normalizeWord(value: string): string {
  return value.toLowerCase();
}

export function trimPhrase(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

export function tokenize(text: string): RawToken[] {
  const tokens: RawToken[] = [];
  WORD_RE.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = WORD_RE.exec(text)) !== null) {
    const tokenText = match[0];
    const isWord = /[A-Za-z]/.test(tokenText);
    tokens.push({
      type: isWord ? "word" : "gap",
      text: tokenText,
      start: match.index,
      end: match.index + tokenText.length,
    });
  }

  return tokens;
}

export function matchCase(original: string, replacement: string): string {
  if (!original) return replacement;

  if (original === original.toUpperCase()) {
    return replacement.toUpperCase();
  }

  if (original[0] === original[0].toUpperCase()) {
    return replacement[0].toUpperCase() + replacement.slice(1);
  }

  return replacement;
}

export function countWords(text: string): number {
  const matches = text.trim().match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g);
  return matches ? matches.length : 0;
}
