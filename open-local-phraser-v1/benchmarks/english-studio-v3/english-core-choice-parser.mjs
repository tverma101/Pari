// Shared conservative parser for English Core forced-choice outputs.
//
// The benchmark asks models to return only an option letter. We nevertheless
// accept unambiguous formatting variants so output-format quirks do not become
// English-competence errors. Explanations are accepted only after an explicit
// choice marker at the start; arbitrary prose is never searched for a letter.
//
// Every forced-choice task freezes its options in a machine-readable
// `allowedChoices` array. Both the strict and recoverable views enforce that
// set, so an impossible label on an A/B task is `invalid_option_label` rather
// than a protocol-valid wrong answer. The set is task metadata; the gold answer
// is never read here.
//
// Frozen Unicode policy: only ASCII a-z folds to A-Z. Full-width, Cyrillic,
// Kelvin, long-s, and dotless-I lookalikes are never normalized into choices.

export function parseChoiceLetter(text, allowedChoices = null) {
  const s = asciiUpper(String(text ?? "").trim());
  if (!s) return null;

  const allowed = normalizeAllowedChoices(allowedChoices);

  const resolve = (letter) => {
    if (allowed != null && !allowed.includes(letter)) return null;
    return letter;
  };

  const patterns = [
    /^([A-Z])$/,
    /^([A-Z])[.)\]:-]$/,
    /^(?:THE\s+)?ANSWER\s+IS\s+([A-Z])[.)\]:-]?$/,
    /^(?:THE\s+)?ANSWER\s*[:=-]\s*([A-Z])[.)\]:-]?$/,
    /^(?:THE\s+)?ANSWER\s+([A-Z])[.)\]:-]?$/,
    /^OPTION\s+([A-Z])[.)\]:-]?$/,
    /^(?:I\s+(?:CHOOSE|SELECT|PICK)|I['’]D\s+(?:CHOOSE|PICK)|I\s+WOULD\s+(?:CHOOSE|SELECT|PICK)|MY\s+(?:ANSWER|CHOICE|PICK)\s+IS)\s+([A-Z])[.)\]:-]?$/,
  ];

  for (const pattern of patterns) {
    const match = s.match(pattern);
    if (match) return resolve(match[1]);
  }

  const explainedLabel = s.match(/^([A-Z])[.)\]:-]\s+([\s\S]+)$/);
  const explainedPrefixes = [
    /^(?:THE\s+)?ANSWER\s+IS\s+([A-Z])[.)\]:-]?\s+([\s\S]+)$/,
    /^(?:THE\s+)?ANSWER\s*[:=-]\s*([A-Z])[.)\]:-]?\s+([\s\S]+)$/,
    /^(?:THE\s+)?ANSWER\s+([A-Z])[.)\]:-]?\s+([\s\S]+)$/,
    /^OPTION\s+([A-Z])[.)\]:-]?\s+([\s\S]+)$/,
    /^(?:I\s+(?:CHOOSE|SELECT|PICK)|I['’]D\s+(?:CHOOSE|PICK)|I\s+WOULD\s+(?:CHOOSE|SELECT|PICK)|MY\s+(?:ANSWER|CHOICE|PICK)\s+IS)\s+([A-Z])[.)\]:-]?\s+([\s\S]+)$/,
  ];
  const explainedBareChoice = s.match(/^([A-Z])\s+(?:(?:BECAUSE|SINCE)\b|IS\s+(?:THE\s+)?(?:ANSWER|CORRECT|BEST|RIGHT)\b)([\s\S]*)$/);
  const ambiguousExplanation = /^(?:OR\b|AND\b|BOTH\b|EITHER\b|[/&]|[A-Z](?:[.)](?:\s|$)|$)|[A-Z]\s+(?:OR|AND)\b)/;
  if (explainedLabel) {
    const explanation = explainedLabel[2].trimStart();
    if (!ambiguousExplanation.test(explanation)) return resolve(explainedLabel[1]);
  }
  for (const pattern of explainedPrefixes) {
    const match = s.match(pattern);
    if (match && !ambiguousExplanation.test(match[2].trimStart())) return resolve(match[1]);
  }
  if (explainedBareChoice && !ambiguousExplanation.test(explainedBareChoice[2].trimStart())) {
    return resolve(explainedBareChoice[1]);
  }
  return null;
}

export const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export function asciiUpper(text) {
  let out = "";
  for (const ch of String(text ?? "")) {
    const code = ch.codePointAt(0);
    out += code >= 0x61 && code <= 0x7a ? String.fromCharCode(code - 32) : ch;
  }
  return out;
}

/** Validate and canonicalize a frozen allowed-choice set. */
export function normalizeAllowedChoices(allowedChoices) {
  if (allowedChoices == null) return null;
  const list = typeof allowedChoices === "string" ? Array.from(allowedChoices) : allowedChoices;
  if (!Array.isArray(list) || list.length === 0) {
    throw new Error("allowedChoices must be a non-empty array of single labels");
  }
  const labels = [];
  for (const value of list) {
    if (typeof value !== "string" || value.trim().length !== 1 || !ALPHABET.includes(value.trim())) {
      throw new Error(`allowedChoices entries must be single ASCII A-Z labels, got ${JSON.stringify(value)}`);
    }
    if (!labels.includes(value.trim())) labels.push(value.trim());
  }
  return labels.sort((a, b) => ALPHABET.indexOf(a) - ALPHABET.indexOf(b));
}

/** Read the frozen allowed-choice set from a model-visible task row. */
export function allowedChoicesFromTask(task) {
  if (!task || typeof task !== "object") return null;
  for (const key of ["allowedChoices", "allowed_choices"]) {
    if (task[key] != null) return normalizeAllowedChoices(task[key]);
  }
  return null;
}

export const CHOICE_STATUS = {
  EMPTY: "empty_output",
  WHITESPACE: "whitespace_only",
  STRICT_ALLOWED: "strict_allowed_choice",
  STRICT_INVALID_LABEL: "strict_invalid_option_label",
  RECOVERABLE_ALLOWED: "recoverable_allowed_choice",
  RECOVERABLE_INVALID_LABEL: "recoverable_invalid_option_label",
  AMBIGUOUS: "ambiguous_multiple_choices",
  NO_ANCHORED_ANSWER: "no_anchored_answer",
};

/**
 * Task-aware forced-choice parse. `letter` is set only when the anchored label
 * is inside the frozen allowed set, and `invalidOptionLabel` keeps an
 * out-of-domain label so callers can report it without re-parsing.
 */
export function parseChoice(text, allowedChoices = null) {
  const allowed = normalizeAllowedChoices(allowedChoices);
  const raw = String(text ?? "");
  // Resolve the anchored label without a set first, so an out-of-domain label
  // can be reported as invalid_option_label instead of looking like no answer.
  const anchoredLabel = parseChoiceLetter(raw);
  const letter = anchoredLabel == null ? null : parseChoiceLetter(raw, allowed);
  const base = {
    letter: letter ?? null,
    anchoredLabel: anchoredLabel ?? null,
    invalidOptionLabel: null,
    allowedChoices: allowed,
    allowedSetFrozen: allowed != null,
    rawOutput: raw,
  };
  if (!raw.trim()) {
    return { ...base, status: raw === "" ? CHOICE_STATUS.EMPTY : CHOICE_STATUS.WHITESPACE };
  }
  if (anchoredLabel != null && allowed != null && !allowed.includes(anchoredLabel)) {
    const status = /^([A-Z])[.)\]:-]?$/.test(asciiUpper(raw.trim()))
      ? CHOICE_STATUS.STRICT_INVALID_LABEL
      : CHOICE_STATUS.RECOVERABLE_INVALID_LABEL;
    return { ...base, letter: null, status, invalidOptionLabel: anchoredLabel };
  }
  if (letter == null) {
    return { ...base, status: CHOICE_STATUS.NO_ANCHORED_ANSWER };
  }
  const status = /^([A-Z])[.)\]:-]?$/.test(asciiUpper(raw.trim()))
    ? CHOICE_STATUS.STRICT_ALLOWED
    : CHOICE_STATUS.RECOVERABLE_ALLOWED;
  return { ...base, status };
}
