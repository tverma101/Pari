// Shared conservative parser for English Core forced-choice outputs.
//
// The benchmark asks models to return only an option letter. We nevertheless
// accept unambiguous formatting variants so output-format quirks do not become
// English-competence errors. Explanations are accepted only after an explicit
// choice marker at the start; arbitrary prose is never searched for a letter.

export function parseChoiceLetter(text) {
  const s = String(text ?? "").trim().toUpperCase();
  if (!s) return null;

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
    if (match) return match[1];
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
    if (!ambiguousExplanation.test(explanation)) return explainedLabel[1];
  }
  for (const pattern of explainedPrefixes) {
    const match = s.match(pattern);
    if (match && !ambiguousExplanation.test(match[2].trimStart())) return match[1];
  }
  if (explainedBareChoice && !ambiguousExplanation.test(explainedBareChoice[2].trimStart())) {
    return explainedBareChoice[1];
  }
  return null;
}
