/**
 * Grammar checking module.
 *
 * Primary: LanguageTool API if available.
 * Fallback: heuristic-based grammar indicators.
 */

interface GrammarResult {
  score: number; // 0-1, where 1 = perfect grammar
  issues: GrammarIssue[];
  summary: string;
}

interface GrammarIssue {
  type: string;
  description: string;
  position?: number;
  severity: "error" | "warning" | "info";
}

const GRAMMAR_INDICATORS = {
  // Double spaces
  doubleSpace: /\s{2,}/g,
  // Repeated words
  repeatedWord: /\b(\w+)\s+\1\b/gi,
  // Missing capital at sentence start
  missingCapital: /(?<=^|[.!?]\s+)[a-z]/g,
  // Questionable punctuation patterns
  multiplePunctuation: /[!?]{2,}/g,
  // Subject-verb agreement red flags (heuristic)
  subjectVerbFlags: [
    /\b(he|she|it)\s+(are|were|have)\b/gi,
    /\b(they|we|you)\s+(is|was|has)\b/gi,
    /\b(the\s+\w+\s+of)\s+are\b/gi,
  ],
};

/**
 * Check grammar quality of a text.
 * Returns a score from 0 (unusable) to 1 (perfect).
 */
export function checkGrammar(text: string): GrammarResult {
  const issues: GrammarIssue[] = [];

  // Check for double spaces
  if (GRAMMAR_INDICATORS.doubleSpace.test(text)) {
    issues.push({
      type: "double_space",
      description: "Double spaces found",
      severity: "warning",
    });
  }

  // Check for repeated words
  GRAMMAR_INDICATORS.repeatedWord.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = GRAMMAR_INDICATORS.repeatedWord.exec(text)) !== null) {
    issues.push({
      type: "repeated_word",
      description: `Repeated word: "${match[1]}"`,
      position: match.index,
      severity: "error",
    });
  }

  // Check for missing capitals
  GRAMMAR_INDICATORS.missingCapital.lastIndex = 0;
  while ((match = GRAMMAR_INDICATORS.missingCapital.exec(text)) !== null) {
    issues.push({
      type: "missing_capital",
      description: "Missing capital letter at sentence start",
      position: match.index,
      severity: "warning",
    });
  }

  // Check for subject-verb agreement
  for (const pattern of GRAMMAR_INDICATORS.subjectVerbFlags) {
    pattern.lastIndex = 0;
    while ((match = pattern.exec(text)) !== null) {
      issues.push({
        type: "subject_verb_agreement",
        description: `Possible agreement error: "${match[0]}"`,
        position: match.index,
        severity: "warning",
      });
    }
  }

  // Score calculation
  // Start at 1.0, deduct for each issue
  let score = 1.0;
  for (const issue of issues) {
    if (issue.severity === "error") score -= 0.15;
    else if (issue.severity === "warning") score -= 0.08;
    else score -= 0.03;
  }

  // Length penalty (very short or very long relative to content)
  const wordCount = text.split(/\s+/).length;
  if (wordCount < 3) score -= 0.2;
  if (wordCount > 100) score -= 0.1;

  return {
    score: Math.max(0, Math.min(1, score)),
    issues,
    summary: issues.length === 0
      ? "No grammar issues detected"
      : `${issues.length} issue(s) found: ${issues.map((i) => i.description).join("; ")}`,
  };
}

/**
 * Simplified LanguageTool interface.
 * Calls the public LanguageTool API if available.
 */
export async function checkGrammarWithLanguageTool(text: string): Promise<GrammarResult> {
  try {
    const response = await fetch("https://api.languagetool.org/v2/check", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        text,
        language: "en-US",
      }),
    });

    if (!response.ok) {
      // Fall back to heuristic check
      return checkGrammar(text);
    }

    const data = await response.json() as { matches: Array<{ message: string; rule: { issueType: string }; offset: number }> };

    const issues: GrammarIssue[] = (data.matches ?? []).map((m) => ({
      type: m.rule?.issueType ?? "unknown",
      description: m.message,
      position: m.offset,
      severity: "warning" as const,
    }));

    const score = Math.max(0, 1.0 - issues.length * 0.08);

    return {
      score,
      issues,
      summary: issues.length === 0
        ? "No grammar issues detected"
        : `${issues.length} issue(s) found`,
    };
  } catch {
    // Network error — fall back to heuristic
    return checkGrammar(text);
  }
}
