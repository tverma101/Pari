export interface SentenceSpan {
  text: string;
  start: number;
  end: number;
}

const SENTENCE_RE = /[^.!?\n]+(?:[.!?]+["'”’»)\]]*(?=\s|$)|$)/g;
const INTERNAL_PERIOD = "\uE010";

function maskInternalPeriods(text: string): string {
  // Keep punctuation inside factual tokens from becoming sentence starts on
  // the next regex search. The replacement is one code unit, so all match
  // indexes remain aligned with the original text when spans are returned.
  return text
    .replace(/\b[AP]\.M\./gi, (match, offset: number, source: string) => {
      const firstPeriod = match.indexOf(".");
      const secondPeriod = match.lastIndexOf(".");
      const after = source.slice(offset + match.length);
      const nextNonSpace = after.match(/\S/)?.[0] ?? "";
      const likelySentenceEnd = !nextNonSpace || !/[a-z]/.test(nextNonSpace);
      const maskedFirst = `${match.slice(0, firstPeriod)}${INTERNAL_PERIOD}${match.slice(firstPeriod + 1, secondPeriod)}`;
      return `${maskedFirst}${likelySentenceEnd ? "." : INTERNAL_PERIOD}`;
    })
    .replace(/\.(?=\S)(?!["'”’»)\]](?:\s|$))/g, INTERNAL_PERIOD);
}

export function splitSentences(text: string): SentenceSpan[] {
  const spans: SentenceSpan[] = [];
  const maskedText = maskInternalPeriods(text);
  SENTENCE_RE.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = SENTENCE_RE.exec(maskedText)) !== null) {
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
