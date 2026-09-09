import type { ProtectedSpan } from "@/lib/safety/protectedContent";
import { capitalizeSentenceStarts, repairPunctuationSpacing } from "@/lib/generation/punctuation";

const PLACEHOLDER_RE = /\uE000([\s\S])\uE001/g;

function protectedValuesFor(spans: ProtectedSpan[]): string[] {
  return [...new Set(spans.map((span) => span.text))]
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);
}

function withProtectedPlaceholders(
  text: string,
  protectedValues: string[],
  transform: (masked: string) => string,
): string {
  let masked = text;
  protectedValues.forEach((value, index) => {
    masked = masked.split(value).join("\uE000" + String.fromCharCode(0xE100 + index) + "\uE001");
  });

  const transformed = transform(masked);
  return transformed.replace(
    PLACEHOLDER_RE,
    (_match, index: string) => protectedValues[index.charCodeAt(0) - 0xE100] ?? "",
  );
}

function startsWithVowelSound(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return false;
  if (/^(?:honest|honor|honour|hour|heir|herb)\b/.test(normalized)) return true;
  if (/^(?:ewe|euro|one|once|uniform|unique|unit|united|university|use|useful|user|usual)\b/.test(normalized)) {
    return false;
  }
  return /^[aeiou]/.test(normalized);
}

function preserveCase(original: string, replacement: string): string {
  if (original === original.toUpperCase()) return replacement.toUpperCase();
  if (original[0] === original[0].toUpperCase()) {
    return replacement[0].toUpperCase() + replacement.slice(1);
  }
  return replacement;
}

function repairArticles(text: string): string {
  return text.replace(/\b(a|an)\s+([A-Za-z][A-Za-z'-]*)\b/gi, (_match, article: string, word: string) => {
    const expected = startsWithVowelSound(word) ? "an" : "a";
    return preserveCase(article, expected) + " " + word;
  });
}

function repairAgreement(text: string): string {
  let repaired = text;
  const pluralSubjects = "(?:we|they|these|those|people|children|men|women|students|writers|users|sentences|ideas|tools|results|problems|tasks|assignments)";
  const singularSubjects = "(?:he|she|it|this|that|someone|everyone|each|every|either|neither|nothing|something)";
  const singularSWords = new Set([
    "analysis", "basis", "business", "crisis", "economics", "gas", "news", "physics",
    "politics", "process", "status", "series", "species", "thesis",
  ]);

  repaired = repaired
    .replace(new RegExp("\\b(" + pluralSubjects + ")\\s+is\\b", "gi"), "$1 are")
    .replace(new RegExp("\\b(" + pluralSubjects + ")\\s+was\\b", "gi"), "$1 were")
    .replace(new RegExp("\\b(" + pluralSubjects + ")\\s+has\\b", "gi"), "$1 have")
    .replace(new RegExp("\\b(" + pluralSubjects + ")\\s+does\\b", "gi"), "$1 do")
    .replace(new RegExp("\\b(" + singularSubjects + ")\\s+are\\b", "gi"), "$1 is")
    .replace(new RegExp("\\b(" + singularSubjects + ")\\s+were\\b", "gi"), "$1 was")
    .replace(new RegExp("\\b(" + singularSubjects + ")\\s+have\\b", "gi"), "$1 has")
    .replace(new RegExp("\\b(" + singularSubjects + ")\\s+do\\b", "gi"), "$1 does")
    .replace(/\bI\s+is\b/gi, "I am")
    .replace(/\byou\s+is\b/gi, "you are")
    .replace(/\byou\s+was\b/gi, "you were")
    .replace(/\b(I|you)\s+has\b/gi, "$1 have")
    .replace(/\b(I|you)\s+does\b/gi, "$1 do")
    .replace(/\b(we|they|these|those|people|students|writers|users)\s+doesn't\b/gi, "$1 don't")
    .replace(/\b(he|she|it|this|that|someone|everyone|each|every)\s+don't\b/gi, "$1 doesn't")
    .replace(/\b([A-Za-z][A-Za-z'-]*s)\s+(is|was|has|does)\b/gi, (match, noun: string, verb: string) => {
      const normalized = noun.toLowerCase();
      if (singularSWords.has(normalized) || /(?:ss|us|is)$/.test(normalized)) return match;
      const plural = { is: "are", was: "were", has: "have", does: "do" }[verb.toLowerCase() as "is" | "was" | "has" | "does"];
      return `${noun} ${plural}`;
    })
    .replace(/\bthere\s+(is|was)\s+(?=(?:the|these|those|many|several)\s+[A-Za-z][A-Za-z'-]*s\b)/gi, (_match, verb: string) =>
      verb.toLowerCase() === "was" ? "there were " : "there are "
    )
    .replace(/\bthere\s+(are|were)\s+(?=(?:a|an|each|every|one)\s+[A-Za-z][A-Za-z'-]*\b)/gi, (_match, verb: string) =>
      verb.toLowerCase() === "were" ? "there was " : "there is "
    );

  return repaired;
}

function repairQuantifierAgreement(text: string): string {
  let repaired = text;
  const pluralQuantifier = "(?:a number of|a lot of|lots of|plenty of|a few|many|several|both|numerous)";
  const pluralNoun = "[A-Za-z][A-Za-z'-]*s";

  // The head of “a number of students” is plural, while the head of “the
  // number of students” is singular. Keep these two commonly confused
  // constructions separate instead of guessing from the final noun alone.
  repaired = repaired
    .replace(new RegExp("\\b(" + pluralQuantifier + ")\\s+(" + pluralNoun + ")\\s+is\\b", "gi"), "$1 $2 are")
    .replace(new RegExp("\\b(" + pluralQuantifier + ")\\s+(" + pluralNoun + ")\\s+was\\b", "gi"), "$1 $2 were")
    .replace(new RegExp("\\b(" + pluralQuantifier + ")\\s+(" + pluralNoun + ")\\s+has\\b", "gi"), "$1 $2 have")
    .replace(new RegExp("\\b(" + pluralQuantifier + ")\\s+(" + pluralNoun + ")\\s+does\\b", "gi"), "$1 $2 do")
    .replace(/\bthe\s+number\s+of\s+([A-Za-z][A-Za-z'-]*s)\s+(are|were|have|do)\b/gi, (_match, noun: string, verb: string) => {
      const singular = { are: "is", were: "was", have: "has", do: "does" }[verb.toLowerCase() as "are" | "were" | "have" | "do"];
      return `the number of ${noun} ${singular}`;
    })
    .replace(/\b(?:one|each|every|either|neither)\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z'-]*s\s+(are|were|have|do)\b/gi, (_match, verb: string) => {
      const singular = { are: "is", were: "was", have: "has", do: "does" }[verb.toLowerCase() as "are" | "were" | "have" | "do"];
      return _match.replace(new RegExp(`\\b${verb}\\b`, "i"), singular);
    })
    .replace(/\bboth\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z'-]*\s+(is|was|has|does)\b/gi, (_match, verb: string) => {
      const plural = { is: "are", was: "were", has: "have", does: "do" }[verb.toLowerCase() as "is" | "was" | "has" | "does"];
      return _match.replace(new RegExp(`\\b${verb}\\b`, "i"), plural);
    });

  // “There is two/several…” is a frequent model error. Limit this to explicit
  // plural determiners so ordinary “there is a lot of work” remains intact.
  repaired = repaired
    .replace(/\bthere\s+(is|was)\s+(?=(?:two|three|four|five|many|several|multiple|both|these|those)\b)/gi, (_match, verb: string) =>
      verb.toLowerCase() === "was" ? "there were " : "there are "
    )
    .replace(/\bthere's\s+(?=(?:two|three|four|five|many|several|multiple|both|these|those)\b)/gi, "there are ");

  return repaired;
}

function repairSentenceBoundaries(text: string): string {
  // Include ordinary determiner-led subjects so a repair catches output such
  // as “The project was unfinished, the reasons are unclear,” while keeping
  // the subject shape bounded enough not to split a noun phrase after a list
  // comma. The lexical verb suffixes cover common finite forms; modal and
  // auxiliary forms remain explicit because they are safer than open-ended
  // POS guessing in a final repair pass.
  const clauseSubject = "(?:I|we|you|he|she|they|it|this|that|there|people|students|users|(?:the|a|an|my|your|our|their|some|any|no|each|every|one|both|many|several)\\s+[A-Za-z][A-Za-z'-]*(?:\\s+[A-Za-z][A-Za-z'-]*){0,2})";
  const finiteVerb = "(?:is|are|was|were|has|have|had|can|could|may|might|must|should|will|would|do|does|did|[A-Za-z]+(?:s|ed)(?!['’]))";
  const independentClause = new RegExp(`^(?:${clauseSubject})\\s+[^,.;!?]*\\b${finiteVerb}\\b`, "i");
  const commaSplice = new RegExp(
    `,\\s+(?=${clauseSubject}\\s+${finiteVerb}\\b)`,
    "gi",
  );

  let repaired = text.replace(commaSplice, (_match, offset: number, fullText: string) => {
    const sentenceStart = Math.max(
      fullText.lastIndexOf(".", offset - 1),
      fullText.lastIndexOf("!", offset - 1),
      fullText.lastIndexOf("?", offset - 1),
    ) + 1;
    const leftClause = fullText.slice(sentenceStart, offset).trim();
    if (/^(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b/i.test(leftClause)) {
      return ", ";
    }
    if (/\b(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b[^,.;!?]*$/i.test(leftClause)) {
      return ", ";
    }
    if (!independentClause.test(leftClause)) {
      return ", ";
    }
    return "; ";
  });

  // Introductory subordinate clauses need a comma before a clear pronoun or
  // plural human subject. Do not include generic “the …” subjects here: that
  // would risk splitting a noun phrase in the middle.
  repaired = repaired.replace(
    /(^|(?<=[.!?]\s))(\s*(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b[^,.;!?]+?)\s+(?=(?:I|we|you|he|she|they|it|this|that|people|students|users)\s+)/gi,
    "$1$2, ",
  );
  return repaired;
}

const MODAL_BASE_FORMS: Array<[RegExp, string]> = [
  [/\b(?:explains?|explaining)\b/gi, "explain"],
  [/\b(?:helps?|helping)\b/gi, "help"],
  [/\b(?:shows?|showing)\b/gi, "show"],
  [/\b(?:makes?|making)\b/gi, "make"],
  [/\b(?:improves?|improving)\b/gi, "improve"],
  [/\b(?:affects?|affecting)\b/gi, "affect"],
  [/\b(?:uses?|using)\b/gi, "use"],
  [/\b(?:gives?|giving)\b/gi, "give"],
  [/\b(?:needs?|needing)\b/gi, "need"],
  [/\b(?:has|having)\b/gi, "have"],
  [/\bdoes\b/gi, "do"],
];

function repairModalForms(text: string): string {
  let repaired = text;
  for (const [verbPattern, base] of MODAL_BASE_FORMS) {
    repaired = repaired.replace(
      new RegExp("\\b(can|could|may|might|must|shall|should|will|would)\\s+" + verbPattern.source, "gi"),
      (_match, modal: string) => modal + " " + base,
    );
  }
  return repaired;
}

function repairPronounCase(text: string): string {
  return text
    .replace(/\bbetween\s+((?:you|he|she|they|we))\s+and\s+I\b/gi, "between $1 and me")
    .replace(/\bbetween\s+you\s+and\s+he\b/gi, "between you and him")
    .replace(/\bbetween\s+you\s+and\s+she\b/gi, "between you and her")
    .replace(/\bbetween\s+we\s+and\s+they\b/gi, "between us and them");
}

function repairCommonGrammarPatterns(text: string): string {
  return text
    .replace(/\b(could|should|would|might|must)\s+of\b/gi, "$1 have")
    .replace(/\balot\b/gi, "a lot")
    .replace(/\bmore\s+(better|worse|easier|harder|simpler)\b/gi, "$1")
    .replace(/\bmost\s+(best|worst|easiest|hardest|simplest)\b/gi, "$1");
}

function repairNoteOpenings(text: string): string {
  const sentenceStart = "(^|(?<=[.!?]\\s))";
  return text
    .replace(new RegExp(sentenceStart + "need\\s+to\\b", "gi"), "$1I need to")
    .replace(new RegExp(sentenceStart + "need\\s+help\\b", "gi"), "$1I need help")
    .replace(new RegExp(sentenceStart + "need\\s+([A-Za-z][A-Za-z'-]*)\\b", "gi"), (_match, prefix: string, noun: string) =>
      prefix + "I need " + (/^(?:an?|the|some|more|to)\b/i.test(noun) ? noun : "the " + noun)
    )
    .replace(/,\s*need\s+to\b/gi, ", I need to")
    .replace(/,\s*need\s+help\b/gi, ", I need help")
    .replace(new RegExp(sentenceStart + "send\\s+update\\b", "gi"), "$1Send an update")
    .replace(new RegExp(sentenceStart + "meeting\\s+(today|tomorrow)\\s+with\\s+", "gi"), "$1The meeting with ")
    .replace(new RegExp(sentenceStart + "deadline\\s+missed\\b", "gi"), "$1The deadline was missed")
    .replace(new RegExp(sentenceStart + "(.+?)\\s+delayed\\b", "gi"), (_match, prefix: string, subject: string) => {
      const normalized = subject.trim();
      const article = /^(?:the|a|an|my|your|our|their|this|that)\b/i.test(normalized) ? "" : "The ";
      return prefix + article + normalized.toLowerCase() + " was delayed";
    });
}

function repairSentenceStarts(text: string): string {
  return capitalizeSentenceStarts(text);
}

/**
 * Apply only high-confidence English grammar repairs after generation.
 *
 * This pass is shared by native drafts and the deterministic fallback. It
 * never edits protected spans and does not attempt open-ended rewriting.
 */
export function repairEnglishGrammar(
  candidate: string,
  protectedSpans: ProtectedSpan[] = [],
): string {
  const protectedValues = protectedValuesFor(protectedSpans);
  return withProtectedPlaceholders(candidate, protectedValues, (masked) => {
    let repaired = repairPunctuationSpacing(
      masked
        .replace(/\s+/g, " ")
        .replace(/\s+([,.;!?])/g, "$1")
    );

    repaired = repairNoteOpenings(repaired);
    repaired = repairAgreement(repaired);
    repaired = repairQuantifierAgreement(repaired);
    repaired = repairModalForms(repaired);
    repaired = repairPronounCase(repaired);
    repaired = repairCommonGrammarPatterns(repaired);
    repaired = repairSentenceBoundaries(repaired);
    repaired = repairArticles(repaired);
    repaired = repairSentenceStarts(repaired);

    return repairPunctuationSpacing(repaired.replace(/\s+([,.;!?])/g, "$1")).trim();
  });
}
