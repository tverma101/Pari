import type { RawToken } from "@/lib/nlp/tokenizer";

import { normalizeWord, trimPhrase } from "@/lib/nlp/tokenizer";

export function parseFreezeEntries(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map(trimPhrase)
    .filter(Boolean);
}

function parseFreezePhrases(raw: string): string[][] {
  return parseFreezeEntries(raw)
    .map((phrase) => {
      const words = phrase.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g);
      return words ? words.map(normalizeWord) : [];
    })
    .filter((phrase) => phrase.length > 0);
}

export function collectFrozenWordTokenIndices(rawTokens: RawToken[], freezeWords: string): Set<number> {
  const phrases = parseFreezePhrases(freezeWords).sort((left, right) => right.length - left.length);
  if (phrases.length === 0) return new Set<number>();

  const wordPositions = rawTokens
    .map((token, tokenIndex) => {
      if (token.type !== "word") return null;
      return {
        tokenIndex,
        normalized: normalizeWord(token.text),
      };
    })
    .filter((entry): entry is { tokenIndex: number; normalized: string } => entry !== null);

  const frozen = new Set<number>();

  for (const phrase of phrases) {
    if (phrase.length > wordPositions.length) continue;

    for (let start = 0; start <= wordPositions.length - phrase.length; start += 1) {
      let matches = true;

      for (let offset = 0; offset < phrase.length; offset += 1) {
        if (wordPositions[start + offset].normalized !== phrase[offset]) {
          matches = false;
          break;
        }
      }

      if (!matches) continue;

      for (let offset = 0; offset < phrase.length; offset += 1) {
        frozen.add(wordPositions[start + offset].tokenIndex);
      }
    }
  }

  return frozen;
}
