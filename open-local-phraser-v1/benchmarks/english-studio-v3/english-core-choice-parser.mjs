// Shared conservative parser for English Core forced-choice outputs.
//
// The benchmark asks models to return only an option letter. We nevertheless
// accept a few unambiguous formatting variants so output-format quirks do not
// become English-competence errors. We intentionally reject free-form prose,
// multiple answers, and strings from which a choice would need to be inferred.

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
  ];

  for (const pattern of patterns) {
    const match = s.match(pattern);
    if (match) return match[1];
  }
  return null;
}
