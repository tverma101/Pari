import { preferredIndefiniteArticle } from "./articleSound";
import { splitSentences } from "./sentenceSplit";

export type GrammarIssueSeverity = "low" | "medium" | "high";

export interface GrammarIssue {
  id: string;
  severity: GrammarIssueSeverity;
  label: string;
  detail: string;
  sample?: string;
  start?: number;
  end?: number;
}

function wordCount(value: string): number {
  return value.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g)?.length ?? 0;
}

function compactSample(value: string, maxLength = 72): string {
  const compacted = value.trim().replace(/\s+/g, " ");
  return compacted.length > maxLength ? `${compacted.slice(0, maxLength - 1)}...` : compacted;
}

function hardIssue(
  id: string,
  label: string,
  detail: string,
  severity: GrammarIssueSeverity = "medium",
  sample?: string,
  start?: number,
  end?: number
): GrammarIssue {
  return { id, label, detail, severity, sample, start, end };
}

const NON_PLURAL_S_WORDS = new Set([
  "analysis",
  "basis",
  "business",
  "class",
  "crisis",
  "economics",
  "gas",
  "information",
  "mathematics",
  "news",
  "physics",
  "politics",
  "process",
  "status",
  "series",
  "species",
  "thesis",
]);

function hardGrammarIssues(text: string): GrammarIssue[] {
  const issues: GrammarIssue[] = [];
  const add = (issue: GrammarIssue) => issues.push(issue);

  const articlePattern = /\b(a|an)\s+([A-Za-z][A-Za-z'-]*)\b/gi;
  let articleMatch: RegExpExecArray | null;
  while ((articleMatch = articlePattern.exec(text)) !== null) {
    const article = articleMatch[1].toLowerCase();
    const word = articleMatch[2];
    const expected = preferredIndefiniteArticle(word);
    if (expected && article !== expected) {
      add(hardIssue(
        "article-mismatch",
        "Article agreement",
        `Use “${expected} ${word}” instead of “${article} ${word}”.`,
        "medium",
        articleMatch[0],
        articleMatch.index,
        articleMatch.index + articleMatch[0].length
      ));
    }
  }

  if (/\s{2,}/.test(text)) {
    add(hardIssue("spacing-double", "Extra spacing", "Multiple spaces make the rewrite feel uneven.", "low"));
  }

  const repeatedWord = text.match(/\b([A-Za-z]+)\s+\1\b/i);
  if (repeatedWord && repeatedWord.index !== undefined) {
    add(hardIssue(
      "repeated-word",
      "Repeated word",
      "A repeated adjacent word usually needs one copy removed.",
      "medium",
      repeatedWord[0],
      repeatedWord.index,
      repeatedWord.index + repeatedWord[0].length
    ));
  }

  const singularSubject = text.match(
    /\b(?:he|she|it|this|that|someone|everyone|each|every|either|neither|nothing|something)\s+(?:are|were|have|do)\b/i
  );
  if (singularSubject && singularSubject.index !== undefined) {
    add(hardIssue(
      "subject-verb-agreement",
      "Subject–verb agreement",
      "This singular subject needs a singular verb.",
      "high",
      singularSubject[0],
      singularSubject.index,
      singularSubject.index + singularSubject[0].length
    ));
  }

  const pluralSubject = text.match(
    /\b(?:we|they|these|those|people|children|students|writers|users|sentences|ideas|tools|results|problems|tasks|assignments)\s+(?:is|was|has|does)\b/i
  );
  if (pluralSubject && pluralSubject.index !== undefined) {
    add(hardIssue(
      "subject-verb-agreement",
      "Subject–verb agreement",
      "This plural subject needs a plural verb.",
      "high",
      pluralSubject[0],
      pluralSubject.index,
      pluralSubject.index + pluralSubject[0].length
    ));
  }

  const firstSecondPerson = text.match(
    /\bI\s+(?:is|has|does)\b|\byou\s+(?:is|was|has|does)\b|\b(?:we|they|these|those|people|students|writers|users)\s+doesn't\b|\b(?:he|she|it|this|that|someone|everyone|each|every)\s+don't\b/i
  );
  if (firstSecondPerson && firstSecondPerson.index !== undefined) {
    add(hardIssue(
      "subject-verb-agreement",
      "Subject–verb agreement",
      "The subject and verb should agree in person and number.",
      "high",
      firstSecondPerson[0],
      firstSecondPerson.index,
      firstSecondPerson.index + firstSecondPerson[0].length
    ));
  }

  const pluralNoun = text.match(/\b([A-Za-z][A-Za-z'-]*s)\s+(is|was|has|does)\b/i);
  if (
    pluralNoun &&
    pluralNoun.index !== undefined &&
    !NON_PLURAL_S_WORDS.has(pluralNoun[1].toLowerCase()) &&
    !/(?:ss|us|is)$/.test(pluralNoun[1].toLowerCase())
  ) {
    add(hardIssue(
      "subject-verb-agreement",
      "Subject–verb agreement",
      "A plural noun should not take this singular verb form.",
      "high",
      pluralNoun[0],
      pluralNoun.index,
      pluralNoun.index + pluralNoun[0].length
    ));
  }

  const thereAgreement = text.match(
    /\bthere\s+(?:is|was)\s+(?:(?:the|these|those|many|several)\s+)?[A-Za-z][A-Za-z'-]*s\b|\bthere\s+(?:are|were)\s+(?:a|an|each|every|one)\s+[A-Za-z][A-Za-z'-]*\b/i
  );
  if (thereAgreement && thereAgreement.index !== undefined) {
    add(hardIssue(
      "subject-verb-agreement",
      "Subject–verb agreement",
      "The verb should agree with the noun that follows “there.”",
      "high",
      thereAgreement[0],
      thereAgreement.index,
      thereAgreement.index + thereAgreement[0].length
    ));
  }

  const modalAgreement = text.match(
    /\b(?:can|could|may|might|must|shall|should|will|would)\s+(?:is|are|was|were|has|does|[A-Za-z]+(?:s|ing))\b/i
  );
  if (modalAgreement && modalAgreement.index !== undefined) {
    add(hardIssue(
      "modal-verb-agreement",
      "Verb form",
      "A modal verb should be followed by the base form of the verb.",
      "high",
      modalAgreement[0],
      modalAgreement.index,
      modalAgreement.index + modalAgreement[0].length
    ));
  }

  const pronounCase = text.match(/\bbetween\s+(?:you|he|she|they|we)\s+and\s+I\b|\bbetween\s+you\s+and\s+(?:he|she)\b/i);
  if (pronounCase && pronounCase.index !== undefined) {
    add(hardIssue(
      "pronoun-case",
      "Pronoun case",
      "Use an object pronoun after “between,” such as “me” or “them.”",
      "medium",
      pronounCase[0],
      pronounCase.index,
      pronounCase.index + pronounCase[0].length
    ));
  }

  const commonGrammar = text.match(
    /\b(?:could|should|would|might|must)\s+of\b|\balot\b|\b(?:more|most)\s+(?:better|worse|easier|harder|simpler|best|worst)\b/i
  );
  if (commonGrammar && commonGrammar.index !== undefined) {
    add(hardIssue(
      "common-grammar-pattern",
      "Common grammar pattern",
      "Use the standard verb or comparison form here, such as “could have,” “a lot,” or “better.”",
      "high",
      commonGrammar[0],
      commonGrammar.index,
      commonGrammar.index + commonGrammar[0].length
    ));
  }

  const quantifierAgreement = text.match(
    /\b(?:a number of|a lot of|lots of|plenty of|a few|many|several|both|numerous)\s+[A-Za-z][A-Za-z'-]*s\s+(?:is|was|has|does)\b|\bthe number of\s+[A-Za-z][A-Za-z'-]*s\s+(?:are|were|have|do)\b|\b(?:one|each|every|either|neither)\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z'-]*s\s+(?:are|were|have|do)\b|\bboth\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z'-]*\s+(?:is|was|has|does)\b|\bthere\s+(?:is|was)\s+(?:two|three|four|five|many|several|multiple|both|these|those)\b|\bthere's\s+(?:two|three|four|five|many|several|multiple|both|these|those)\b/i
  );
  if (quantifierAgreement && quantifierAgreement.index !== undefined) {
    add(hardIssue(
      "quantifier-agreement",
      "Quantifier agreement",
      "The verb should agree with the grammatical head of this quantifier phrase, such as “one of … is” or “a number of … are.”",
      "high",
      quantifierAgreement[0],
      quantifierAgreement.index,
      quantifierAgreement.index + quantifierAgreement[0].length,
    ));
  }

  const clauseSubject = "(?:I|we|you|he|she|they|it|this|that|there|people|students|users|(?:the|a|an|my|your|our|their|some|any|no|each|every|one|both|many|several)\\s+[A-Za-z][A-Za-z'-]*(?:\\s+[A-Za-z][A-Za-z'-]*){0,2})";
  const finiteVerb = "(?:is|are|was|were|has|have|had|can|could|may|might|must|should|will|would|do|does|did|[A-Za-z]+(?:s|ed)(?!['’]))";
  const independentClause = new RegExp(`^(?:${clauseSubject})\\s+[^,.;!?]*\\b${finiteVerb}\\b`, "i");
  const commaSplicePattern = new RegExp(`,\\s+(?=${clauseSubject}\\s+${finiteVerb}\\b)`, "gi");
  let commaSplice: RegExpExecArray | null = null;
  let possibleCommaSplice: RegExpExecArray | null;
  while ((possibleCommaSplice = commaSplicePattern.exec(text)) !== null) {
    const sentenceStart = Math.max(
      text.lastIndexOf(".", possibleCommaSplice.index - 1),
      text.lastIndexOf("!", possibleCommaSplice.index - 1),
      text.lastIndexOf("?", possibleCommaSplice.index - 1),
    ) + 1;
    const leftClause = text.slice(sentenceStart, possibleCommaSplice.index).trim();
    if (/^(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b/i.test(leftClause)) continue;
    if (/\b(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b[^,.;!?]*$/i.test(leftClause)) continue;
    if (independentClause.test(leftClause)) {
      commaSplice = possibleCommaSplice;
      break;
    }
  }
  if (commaSplice && commaSplice.index !== undefined) {
    add(hardIssue(
      "comma-splice",
      "Sentence boundary",
      "Two complete clauses need a conjunction, semicolon, or full stop instead of a comma alone.",
      "high",
      commaSplice[0].trim(),
      commaSplice.index,
      commaSplice.index + commaSplice[0].length,
    ));
  }

  return issues;
}

export function grammarSafetyIssues(text: string): GrammarIssue[] {
  return hardGrammarIssues(text);
}

export function mergeGrammarIssues(...issueLists: GrammarIssue[][]): GrammarIssue[] {
  const merged: GrammarIssue[] = [];
  const severityRank: Record<GrammarIssueSeverity, number> = { high: 0, medium: 1, low: 2 };

  for (const issue of issueLists.flat()) {
    const duplicate = merged.some((existing) => {
      if (existing.id === issue.id) return true;
      if (
        typeof existing.start !== "number" ||
        typeof existing.end !== "number" ||
        typeof issue.start !== "number" ||
        typeof issue.end !== "number"
      ) {
        return false;
      }
      return existing.start === issue.start && existing.end === issue.end;
    });
    if (!duplicate) merged.push(issue);
  }

  return merged
    .sort((left, right) => {
      const leftStart = left.start ?? Number.MAX_SAFE_INTEGER;
      const rightStart = right.start ?? Number.MAX_SAFE_INTEGER;
      return leftStart - rightStart || severityRank[left.severity] - severityRank[right.severity];
    })
    .slice(0, 24);
}

export function analyzeGrammar(text: string): GrammarIssue[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  const issues: GrammarIssue[] = hardGrammarIssues(text);
  const sentences = splitSentences(text);

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

  return issues.filter((issue, index, all) => all.findIndex((candidate) => candidate.id === issue.id) === index).slice(0, 12);
}

export function grammarHealthScore(issues: GrammarIssue[]): number {
  const penalty = issues.reduce((total, issue) => {
    if (issue.severity === "high") return total + 18;
    if (issue.severity === "medium") return total + 10;
    return total + 5;
  }, 0);

  return Math.max(0, Math.min(100, 100 - penalty));
}
