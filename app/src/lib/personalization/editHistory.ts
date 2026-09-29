import type { EditEvent, EditEventSource, EditEventType } from "./approvalMemory";
import type { ProtectedSpan } from "@/lib/safety/protectedContent";

export interface TextEditMetadata {
  type?: EditEventType;
  originalFragment?: string;
  replacementFragment?: string;
  sentenceIndex?: number;
  tokenIndex?: number;
}

export interface ParaphraseSession {
  startedAt: number;
  originalText: string;
  generatedText: string;
  currentEditedText: string;
  protectedSpans: ProtectedSpan[];
  groupedEditEvents: EditEvent[];
  generationMetadata: {
    source: string;
    durationMs: number;
    retryCount: number;
    retrievedExampleCount: number;
    safe: boolean;
    notice?: string;
    /** Style that produced this draft. Sessions restored from older builds may
     *  omit it, so the UI treats a missing value as "unknown origin" rather
     *  than assuming the currently selected style. */
    mode?: string;
    strength?: number;
  };
}

function commonPrefixLength(left: string, right: string): number {
  let index = 0;
  while (index < left.length && index < right.length && left[index] === right[index]) index += 1;
  return index;
}

function commonSuffixLength(left: string, right: string, prefix: number): number {
  let length = 0;
  while (
    length < left.length - prefix &&
    length < right.length - prefix &&
    left[left.length - 1 - length] === right[right.length - 1 - length]
  ) {
    length += 1;
  }
  return length;
}

function isWordCharacter(value: string | undefined): boolean {
  return Boolean(value && /[A-Za-z0-9]/.test(value));
}

function expandDiffToWordBoundaries(
  previousText: string,
  nextText: string,
  prefix: number,
  suffix: number
): { prefix: number; suffix: number } {
  let expandedPrefix = prefix;
  let expandedSuffix = suffix;

  // Character-level diffs can split a replacement inside a word when the
  // old and new words share a prefix, such as "manager" -> "supervisor".
  // Move the edit start back to the word boundary so approval memory learns
  // the actual term rather than an unusable fragment.
  // Also handle an insertion or deletion that reaches the end of one word,
  // such as "help" -> "helpful" or "manager" -> "manage".
  while (
    expandedPrefix > 0 &&
    isWordCharacter(previousText[expandedPrefix - 1]) &&
    (isWordCharacter(previousText[expandedPrefix]) || isWordCharacter(nextText[expandedPrefix]))
  ) {
    expandedPrefix -= 1;
  }

  // A shared final character can make the diff end inside both words. Pull
  // that suffix out of the common region so the replacement ends at a word
  // boundary as well.
  while (expandedSuffix > 0) {
    const previousStart = previousText.length - expandedSuffix;
    const nextStart = nextText.length - expandedSuffix;
    if (
      previousStart <= expandedPrefix ||
      nextStart <= expandedPrefix ||
      !isWordCharacter(previousText[previousStart - 1]) ||
      !isWordCharacter(previousText[previousStart]) ||
      !isWordCharacter(nextText[nextStart - 1]) ||
      !isWordCharacter(nextText[nextStart])
    ) break;
    expandedSuffix -= 1;
  }

  return { prefix: expandedPrefix, suffix: expandedSuffix };
}

export function describeTextEdit(
  previousText: string,
  nextText: string,
  source: EditEventSource,
  metadata: TextEditMetadata = {},
  relativeTimestamp = 0
): EditEvent {
  const commonPrefix = commonPrefixLength(previousText, nextText);
  const commonSuffix = commonSuffixLength(previousText, nextText, commonPrefix);
  const expandedDiff = expandDiffToWordBoundaries(previousText, nextText, commonPrefix, commonSuffix);
  const originalEnd = Math.max(expandedDiff.prefix, previousText.length - expandedDiff.suffix);
  const replacementEnd = Math.max(expandedDiff.prefix, nextText.length - expandedDiff.suffix);
  const originalFragment = metadata.originalFragment ?? previousText.slice(expandedDiff.prefix, originalEnd);
  const replacementFragment = metadata.replacementFragment ?? nextText.slice(expandedDiff.prefix, replacementEnd);

  let type: EditEventType = metadata.type ?? "typed-replacement";
  if (!metadata.type) {
    if (source === "paste") type = "pasted-revision";
    else if (!originalFragment && replacementFragment) type = "insertion";
    else if (originalFragment && !replacementFragment) type = "deletion";
  }

  return {
    id: `edit-${relativeTimestamp}-${Math.random().toString(36).slice(2, 8)}`,
    sequence: 0,
    type,
    originalFragment,
    replacementFragment,
    sentenceIndex: metadata.sentenceIndex,
    tokenIndex: metadata.tokenIndex,
    source,
    relativeTimestamp,
  };
}

export function appendGroupedEdit(events: EditEvent[], event: EditEvent): EditEvent[] {
  const nextEvent = { ...event, sequence: events.length + 1 };
  const previous = events[events.length - 1];
  const canMergeTyped =
    previous &&
    previous.source === "typed" &&
    nextEvent.source === "typed" &&
    nextEvent.relativeTimestamp - previous.relativeTimestamp <= 1200;

  if (!canMergeTyped) return [...events, nextEvent];

  return [
    ...events.slice(0, -1),
    {
      ...previous,
      replacementFragment: `${previous.replacementFragment}${nextEvent.replacementFragment}`,
      sequence: previous.sequence,
      relativeTimestamp: nextEvent.relativeTimestamp,
    },
  ];
}

export function summarizeEditEvents(events: EditEvent[]): Record<string, number> {
  return events.reduce<Record<string, number>>((summary, event) => {
    summary[event.type] = (summary[event.type] ?? 0) + 1;
    return summary;
  }, {});
}
