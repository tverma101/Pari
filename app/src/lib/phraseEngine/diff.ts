import type { RewriteResult, RewriteToken } from "./types";

export function assignTokenRanges(tokens: RewriteToken[]): RewriteToken[] {
  let cursor = 0;

  return tokens.map((token) => {
    const start = cursor;
    const end = cursor + token.text.length;
    cursor = end;
    return {
      ...token,
      start,
      end,
    };
  });
}

export function tokensToText(tokens: RewriteToken[]): string {
  return tokens.map((token) => token.text).join("");
}

export function summarizeTokens(tokens: RewriteToken[]): Omit<RewriteResult, "tokens"> {
  let changedCount = 0;
  let frozenCount = 0;
  let candidateCount = 0;

  for (const token of tokens) {
    if (!token.isWord) continue;
    if (token.changed) changedCount += 1;
    if (token.frozen) frozenCount += 1;
    if (!token.frozen && token.alternatives.length > 0) candidateCount += 1;
  }

  return {
    outputText: tokensToText(tokens),
    changedCount,
    frozenCount,
    candidateCount,
  };
}
