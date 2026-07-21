export interface SentenceSpan {
  text: string;
  start: number;
  end: number;
}

const SENTENCE_RE = /[^.!?\n]+(?:[.!?]+(?=\s|$)|$)/g;

export function splitSentences(text: string): SentenceSpan[] {
  const spans: SentenceSpan[] = [];
  SENTENCE_RE.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = SENTENCE_RE.exec(text)) !== null) {
    const raw = match[0];
    const leadingWhitespace = raw.match(/^\s*/)?.[0].length ?? 0;
    const trailingWhitespace = raw.match(/\s*$/)?.[0].length ?? 0;
    const trimmed = raw.trim();

    if (!trimmed) continue;

    const start = match.index + leadingWhitespace;
    const end = match.index + raw.length - trailingWhitespace;

    spans.push({
      text: text.slice(start, end),
      start,
      end,
    });
  }

  if (spans.length === 0 && text.trim()) {
    return [
      {
        text: text.trim(),
        start: text.search(/\S/),
        end: text.length - (text.match(/\s*$/)?.[0].length ?? 0),
      },
    ];
  }

  return spans;
}

export function countSentences(text: string): number {
  return splitSentences(text).length;
}

export function getSentenceForRange(text: string, start: number, end: number): SentenceSpan {
  const sentences = splitSentences(text);
  const fallbackStart = Math.max(0, Math.min(start, text.length));
  const fallbackEnd = Math.max(fallbackStart, Math.min(end, text.length));

  for (const sentence of sentences) {
    const overlaps = start < sentence.end && end > sentence.start;
    const contains = start >= sentence.start && end <= sentence.end;
    if (contains || overlaps) {
      return sentence;
    }
  }

  return {
    text: text.slice(fallbackStart, fallbackEnd) || text,
    start: fallbackStart,
    end: fallbackEnd || text.length,
  };
}
