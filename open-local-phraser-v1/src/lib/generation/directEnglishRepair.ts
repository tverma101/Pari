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
  being: "be",
  doing: "do",
  going: "go",
  making: "make",
  using: "use",
  writing: "write",
  taking: "take",
  giving: "give",
  having: "have",
  seeing: "see",
  coming: "come",
  becoming: "become",
  moving: "move",
  living: "live",
  driving: "drive",
  improving: "improve",
  proving: "prove",
  lying: "lie",
  tying: "tie",
  dying: "die",
};

/** Convert a gerund to an infinitive complement without producing forms such as “to mak”. */
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
  if (/([b-df-hj-np-tv-z])\1$/i.test(stem)) stem = stem.slice(0, -1);
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
  const repaired = withProtectedPlaceholders(candidate, protectedValues, (masked) => {
    const negation = "(?:no|not|never|without|\\uE000[\\s\\S]\\uE001)";
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

    // “There is no indication that …” is a classic vague noun plus expletive.
    // Keep the exact negation (including its protected placeholder) while
    // giving it a real subject.
    repaired = repaired.replace(
      new RegExp(`\\bthere\\s+is\\s+(${negation})\\s+indication\\s+that\\s+`, "gi"),
      "$1 evidence shows that ",
    );

    // “It is not the case that the method is …” can be made direct without
    // weakening the negation. Restrict this to a copular clause so we do not
    // guess at a more complex proposition.
    repaired = repaired.replace(
      new RegExp(
        `\\bit\\s+is\\s+(${negation})\\s+the\\s+case\\s+that\\s+(.+?)\\s+(is|are|was|were)\\s+([^.!?]+)`,
        "gi",
      ),
      (_match, marker: string, subject: string, verb: string, complement: string) =>
        `${capitalize(subject.trim())} ${verb} ${marker} ${complement.trim()}`,
    );

    // “The reason is not because the process was lacking in effectiveness”
    // contains a vague reason frame plus a nominalized adjective. Convert the
    // clause to a direct subject without turning the negation into a claim
    // that the process itself was effective or ineffective.
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

    // Replace the expletive “there is a need for us to …” with a real subject
    // and collapse the common “make improvements” nominalization.
    repaired = repaired.replace(
      /\bthere\s+is\s+a\s+need\s+for\s+us\s+to\s+([^.!?]+)([.!?])/gi,
      (_match, action: string, punctuation: string) => {
        const directAction = action.trim().replace(/\bmake\s+improvements\b/gi, "improve");
        return `We need to ${directAction}${punctuation}`;
      },
    );

    // Collapse whitespace created when a filler opener was removed, while
    // leaving punctuation and protected placeholders untouched.
    return repairPunctuationSpacing(
      repaired
        .replace(/\s{2,}/g, " ")
        .replace(/\s+([,.;!?])/g, "$1")
    ).trim();
  });

  return capitalizeSentenceStarts(repaired);
}
