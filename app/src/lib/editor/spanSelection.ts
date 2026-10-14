import { splitSentences } from "../nlp/sentenceSplit.ts";
import { tokenize } from "../nlp/tokenizer.ts";

export type EditorSpanKind = "word" | "phrase" | "clause" | "sentence" | "multi-sentence";

export interface EditorSpanSelection {
  start: number;
  end: number;
  text: string;
  kind: EditorSpanKind;
}

export interface EditorDomSelection {
  span: EditorSpanSelection;
  range: Range;
}

function isWordCharacter(value: string | undefined): boolean {
  return Boolean(value && /[A-Za-z0-9]/.test(value));
}

function isWordBoundaryCharacter(value: string | undefined): boolean {
  return isWordCharacter(value) || value === "'" || value === "-";
}

function trimSpan(text: string, start: number, end: number): { start: number; end: number } | null {
  let safeStart = Math.max(0, Math.min(start, text.length));
  let safeEnd = Math.max(safeStart, Math.min(end, text.length));

  while (safeStart < safeEnd && /\s/.test(text[safeStart])) safeStart += 1;
  while (safeEnd > safeStart && /\s/.test(text[safeEnd - 1])) safeEnd -= 1;
  if (safeStart >= safeEnd) return null;

  // A browser selection can land inside a word. Expand only when the
  // boundary is genuinely inside a word so punctuation keeps its own edge.
  if (isWordCharacter(text[safeStart]) && isWordCharacter(text[safeStart - 1])) {
    while (safeStart > 0 && isWordBoundaryCharacter(text[safeStart - 1])) safeStart -= 1;
  }
  if (isWordCharacter(text[safeEnd - 1]) && isWordCharacter(text[safeEnd])) {
    while (safeEnd < text.length && isWordBoundaryCharacter(text[safeEnd])) safeEnd += 1;
  }

  return { start: safeStart, end: safeEnd };
}

function selectionWordCount(text: string, start: number, end: number): number {
  return tokenize(text.slice(start, end)).filter((token) => token.type === "word").length;
}

function selectionSentenceCount(text: string, start: number, end: number): number {
  return splitSentences(text).filter((sentence) => sentence.start < end && sentence.end > start).length;
}

export function classifyEditorSpan(
  text: string,
  start: number,
  end: number
): EditorSpanKind {
  const safeStart = Math.max(0, Math.min(start, text.length));
  const safeEnd = Math.max(safeStart, Math.min(end, text.length));
  const selected = text.slice(safeStart, safeEnd).trim();
  const wordCount = selectionWordCount(text, safeStart, safeEnd);
  const sentenceCount = selectionSentenceCount(text, safeStart, safeEnd);

  if (wordCount <= 0) return "phrase";
  if (sentenceCount > 1) return "multi-sentence";
  if (sentenceCount === 1) {
    const sentence = splitSentences(text).find((entry) => entry.start < safeEnd && entry.end > safeStart);
    if (sentence && safeStart <= sentence.start && safeEnd >= sentence.end) return "sentence";
  }
  if (/[,;:()]|\b(?:although|though|because|while|whereas|which|that|if|when)\b/i.test(selected)) {
    return "clause";
  }
  if (wordCount <= 1) return "word";
  if (wordCount <= 8) return "phrase";
  return "clause";
}

export function normalizeEditorSpan(
  text: string,
  start: number,
  end: number
): EditorSpanSelection | null {
  const trimmed = trimSpan(text, start, end);
  if (!trimmed) return null;
  const selected = text.slice(trimmed.start, trimmed.end);
  if (!/[A-Za-z0-9]/.test(selected)) return null;
  return {
    start: trimmed.start,
    end: trimmed.end,
    text: selected,
    kind: classifyEditorSpan(text, trimmed.start, trimmed.end),
  };
}

function nodeTextLength(node: Node): number {
  return node.textContent?.length ?? 0;
}

function isContained(root: HTMLElement, node: Node | null): boolean {
  if (!node) return false;
  if (node === root) return true;
  return typeof root.contains === "function" && root.contains(node);
}

/**
 * Convert a contenteditable DOM point to a character offset in the plain
 * text used to render the editor. The editor intentionally renders only text
 * nodes and inline spans, so recursive text length stays stable across
 * browser selection boundary elements.
 */
export function domPointToTextOffset(
  root: HTMLElement,
  node: Node | null,
  offset: number
): number | null {
  if (!isContained(root, node)) return null;

  let total = 0;
  const visit = (current: Node): number | null => {
    if (current === node) {
      if (current.nodeType === 3) {
        return total + Math.max(0, Math.min(offset, nodeTextLength(current)));
      }
      let childTotal = 0;
      const childCount = Math.max(0, Math.min(offset, current.childNodes.length));
      for (let index = 0; index < childCount; index += 1) {
        childTotal += nodeTextLength(current.childNodes[index]);
      }
      return total + childTotal;
    }

    if (current.nodeType === 3) {
      total += nodeTextLength(current);
      return null;
    }

    for (let index = 0; index < current.childNodes.length; index += 1) {
      const result = visit(current.childNodes[index]);
      if (result !== null) return result;
    }
    return null;
  };

  return visit(root);
}

export function selectionSpanFromRange(
  root: HTMLElement,
  text: string,
  range: Range
): EditorSpanSelection | null {
  const start = domPointToTextOffset(root, range.startContainer, range.startOffset);
  const end = domPointToTextOffset(root, range.endContainer, range.endOffset);
  if (start === null || end === null || start === end) return null;
  return normalizeEditorSpan(text, Math.min(start, end), Math.max(start, end));
}

export function selectionSpanFromDom(
  root: HTMLElement,
  text: string,
  selection: Selection | null = typeof window !== "undefined" ? window.getSelection() : null
): EditorDomSelection | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  if (!isContained(root, range.commonAncestorContainer)) return null;
  const span = selectionSpanFromRange(root, text, range);
  return span ? { span, range: range.cloneRange() } : null;
}

export function applyEditorSpan(
  text: string,
  span: Pick<EditorSpanSelection, "start" | "end">,
  replacement: string
): string {
  return `${text.slice(0, span.start)}${replacement}${text.slice(span.end)}`;
}

export function selectionWordCountForSpan(
  text: string,
  span: Pick<EditorSpanSelection, "start" | "end">
): number {
  return selectionWordCount(text, span.start, span.end);
}

function capitalizeSentence(value: string): string {
  const trimmed = value.trim();
  return trimmed ? trimmed[0].toUpperCase() + trimmed.slice(1) : trimmed;
}

/** Return a conservative two-sentence alternative for a selected span. */
export function splitEditorSpanText(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed || /[.!?]/.test(trimmed.slice(0, -1))) return null;

  const parts = trimmed
    .split(/\s*(?:,|;)\s+|\s+(?:and|but|or|because|when|while)\s+/i)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 2) return null;

  const sentences = parts.map((part, index) => {
    const sentence = /[.!?]$/.test(part) ? part : `${part}.`;
    return index === 0 ? sentence : capitalizeSentence(sentence);
  });
  return sentences.join(" ");
}

/** Return a conservative single-sentence alternative for adjacent sentences. */
export function joinEditorSpanText(left: string, right: string): string | null {
  const first = left.trim().replace(/\s+/g, " ").replace(/[.!?]+$/, "");
  const second = right.trim().replace(/\s+/g, " ").replace(/[.!?]+$/, "");
  if (!first || !second) return null;
  const nextWord = second.split(/\s+/, 1)[0] ?? "";
  const joiner = /^(?:and|but|or|so|yet|because|while|although|which|that)$/i.test(nextWord)
    ? " "
    : /[,;:]$/.test(first)
      ? " "
      : ", and ";
  return `${first}${joiner}${second.charAt(0).toLowerCase()}${second.slice(1)}.`;
}
