import type { SentenceSpan } from "../core/types.js";

/**
 * Set of abbreviations that should NOT trigger sentence breaks when followed by a period.
 */
const ABBREVIATIONS = new Set([
  "dr", "mr", "mrs", "ms", "prof", "rev", "sr", "jr", "st", "ave", "blvd", "rd",
  "etc", "vs", "inc", "ltd", "co", "corp", "dept", "est", "govt", "mt", "ft",
  "gen", "sgt", "capt", "lt", "col", "maj", "cpl", "pvt",
  "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
  "approx", "appt", "apt", "assn", "asst", "attn", "bldg", "bro", "capt",
  "cf", "cia", "dept", "doc", "drs", "esp", "esq", "fbi", "gov", "hr",
  "intro", "misc", "mlle", "mme", "no", "nos", "plf", "pl", "pm", "pp",
  "pres", "prof", "pvt", "rep", "res", "revd", "sec", "sen", "sgt", "sic",
  "soc", "sq", "subj", "supt", "surg", "tel", "treas", "univ", "vp",
]);

/**
 * Patterns that look like sentence breaks but aren't:
 * - "U.S." style acronyms
 * - "3.5" style decimals
 * - "e.g." and "i.e."
 */
const NON_BREAKING_PATTERNS = [
  // U.S., U.K., U.A.E.
  /\b[A-Z]\.(?:[A-Z]\.)+/g,
  // e.g., i.e., etc. (when followed by comma or space)
  /\b(?:e\.g|i\.e|etc)\.(?=\s|,|$)/gi,
  // Abbreviations followed by period then space+lowercase (Dr. Smith)
  /\b(?:[A-Z][a-z]*)\.(?=[\s,;:!?]+\p{Lu})/gu,
  // Single capital letter followed by period (initial: J. Smith)
  /\b[A-Z]\.(?=\s+[A-Z][a-z])/g,
];

/**
 * Conservative sentence splitter that handles:
 * - Abbreviations (Dr., Mr., U.S., etc.)
 * - Decimals (3.5)
 * - Citations ((Smith, 2020))
 * - Ellipses
 * - Quoted sentences
 * - Parentheticals
 */
export function splitSentences(text: string): SentenceSpan[] {
  if (!text || !text.trim()) return [];

  const protectedText = preProtectNonBreaks(text);
  const rawSpans = splitOnBreaks(protectedText);
  const adjusted = postProcessAbbreviations(rawSpans, protectedText, text);

  return adjusted.map((span, index) => ({
    text: span.text,
    start: span.start,
    end: span.end,
    index,
  }));
}

/**
 * Temporarily replace non-breaking periods with a sentinel
 * so the splitter doesn't break on them.
 */
function preProtectNonBreaks(text: string): string {
  let protectedText = text;

  // Protect decimal numbers: 3.5, 0.75, etc.
  protectedText = protectedText.replace(/\b(\d+)\.(\d+)\b/g, (_match, int, dec) => {
    return `DEC_${int}_${dec}`;
  });

  // Protect known abbreviations with trailing period + space
  protectedText = protectedText.replace(
    /\b([A-Za-z]{1,3})\.(?=\s+[a-z])/g,
    (_match, abbr) => {
      const lower = abbr.toLowerCase();
      if (ABBREVIATIONS.has(lower)) {
        return `ABBR_${lower}_`;
      }
      return _match;
    }
  );

  // Protect U.S., U.K., etc.
  protectedText = protectedText.replace(/\b([A-Z])\.([A-Z])\./g, (_match, a, b) => {
    return `US_PAIR_${a}_${b}_`;
  });

  // Protect e.g., i.e., etc.
  protectedText = protectedText.replace(
    /\b(e\.g|i\.e|etc)\.(?=\s|,)/gi,
    (_match, prefix) => {
      return `ABBR_${prefix.replace(".", "_")}_`;
    }
  );

  return protectedText;
}

/**
 * Post-process to restore protected non-breaks and fix any splits
 * that happened inside protected abbreviations.
 */
function postProcessAbbreviations(
  spans: SentenceSpan[],
  protectedText: string,
  originalText: string
): SentenceSpan[] {
  return spans.map((span) => {
    // Restore original text for this span range
    let original = span.text;

    // Restore decimal numbers
    original = original.replace(/DEC_(\d+)_(\d+)/g, (_match, intPart, decPart) => {
      return `${intPart}.${decPart}`;
    });

    // Restore abbreviations
    original = original.replace(/ABBR_([a-z]+)_/g, (_match, abbr) => {
      return `${abbr}.`;
    });

    // Restore U.S.-style pairs
    original = original.replace(/US_PAIR_([A-Z])_([A-Z])_/g, (_match, a, b) => {
      return `${a}.${b}.`;
    });

    // Restore e.g./i.e.
    original = original.replace(/ABBR_([a-z])_([a-z])_/g, (_match, a, b) => {
      return `${a}.${b}.`;
    });

    return {
      text: original,
      start: span.start,
      end: span.end,
      index: span.index,
    };
  });
}

/**
 * Split text at sentence boundaries: . ! ? followed by whitespace or end.
 */
function splitOnBreaks(text: string, startIndex: number = 0): SentenceSpan[] {
  const spans: SentenceSpan[] = [];

  // Split on sentence-ending punctuation followed by whitespace+capitalized word or end
  const sentenceEndRegex = /(?<=[.!?])(?:\s+(?=[\p{Lu}"'“‘(]|\s*$)|$)/gu;

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  sentenceEndRegex.lastIndex = 0;

  while ((match = sentenceEndRegex.exec(text)) !== null) {
    const end = match.index + match[0].length;
    const sentenceText = text.substring(lastIndex, end).trim();
    if (sentenceText) {
      spans.push({
        text: sentenceText,
        start: lastIndex,
        end,
        index: spans.length,
      });
    }
    lastIndex = end;
  }

  // Add remaining text after last split
  if (lastIndex < text.length) {
    const remaining = text.substring(lastIndex).trim();
    if (remaining) {
      spans.push({
        text: remaining,
        start: lastIndex,
        end: text.length,
        index: spans.length,
      });
    }
  }

  // Fallback: if no splits were found, return the whole text
  if (spans.length === 0 && text.trim()) {
    spans.push({
      text: text.trim(),
      start: text.search(/\S/),
      end: text.trim().length,
      index: 0,
    });
  }

  return spans;
}

/**
 * Count sentences in text.
 */
export function countSentences(text: string): number {
  return splitSentences(text).length;
}

/**
 * Find which sentence contains a given character offset.
 */
export function getSentenceAtOffset(
  text: string,
  offset: number
): SentenceSpan | null {
  const sentences = splitSentences(text);
  return sentences.find((s) => offset >= s.start && offset <= s.end) ?? null;
}
