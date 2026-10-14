import { splitSentences } from "../nlp/sentenceSplit.ts";

export interface TextRange {
  start: number;
  end: number;
}

export interface ScopedTextChange extends TextRange {
  beforeText: string;
  afterText: string;
}

export interface TextHistory {
  undo: string[];
  redo: string[];
  lastSource: "typed" | "discrete" | null;
  lastEditAt: number;
}

const MAX_HISTORY_ITEMS = 100;
const TYPING_GROUP_MS = 850;

export function createTextHistory(): TextHistory {
  return { undo: [], redo: [], lastSource: null, lastEditAt: 0 };
}

export function recordTextEdit(
  history: TextHistory,
  before: string,
  after: string,
  source: "typed" | "discrete",
  now = Date.now(),
): TextHistory {
  if (before === after) return history;
  const canGroup = source === "typed" && history.lastSource === "typed" && now - history.lastEditAt <= TYPING_GROUP_MS;
  return {
    undo: canGroup ? history.undo : [...history.undo, before].slice(-MAX_HISTORY_ITEMS),
    redo: [],
    lastSource: source,
    lastEditAt: now,
  };
}

export function undoTextEdit(history: TextHistory, current: string): { history: TextHistory; text: string } | null {
  if (history.undo.length === 0) return null;
  const text = history.undo[history.undo.length - 1];
  return {
    history: {
      undo: history.undo.slice(0, -1),
      redo: [current, ...history.redo].slice(0, MAX_HISTORY_ITEMS),
      lastSource: null,
      lastEditAt: 0,
    },
    text,
  };
}

export function redoTextEdit(history: TextHistory, current: string): { history: TextHistory; text: string } | null {
  if (history.redo.length === 0) return null;
  const text = history.redo[0];
  return {
    history: {
      undo: [...history.undo, current].slice(-MAX_HISTORY_ITEMS),
      redo: history.redo.slice(1),
      lastSource: null,
      lastEditAt: 0,
    },
    text,
  };
}

export function replaceTextRange(text: string, range: TextRange, replacement: string): string {
  if (range.start < 0 || range.end < range.start || range.end > text.length) return text;
  return `${text.slice(0, range.start)}${replacement}${text.slice(range.end)}`;
}

/** Extract a generated replacement only when the exact surrounding context is unchanged. */
export function extractContainedReplacement(contextText: string, range: TextRange, rewrittenText: string): string | null {
  if (range.start < 0 || range.end < range.start || range.end > contextText.length) return null;
  const leftContext = contextText.slice(0, range.start);
  const rightContext = contextText.slice(range.end);
  const candidate = rewrittenText.trim();
  if (!candidate.startsWith(leftContext) || !candidate.endsWith(rightContext)) return null;
  const end = candidate.length - rightContext.length;
  if (end <= leftContext.length) return null;
  return candidate.slice(leftContext.length, end);
}

export function diffTextRange(before: string, after: string): { start: number; beforeEnd: number; afterEnd: number } {
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start += 1;
  let suffix = 0;
  while (
    suffix < before.length - start &&
    suffix < after.length - start &&
    before[before.length - suffix - 1] === after[after.length - suffix - 1]
  ) suffix += 1;
  return {
    start,
    beforeEnd: before.length - suffix,
    afterEnd: after.length - suffix,
  };
}

export function rebaseScopedChanges(
  changes: ScopedTextChange[],
  before: string,
  after: string,
): ScopedTextChange[] {
  const diff = diffTextRange(before, after);
  if (diff.start === diff.beforeEnd && diff.start === diff.afterEnd) return changes;
  const delta = diff.afterEnd - diff.beforeEnd;
  return changes.flatMap((change) => {
    if (diff.beforeEnd <= change.start) {
      return [{ ...change, start: change.start + delta, end: change.end + delta }];
    }
    if (diff.start >= change.end) return [change];
    return [];
  });
}

export function addScopedChange(
  changes: ScopedTextChange[],
  range: TextRange,
  beforeText: string,
  afterText: string,
): ScopedTextChange[] {
  if (beforeText === afterText) return changes;
  return [...changes, {
    start: range.start,
    end: range.start + afterText.length,
    beforeText,
    afterText,
  }].slice(-MAX_HISTORY_ITEMS);
}

export function findScopedRevert(
  changes: ScopedTextChange[],
  text: string,
  range: TextRange,
): ScopedTextChange | null {
  for (let index = changes.length - 1; index >= 0; index -= 1) {
    const change = changes[index];
    if (
      change.start === range.start &&
      change.end === range.end &&
      text.slice(change.start, change.end) === change.afterText
    ) return change;
  }
  return null;
}

export function removeScopedChange(changes: ScopedTextChange[], target: ScopedTextChange): ScopedTextChange[] {
  const index = changes.lastIndexOf(target);
  return index < 0 ? changes : [...changes.slice(0, index), ...changes.slice(index + 1)];
}

/** Split at explicit clause punctuation without dropping words or changing their order. */
export function splitAtClauseBoundary(text: string): string | null {
  const boundary = text.match(/([;:—,])(\s+)(?=[\p{L}\d])/u);
  if (!boundary || boundary.index === undefined) return null;
  const punctuation = boundary[1];
  const afterBoundary = text.slice(boundary.index + boundary[0].length);
  if (punctuation === "," && !/^(?:and|but|so|yet)\b/i.test(afterBoundary)) return null;
  const before = text.slice(0, boundary.index).trimEnd();
  const after = afterBoundary.replace(/^([a-z])/, (letter) => letter.toUpperCase());
  if (!before || !after || /[.!?]$/.test(before)) return null;
  if (before.split(/\s+/).length < 2 || after.split(/\s+/).length < 2) return null;
  return `${before}. ${after}`;
}

/** Join two complete period-ended sentences with a semicolon, without deleting words. */
export function joinWithSemicolon(text: string): string | null {
  const sentences = splitSentences(text);
  if (sentences.length !== 2) return null;
  const [first, second] = sentences;
  if (!first.text.endsWith(".") || !second.text.endsWith(".")) return null;
  if (!/^\s+$/.test(text.slice(first.end, second.start))) return null;
  return `${text.slice(0, first.end - 1)};${text.slice(first.end)}`;
}

export function joinSelectedSentenceWithNeighbor(
  text: string,
  selection: TextRange,
): (TextRange & { replacement: string; sourceText: string }) | null {
  const selectedText = text.slice(selection.start, selection.end);
  const selectedSentences = splitSentences(selectedText);
  if (selectedSentences.length === 2) {
    const replacement = joinWithSemicolon(selectedText);
    return replacement ? { ...selection, replacement, sourceText: selectedText } : null;
  }

  const sentences = splitSentences(text);
  const index = sentences.findIndex((sentence) =>
    sentence.start === selection.start && sentence.end === selection.end
  );
  if (index < 0) return null;
  const firstIndex = index + 1 < sentences.length ? index : index - 1;
  if (firstIndex < 0) return null;
  const first = sentences[firstIndex];
  const second = sentences[firstIndex + 1];
  const pairRange = { start: first.start, end: second.end };
  const replacement = joinWithSemicolon(text.slice(pairRange.start, pairRange.end));
  return replacement ? { ...pairRange, replacement, sourceText: text.slice(pairRange.start, pairRange.end) } : null;
}
