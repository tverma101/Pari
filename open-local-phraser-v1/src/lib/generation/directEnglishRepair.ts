import type { ProtectedSpan } from "@/lib/safety/protectedContent";
import { capitalizeSentenceStarts, repairPunctuationSpacing } from "@/lib/generation/punctuation";

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
    masked = masked.split(value).join(`\uE000${String.fromCharCode(0xE100 + index)}\uE001`);
  });

  const transformed = transform(masked);
  return transformed.replace(
    /\uE000([\s\S])\uE001/g,
    (_match, index: string) => protectedValues[index.charCodeAt(0) - 0xE100] ?? "",
  );
}

function capitalize(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

const GERUND_BASE_FORMS: Record<string, string> = {
  adding: "add",
  analyzing: "analyze",
  becoming: "become",
  beginning: "begin",
  calculating: "calculate",
  calling: "call",
  cancelling: "cancel",
  canceling: "cancel",
  coming: "come",
  comparing: "compare",
  controlling: "control",
  creating: "create",
  cutting: "cut",
  decreasing: "decrease",
  doing: "do",
  driving: "drive",
  dying: "die",
  editing: "edit",
  evaluating: "evaluate",
  generating: "generate",
  getting: "get",
  giving: "give",
  going: "go",
  having: "have",
  hitting: "hit",
  improving: "improve",
  increasing: "increase",
  indicating: "indicate",
  letting: "let",
  living: "live",
  lying: "lie",
  making: "make",
  moving: "move",
  noticing: "notice",
  operating: "operate",
  organizing: "organize",
  organising: "organise",
  passing: "pass",
  planning: "plan",
  practicing: "practice",
  preferring: "prefer",
  preparing: "prepare",
  producing: "produce",
  proving: "prove",
  putting: "put",
  recognizing: "recognize",
  recognising: "recognise",
  reducing: "reduce",
  referring: "refer",
  revising: "revise",
  running: "run",
  seeing: "see",
  setting: "set",
  sitting: "sit",
  stopping: "stop",
  swimming: "swim",
  taking: "take",
  tying: "tie",
  using: "use",
  winning: "win",
  writing: "write",
};

/**
 * Convert a gerund to an infinitive complement conservatively.
 *
 * The old implementation removed any doubled final consonant after stripping
 * `-ing`, which produced invalid bases such as `calling -> cal` and
 * `passing -> pas`; silent-e verbs such as `creating` also became `creat`.
 * Common irregular/silent-e/doubling forms are explicit above. The fallback
 * handles only spelling patterns that are safe enough for a final repair.
 */
export function infinitiveFromGerund(value: string): string {
  const normalized = value.toLowerCase();
  const known = GERUND_BASE_FORMS[normalized];
  if (known) {
    return value[0] === value[0].toUpperCase()
      ? known[0].toUpperCase() + known.slice(1)
      : known;
  }
  if (!normalized.endsWith("ing") || normalized.length <= 4) return value;

  let stem = value.slice(0, -3);
  if (/([b-df-hj-km-np-rt-vx-y])\1$/i.test(stem)) stem = stem.slice(0, -1);
  if (/v$/i.test(stem) || /c$/i.test(stem) || /(?:bl|dl|gl|pl|tl)$/i.test(stem)) {
    stem += "e";
  }
  return stem;
}

/**
 * Remove high-confidence academic padding and vague expletive openings.
 *
 * This is intentionally a small, structural pass rather than a synonym
 * dictionary. It only fires for constructions whose direct form is clear and
 * keeps protected facts and semantic markers masked while it edits.
 */
export function repairDirectEnglish(
  candidate: string,
  protectedSpans: ProtectedSpan[] = [],
): string {
  const protectedValues = protectedValuesFor(protectedSpans);

  // `extractProtectedSpans` deliberately protects expanded auxiliary negation
  // as one unit (`is not`). If masking happens first, "It is not the case ..."
  // becomes "It <placeholder> the case ..." and the structural repair cannot
  // see its grammar. Perform only the high-confidence singular-copula recast
  // first, preserving the exact `is not`/`isn't` text so the protected anchor
  // still survives unchanged. Plural/past inner copulas fail closed because
  // moving `is not` to `are not`/`was not` would mutate that protected span.
  const directBookishNegation = candidate.replace(
    /\bit\s+(is\s+not|isn['’]t)\s+the\s+case\s+that\s+(.+?)\s+is\s+([^.!?]+)([.!?]?)/gi,
    (_match, marker: string, subject: string, complement: string, punctuation: string) =>
      `${capitalize(subject.trim())} ${marker} ${complement.trim()}${punctuation}`,
  );

  const repaired = withProtectedPlaceholders(directBookishNegation, protectedValues, (masked) => {
    let repaired = masked
      .replace(/\bit\s+is\s+(?:important|worth)\s+to\s+note\s+that\s+/gi, "")
      .replace(/\bit\s+should\s+be\s+noted\s+that\s+/gi, "")
      .replace(/\bit\s+is\s+useful\s+to\s+remember\s+that\s+/gi, "")
      .replace(/\bthere\s+are\s+a\s+number\s+of\s+/gi, "several ")
      .replace(/\bthere\s+are\s+an\s+umber\s+of\s+/gi, "several ")
      .replace(/\bbecause\s+of\s+(?:the\s+)?reasons?\b/gi, "for unspecified reasons")
      .replace(/\bbecause\s+reasons?\b/gi, "for unspecified reasons")
      .replace(/\bnotwithstanding\s+the\s+fact\s+that\b/gi, "although")
      .replace(/\bdue\s+to\s+the\s+fact\s+that\b/gi, "because")
      .replace(/\bin\s+order\s+to\b/gi, "to")
      .replace(/\bin\s+the\s+event\s+that\b/gi, "if")
      .replace(/\bat\s+(?:this|the\s+present)\s+point\s+in\s+time\b/gi, "now")
      .replace(/\bfor\s+the\s+purpose\s+of\s+([A-Za-z]+ing)\b/gi, (_match, verb: string) =>
        `to ${infinitiveFromGerund(verb)}`,
      );

    // Do not rewrite “There is no indication that …” to “No evidence shows
    // that …”. `Indication` and `evidence` are not interchangeable in every
    // domain, and “shows” can strengthen an uncertainty statement. The phrase
    // is already grammatical, so a deterministic safety pass should leave it.

    repaired = repaired.replace(
      /\bthe\s+reason\s+is\s+(not\s+)?because\s+([^.!?]+)([.!?])/gi,
      (_match, marker: string | undefined, clause: string, punctuation: string) => {
        const lackingClause = clause.trim().match(/^(.+?)\s+(?:is|was)\s+lacking\s+in\s+(.+)$/i);
        if (!lackingClause) return _match;
        const subject = lackingClause[1].trim();
        const complement = lackingClause[2].trim();
        const possessive = `${subject}'s`;
        return `${capitalize(`${possessive} lack of ${complement}`)} ${marker ? "is not" : "is"} the reason${punctuation}`;
      },
    );

    repaired = repaired.replace(
      /\bthere\s+is\s+a\s+need\s+for\s+us\s+to\s+([^.!?]+)([.!?])/gi,
      (_match, action: string, punctuation: string) => {
        const directAction = action.trim().replace(/\bmake\s+improvements\b/gi, "improve");
        return `We need to ${directAction}${punctuation}`;
      },
    );

    return repairPunctuationSpacing(
      repaired
        .replace(/\s{2,}/g, " ")
        .replace(/\s+([,.;!?])/g, "$1")
    ).trim();
  });

  return capitalizeSentenceStarts(repaired);
}
