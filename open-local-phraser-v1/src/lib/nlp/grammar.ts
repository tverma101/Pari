import { splitSentences } from "./sentenceSplit";

export type GrammarIssueSeverity = "low" | "medium" | "high";

export interface GrammarIssue {
  id: string;
  severity: GrammarIssueSeverity;
  label: string;
  detail: string;
  sample?: string;
}

function wordCount(value: string): number {
  return value.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g)?.length ?? 0;
}

function compactSample(value: string, maxLength = 72): string {
  const compacted = value.trim().replace(/\s+/g, " ");
  return compacted.length > maxLength ? `${compacted.slice(0, maxLength - 1)}...` : compacted;
}

export function analyzeGrammar(text: string): GrammarIssue[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  const issues: GrammarIssue[] = [];
  const sentences = splitSentences(text);

  if (/\s{2,}/.test(text)) {
    issues.push({
      id: "spacing-double",
      severity: "low",
      label: "Extra spacing",
      detail: "Multiple spaces can make a rewritten passage feel uneven.",
    });
  }

  const repeatedWord = text.match(/\b([A-Za-z]+)\s+\1\b/i);
  if (repeatedWord) {
    issues.push({
      id: "repeated-word",
      severity: "medium",
      label: "Repeated word",
      detail: "A repeated adjacent word usually needs one copy removed.",
      sample: repeatedWord[0],
    });
  }

  if (!/[.!?]"?$/.test(trimmed)) {
    issues.push({
      id: "terminal-punctuation",
      severity: "low",
      label: "Ending punctuation",
      detail: "The final sentence does not end with a clear sentence mark.",
    });
  }

  sentences.forEach((sentence, index) => {
    const count = wordCount(sentence.text);
    if (count > 38) {
      issues.push({
        id: `long-sentence-${index}`,
        severity: count > 56 ? "high" : "medium",
        label: "Long sentence",
        detail: `${count} words in one sentence. Consider splitting it for readability.`,
        sample: compactSample(sentence.text),
      });
    }

    if (/\b(?:is|are|was|were|be|been|being)\s+[a-z]+ed\b/i.test(sentence.text)) {
      issues.push({
        id: `passive-voice-${index}`,
        severity: "low",
        label: "Possible passive voice",
        detail: "Passive phrasing can be fine, but active phrasing is often clearer.",
        sample: compactSample(sentence.text),
      });
    }

    const firstLetter = sentence.text.match(/[A-Za-z]/)?.[0];
    if (firstLetter && firstLetter !== firstLetter.toUpperCase()) {
      issues.push({
        id: `sentence-capitalization-${index}`,
        severity: "low",
        label: "Sentence capitalization",
        detail: "Sentence starts are easier to read when the first word is capitalized.",
        sample: compactSample(sentence.text),
      });
    }
  });

  return issues.slice(0, 8);
}

export function grammarHealthScore(issues: GrammarIssue[]): number {
  const penalty = issues.reduce((total, issue) => {
    if (issue.severity === "high") return total + 18;
    if (issue.severity === "medium") return total + 10;
    return total + 5;
  }, 0);

  return Math.max(0, Math.min(100, 100 - penalty));
}
