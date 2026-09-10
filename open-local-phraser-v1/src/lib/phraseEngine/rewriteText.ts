import { guessPartOfSpeech } from "@/lib/nlp/posTagger";
import { countSentences, getSentenceForRange } from "@/lib/nlp/sentenceSplit";
import { countWords, normalizeWord, tokenize } from "@/lib/nlp/tokenizer";
import {
  isConservativeAutomaticCandidate,
  rankCandidatesByRule,
  pickAutomaticCandidate,
} from "@/lib/ranking/ruleBasedRanker";

import { assignTokenRanges, summarizeTokens } from "./diff";
import { collectFrozenWordTokenIndices, parseFreezeEntries } from "./freezeWords";
import {
  maximumAutomaticRewrites,
  minimumAutomaticRewrites,
  rewriteChance,
  seededFloat,
  strengthLabel,
} from "./rules";
import { buildCandidateOptions, getSynonymEntry, PHRASE_KEYS } from "./synonymBank";
import { isWarmthMode } from "@/lib/types";
import type { ManualChoiceMap, RewriteResult, RewriteSettingsInput, RewriteToken } from "./types";
import type { CandidateOption } from "@/lib/ranking/types";

interface WordPosition {
  tokenIndex: number;
  normalized: string;
}

const MANUAL_ONLY_SINGLE_WORDS = new Set([
  "and",
  "choose",
  "choosing",
  "chose",
  "chosen",
  "good",
  "may",
  "people",
  "person",
  "sentence",
  "show",
  "themselves",
  "tool",
  "used",
  "while",
  "writing",
  "when",
  "yourself",
  "oneself",
]);

function buildWordPositions(text: string): WordPosition[] {
  return tokenize(text)
    .map((token, tokenIndex) => {
      if (token.type !== "word") return null;
      return {
        tokenIndex,
        normalized: normalizeWord(token.text),
      };
    })
    .filter((entry): entry is WordPosition => entry !== null);
}

function hasWhitespaceSeparators(rawText: string): boolean {
  return /^\s+$/.test(rawText);
}

function mergeAlternatives(
  baseAlternatives: CandidateOption[],
  extraAlternatives: CandidateOption[],
  originalText: string
): CandidateOption[] {
  if (extraAlternatives.length === 0) return baseAlternatives;

  const seen = new Set(baseAlternatives.map((option) => normalizeWord(option.replacement)));
  const merged = [...baseAlternatives];

  for (const option of extraAlternatives) {
    const key = normalizeWord(option.replacement);
    if (!key || key === normalizeWord(originalText) || seen.has(key)) {
      continue;
    }

    seen.add(key);
    merged.push(option);
  }

  return merged;
}

function wordAfter(text: string, end: number): string | null {
  const match = text.slice(end).match(/^\s*([A-Za-z]+(?:[-'][A-Za-z]+)?)/);
  return match ? normalizeWord(match[1]) : null;
}

function wordsAfter(text: string, end: number, limit = 4): string[] {
  return (text.slice(end).match(/[A-Za-z]+(?:[-'][A-Za-z]+)?/g) ?? [])
    .slice(0, limit)
    .map((word) => normalizeWord(word));
}

function startsWithVowelSound(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return false;
  if (/^(?:honest|honor|honour|hour|heir|herb)\b/.test(normalized)) return true;
  if (/^(?:ewe|euro|one|once|uniform|unique|unit|united|university|use|user|usual)\b/.test(normalized)) {
    return false;
  }
  return /^[aeiou]/.test(normalized);
}

function automaticCandidateContextIssue(
  option: CandidateOption,
  sentence: string,
  sentenceStart: number,
  selectionStart: number,
  selectionEnd: number,
  isPhrase: boolean
): string | null {
  const localStart = Math.max(0, selectionStart - sentenceStart);
  const localEnd = Math.max(localStart, selectionEnd - sentenceStart);
  const before = sentence.slice(0, localStart);
  const after = sentence.slice(localEnd);
  const previous = before.match(/\b([A-Za-z]+(?:[-'][A-Za-z]+)?)\s*$/)?.[1]?.toLowerCase() ?? null;
  const following = wordsAfter(after, 0, 6);
  const next = following[0] ?? null;
  const afterNext = following[1] ?? null;
  const original = normalizeWord(option.original);
  const replacement = option.replacement.trim().toLowerCase();
  const properNounAfter = after.match(/^\s*([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*)/)?.[1] ?? null;

  const firstReplacementWord = replacement.match(/^[a-z]+(?:[-'][a-z]+)*/)?.[0] ?? "";
  const article = before.match(/\b(a|an)\s*$/i)?.[1]?.toLowerCase();
  if (article && article === "a" && startsWithVowelSound(firstReplacementWord)) {
    return "The candidate changes the article from “a” to an incompatible vowel sound.";
  }
  if (article && article === "an" && !startsWithVowelSound(firstReplacementWord)) {
    return "The candidate changes the article from “an” to an incompatible consonant sound.";
  }

  // Automatic rewriting is sentence-aware only through this small local
  // window, so protect the most common frames where a dictionary synonym is
  // grammatical in isolation but wrong for the sentence around it.
  if (
    original === "however" &&
    !before.trim() &&
    /^(?:yet|though)\b/.test(replacement)
  ) {
    return "Keep a full contrast connector at the start of the sentence.";
  }

  if (
    original === "because" &&
    /^(?:seeing that|considering that)\b/.test(replacement)
  ) {
    return "Keep “because” or use a direct causal connector.";
  }

  if (
    original === "simple" &&
    /^(?:tools?|devices?|software|methods?|processes?|approaches?)$/.test(next ?? "") &&
    /^(?:easy|uncomplicated)\b/.test(replacement)
  ) {
    return "Use “basic” or keep “simple” for a tool or process description.";
  }

  if (
    original === "team" &&
    /^(?:crew|unit|staff)\b/.test(replacement) &&
    /\b(?:writing|drafts?|ideas?|students?|teachers?|editor|review)\b/i.test(sentence)
  ) {
    return "Keep “team” or use “group” in an academic or writing context.";
  }

  if (
    /^(?:teacher|teachers)$/.test(original) &&
    /^(?:tutor|tutors)\b/.test(replacement) &&
    /\b(?:gave|asked|told|reminded|provide|provided|review|reviewed)\b/i.test(sentence)
  ) {
    return "Keep the classroom role “teacher” in this sentence.";
  }

  if (
    /^(?:tool|tools)$/.test(original) &&
    /^devices?\b/.test(replacement) &&
    /\b(?:writing|drafts?|paragraphs?|text|software|app(?:lication)?s?|digital|local|online)\b/i.test(sentence)
  ) {
    return "Keep “tool” for software and writing-tool contexts.";
  }

  if (
    original === "understand" &&
    /^(?:myself|yourself|himself|herself|ourselves|themselves|itself)$/.test(next ?? "") &&
    replacement !== "understand"
  ) {
    return "Keep “understand” in a reflexive self-understanding frame.";
  }

  if (
    original === "take" &&
    next === "a" &&
    afterNext === "break" &&
    /^(?:receive|accept|obtain|grab|seize|carry|choose)\b/.test(replacement)
  ) {
    return "Keep the natural phrase “take a break.”";
  }

  if (
    original === "review" &&
    following.some((word) => /^(?:ideas?|work|drafts?)$/.test(word)) &&
    /^(?:characterize|depict|portray|illustrate)\b/.test(replacement)
  ) {
    return "Use “review” or “examine” for ideas, work, or a draft.";
  }

  if (
    original === "asked the class to" &&
    /^invited the class to\b/.test(replacement)
  ) {
    return "Keep “asked the class to” when the source gives an instruction.";
  }

  if (
    original === "take time to understand" &&
    /^(?:spend time learning|need time to grasp)\b/.test(replacement) &&
    /(?:^|\s)(?:may|might|could|can)\s*$/i.test(before)
  ) {
    return "Keep the “may take time to understand” frame.";
  }

  if (
    original === "feedback" &&
    /^advice\b/.test(replacement) &&
    /\b(?:fast|faster|rapid|timely|writing|draft|tool|suggestions?)\b/i.test(sentence)
  ) {
    return "Keep “feedback” when the source describes responses to writing or work.";
  }

  if (
    original === "communication" &&
    /^(?:dialogue|interaction|exchange|conversation)\b/.test(replacement) &&
    /\b(?:improve|improves|improved|strengthen|strengthens|strengthened|effective|better|clear)\s+communication\b/i.test(sentence)
  ) {
    return "Keep broad “communication” wording in this improvement frame.";
  }

  if (
    original === "clear" &&
    next === "suggestions" &&
    /^(?:direct|plain|readable)\b/.test(replacement)
  ) {
    return "Keep “clear suggestions” as the natural phrase.";
  }

  const unsafePairs: Record<string, string[]> = {
    communication: ["connection", "interaction"],
    communications: ["connections", "interactions"],
    argument: ["case", "point", "claim"],
    arguments: ["cases", "points", "claims"],
    teacher: ["guide"],
    teachers: ["guides"],
    student: ["pupil"],
    students: ["pupils"],
    paragraph: ["section"],
    paragraphs: ["sections"],
    original: ["first"],
  };
  if (unsafePairs[original]?.includes(replacement)) {
    return "The candidate is too context-dependent for an automatic Personal rewrite.";
  }

  // Some replacements are grammatical in isolation but become noticeably
  // robotic when they are placed next to a concrete phrase. Keep the
  // automatic paragraph path conservative while leaving these choices
  // available in the inline chooser.
  if (
    original === "strong" &&
    next === "eye" &&
    afterNext === "contact" &&
    replacement !== "strong"
  ) {
    return "Keep the established collocation “strong eye contact.”";
  }

  if (
    original === "effective" &&
    next === "communication" &&
    /^(?:potent|powerful|robust)$/.test(replacement)
  ) {
    return "Keep the natural collocation “effective communication.”";
  }

  if (
    original === "clear" &&
    next === "responsibilities" &&
    replacement !== "clear"
  ) {
    return "“Clear responsibilities” is more natural in this sentence frame.";
  }

  if (
    original === "clear" &&
    next === "expectations" &&
    replacement !== "clear"
  ) {
    return "Keep the familiar collocation “clear expectations.”";
  }

  if (
    original === "clear" &&
    replacement !== "clear" &&
    /\bmake(?:s)?\b[^.!?]*$/i.test(before)
  ) {
    return "Keep “clear” in the phrase “make the next step clear.”";
  }

  if (
    original === "relationships" &&
    next === "and" &&
    afterNext === "groups" &&
    replacement !== "relationships"
  ) {
    return "Keep “relationships and groups” together as a coherent topic.";
  }

  if (
    /\barguments?\b/i.test(original) &&
    /^(?:case|point|claim)$/.test(replacement)
  ) {
    return "“Case” is too context-dependent as an automatic replacement for “argument.”";
  }

  if (
    original === "used" &&
    properNounAfter &&
    /^(?:drew on|turned to|relied on)$/.test(replacement)
  ) {
    return "Keep “used” before a named product, service, or tool.";
  }

  if (
    original === "used" &&
    /^(?:drew on|turned to|relied on|employed|utilized)$/.test(replacement) &&
    /^(?:test|method|approach|system|tool|procedure|technique|measure|strategy)$/.test(previous ?? "") &&
    (!next || /^(?:to|for|in|by|when|that)$/.test(next))
  ) {
    return "Keep “used” when it modifies a test, method, tool, or approach.";
  }

  if (
    original === "help" &&
    /^(?:guide|assist|aid|support|facilitate)$/.test(replacement) &&
    /^(?:show|understand|find|make|read|explain|see|determine|identify|improve|review|recognize|interpret|remember|learn|compare)$/.test(next ?? "")
  ) {
    return "Keep the complement in the familiar “help show” or “help understand” frame.";
  }

  if (
    original === "explain" &&
    /^(?:describe|detail|outline|illustrate)$/.test(replacement) &&
    next === "that"
  ) {
    return "Keep a verb that naturally introduces a following “that” clause.";
  }

  if (
    original === "better" &&
    next === "at" &&
    replacement !== "better"
  ) {
    return "Keep the established comparative frame “better at.”";
  }

  if (
    original === "good" &&
    next === "at" &&
    replacement !== "good"
  ) {
    return "Keep the established ability frame “good at.”";
  }

  if (
    original === "good" &&
    following.some((word) => /^(?:witnesses?|memory|ability|evidence)$/.test(word)) &&
    /^(?:positive|constructive|helpful|powerful)$/.test(replacement)
  ) {
    return "Keep “good” in this quality description instead of changing its meaning or tone.";
  }

  if (
    original === "strong" &&
    (next === "or" || following.includes("weak")) &&
    following.includes("recognizing") &&
    replacement !== "strong"
  ) {
    return "Keep “strong” in the contrast with “weak at recognizing faces.”";
  }

  if (
    original === "simple" &&
    next === "effect" &&
    /^(?:easy|basic|uncomplicated)$/.test(replacement)
  ) {
    return "Keep “simple effect” in this technical sentence frame.";
  }

  if (
    original === "perspectives" &&
    /^(?:different|varied|contrasting|clear)$/.test(previous ?? "") &&
    replacement !== "perspectives"
  ) {
    return "Keep “perspectives” in this established comparison phrase.";
  }

  if (
    original === "teacher" &&
    /^(?:gave|asked|told|reminded)$/.test(next ?? "") &&
    /^(?:tutor|mentor|guide)$/.test(replacement)
  ) {
    return "Keep the role “teacher” in this classroom action frame.";
  }

  if (
    original === "communication" &&
    next === "between" &&
    /^(?:connection|interaction|dialogue|conversation|exchange)$/.test(replacement)
  ) {
    return "Keep broad “communication” wording between groups or departments.";
  }

  if (
    original === "original" &&
    next === "wording" &&
    /^(?:source|first)$/.test(replacement)
  ) {
    return "Keep the established phrase “original wording.”";
  }

  if (isPhrase) return null;

  if (
    /^(?:ask|asked|asks)$/.test(original) &&
    /^(?:sought|requested|inquired|questioned)$/.test(replacement) &&
    (next === "for" || (next && /^(?:me|us|you|him|her|them)$/.test(next) && afterNext === "to"))
  ) {
    return "This candidate does not preserve the source verb's object pattern.";
  }

  if (
    original === "asked" &&
    replacement === "sought" &&
    /^(?:was|were|is|are|be|been|being)$/.test(previous ?? "") &&
    next === "to"
  ) {
    return "This candidate cannot replace a passive “asked to” frame.";
  }

  if (
    original === "asked" &&
    (/(?:was|were|is|are|be|been|being)\s*$/i.test(before) || next === "questions")
  ) {
    return "Keep the common “asked” frame in passive and question contexts.";
  }

  if (
    original === "need" &&
    /^(?:require|seek|necessitate|demand)$/.test(replacement) &&
    next === "to"
  ) {
    return "This candidate does not preserve the “need to” frame.";
  }

  if (
    original === "take" &&
    /^(?:receive|accept|obtain|grab|seize|carry|choose)$/.test(replacement) &&
    following.includes("into") &&
    following.includes("account")
  ) {
    return "This candidate does not preserve the “take into account” frame.";
  }

  if (
    original === "help" &&
    /^(?:guide|guides|assist|assists|aid|aids|support|supports)$/.test(replacement) &&
    (/^(?:my|your|his|her|our|their)$/.test(previous ?? "") || next === "with" ||
      (previous === "for" && /^(?:guide|guides|assist|assists|aid|aids)$/.test(replacement)))
  ) {
    return "This candidate does not preserve the noun or “help with” frame.";
  }

  if (
    /^(?:guide|guides|guided|guiding)$/.test(replacement) &&
    next === "with"
  ) {
    return "“Guide” does not preserve the source “help with” construction.";
  }

  if (next === "for" && /^(?:sought|requested|inquired|questioned)$/.test(replacement)) {
    return "This candidate creates an invalid verb-preposition pair.";
  }

  if (
    next === "that" &&
    /^(?:follow|look at|read|review|examine|consider)$/.test(replacement)
  ) {
    return "This candidate does not fit the following “that” clause.";
  }

  return null;
}

function canAutoRewriteSingleWord(originalText: string, fullText: string, selectionEnd: number): boolean {
  const normalized = normalizeWord(originalText);
  if (MANUAL_ONLY_SINGLE_WORDS.has(normalized)) return false;
  if (normalized === "better" && wordAfter(fullText, selectionEnd) === "than") return false;
  return true;
}

function forcedModeCandidate(
  ranked: RankedCandidate[],
  mode: RewriteSettingsInput["mode"],
  strength: number
): CandidateOption | null {
  if (strength < 35 || mode === "personal" || mode === "standard") return null;
  const explicit = ranked.find((candidate) =>
    candidate.option.modePreference?.includes(mode) ||
    (isWarmthMode(mode) && candidate.option.modePreference?.includes("warm"))
  )?.option;
  if (explicit) return explicit;
  if (mode === "simple" || mode === "shorten" || mode === "expand") return ranked[0]?.option ?? null;
  return null;
}

function modeRankedCandidates(
  ranked: RankedCandidate[],
  mode: RewriteSettingsInput["mode"]
): RankedCandidate[] {
  if (mode === "personal" || mode === "standard") return ranked;

  const explicit = ranked.filter((candidate) =>
    candidate.option.modePreference?.includes(mode) ||
    (isWarmthMode(mode) && candidate.option.modePreference?.includes("warm"))
  );
  if (explicit.length > 0) return explicit;

  if (mode === "simple" || mode === "shorten") {
    const shorter = ranked.filter(
      (candidate) => candidate.option.replacement.length < candidate.option.original.length
    );
    return shorter;
  }

  if (mode === "expand") {
    const longer = ranked.filter(
      (candidate) => candidate.option.replacement.length > candidate.option.original.length
    );
    return longer;
  }

  return ranked;
}

function findPhraseMatches(
  text: string,
  frozenTokenIndices: Set<number>
): Map<number, { key: string; length: number }> {
  const rawTokens = tokenize(text);
  const wordPositions = buildWordPositions(text);
  const matches = new Map<number, { key: string; length: number }>();

  for (let index = 0; index < wordPositions.length; index += 1) {
    for (const key of PHRASE_KEYS) {
      const words = key.split(/\s+/);
      if (index + words.length > wordPositions.length) continue;

      let valid = true;
      for (let offset = 0; offset < words.length; offset += 1) {
        const wordPosition = wordPositions[index + offset];
        if (wordPosition.normalized !== words[offset]) {
          valid = false;
          break;
        }

        if (frozenTokenIndices.has(wordPosition.tokenIndex)) {
          valid = false;
          break;
        }

        if (offset > 0) {
          const previousTokenIndex = wordPositions[index + offset - 1].tokenIndex;
          const between = rawTokens
            .slice(previousTokenIndex + 1, wordPosition.tokenIndex)
            .map((token) => token.text)
            .join("");

          if (!hasWhitespaceSeparators(between)) {
            valid = false;
            break;
          }
        }
      }

      if (!valid) continue;

      matches.set(index, { key, length: words.length });
      index += words.length - 1;
      break;
    }
  }

  return matches;
}

type RankedCandidate = ReturnType<typeof rankCandidatesByRule>[number];

function previousOutputWord(tokens: RewriteToken[]): string | null {
  for (let index = tokens.length - 1; index >= 0; index -= 1) {
    const token = tokens[index];
    if (token.isWord) {
      const match = token.text.match(/([A-Za-z]+(?:[-'][A-Za-z]+)?)\s*$/);
      return match ? normalizeWord(match[1]) : null;
    }

    if (/[.!?;:,]/.test(token.text)) return null;
  }

  return null;
}

function recentOutputWords(tokens: RewriteToken[], limit = 4): string[] {
  const words: string[] = [];
  for (let index = tokens.length - 1; index >= 0 && words.length < limit; index -= 1) {
    const token = tokens[index];
    if (token.isWord) {
      const tokenWords = token.text.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g) ?? [];
      for (let wordIndex = tokenWords.length - 1; wordIndex >= 0 && words.length < limit; wordIndex -= 1) {
        words.push(normalizeWord(tokenWords[wordIndex]));
      }
      continue;
    }

    if (/[.!?;:,]/.test(token.text)) break;
  }
  return words;
}

function outputCollocationPenalty(
  option: CandidateOption,
  tokens: RewriteToken[],
  automaticReplacementCounts: Map<string, number>
): number {
  const previous = previousOutputWord(tokens);
  const recent = recentOutputWords(tokens);
  const replacement = normalizeWord(option.replacement);
  const priorUses = automaticReplacementCounts.get(replacement) ?? 0;
  let penalty = priorUses > 0 ? Math.min(0.28, 0.14 * priorUses) : 0;

  if (!previous) return penalty;

  if (
    recent.some((word) => /^(?:applied|employed|utilized)$/.test(word)) &&
    /^(?:basic|simple|straightforward|local|online|digital\s+)?applications?$/.test(replacement)
  ) {
    return penalty + 0.9;
  }

  if (previous === "team" && /^teamed(?:\s+up)?\s+with\b/.test(replacement)) return penalty + 0.9;
  if (previous === "aid" && /^aids?\b/.test(replacement)) return penalty + 0.9;
  if (previous === "the" && /^the\b/.test(replacement)) return penalty + 0.6;
  return penalty;
}

function rerankAgainstOutputContext(
  ranked: RankedCandidate[],
  tokens: RewriteToken[],
  automaticReplacementCounts: Map<string, number>
): RankedCandidate[] {
  return ranked
    .map((candidate) => ({
      ...candidate,
      score: candidate.score - outputCollocationPenalty(candidate.option, tokens, automaticReplacementCounts),
    }))
    .sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      if (left.risk !== right.risk) {
        const order: Record<"low" | "medium" | "high", number> = { low: 0, medium: 1, high: 2 };
        return order[left.risk] - order[right.risk];
      }
      return left.option.replacement.localeCompare(right.option.replacement);
    });
}

function automaticCandidates(
  ranked: RankedCandidate[],
  settings: RewriteSettingsInput,
  sentence: string,
  sentenceStart: number,
  selectionStart: number,
  selectionEnd: number,
  isPhrase: boolean
): RankedCandidate[] {
  if (settings.automaticRewriteStrategy !== "conservative") return ranked;
  const localStart = Math.max(0, selectionStart - sentenceStart);
  const localEnd = Math.max(localStart, selectionEnd - sentenceStart);
  const before = sentence.slice(0, localStart);
  const after = sentence.slice(localEnd);
  const previous = before.match(/\b([A-Za-z]+(?:[-'][A-Za-z]+)?)\s*$/)?.[1]?.toLowerCase() ?? null;
  const nextWords = after.match(/^\s*([A-Za-z]+(?:[-'][A-Za-z]+)?)(?:\s+([A-Za-z]+(?:[-'][A-Za-z]+)?))?/i);
  const next = nextWords?.[1]?.toLowerCase() ?? null;
  const afterNext = nextWords?.[2]?.toLowerCase() ?? null;

  return ranked.filter((candidate) => {
    if (!isConservativeAutomaticCandidate(candidate.option, settings.mode)) return false;
    const replacement = candidate.option.replacement.trim().toLowerCase();

    if (
      automaticCandidateContextIssue(
        candidate.option,
        sentence,
        sentenceStart,
        selectionStart,
        selectionEnd,
        isPhrase
      )
    ) {
      return false;
    }

    // Adding an article to an existing single-word slot is a common source of
    // outputs such as "stress at the task". Phrase-level rewrites can make
    // their own article decision, so leave those eligible.
    if (!isPhrase && /^(?:a|an|the)\b/.test(replacement)) return false;

    if (next === "times" && replacement === "some") return false;
    // Verbs such as "seek" and "request" take a direct object here; keeping
    // the source preposition would create errors such as "sought for time".
    if (next === "for" && /^(?:sought|requested|inquired)\b/.test(replacement)) return false;
    if (next === "that" && /^(?:follow|look at|read|review|examine|consider)\b/.test(replacement)) return false;
    if (replacement === "questioned" && next === "questions") return false;
    if (replacement === "direct" && next === "expectations") return false;
    if (
      /^(?:drew on|turned to)\b/.test(replacement) &&
      /^(?:different|varied|contrasting|clear|strong|good)\b/.test(next ?? "")
    ) {
      return false;
    }
    if (
      replacement === "worked with" &&
      /^(?:different|varied|contrasting)\b/.test(next ?? "") &&
      /^(?:tones?|details?|styles?|approaches?)\b/.test(afterNext ?? "")
    ) {
      return false;
    }
    if (previous === "body" && /^(?:speech|tongue)\b/.test(replacement)) return false;
    if (
      replacement === "readable" &&
      !/^(?:text|writing|sentences?|paragraphs?|passages?|drafts?|prose|copy|content)\b/.test(next ?? "")
    ) {
      return false;
    }
    if (
      /^(?:invited|requested|inquired|encouraged)\b/.test(replacement) &&
      /^(?:clean|organize|review|revise|read|write|help|make|find|understand|learn|listen|practice|improve|communicate|stay|work|contribute|explain|respond)\b/.test(next ?? "") &&
      /^(?:to|that|the|a|an|me|us|you|him|her|them)\b/.test(afterNext ?? "") === false
    ) {
      return false;
    }
    if (
      replacement === "make clear" &&
      !/^(?:that|how|why|what|it|this|these)\b/i.test(next ?? "")
    ) {
      return false;
    }

    // Verbs such as guide and assist need a complement after a pronoun;
    // "guide me communicate" is not a safe replacement for "help me
    // communicate" without a sentence-level generator to repair it.
    if (
      /^(?:me|us|you|him|her|them)\b/.test(next ?? "") &&
      /^(?:guide|assist|aid|support)\b/.test(replacement) &&
      !/^(?:to|as|that)\b/i.test(after.replace(/^\s*[A-Za-z]+(?:[-'][A-Za-z]+)?\s*/i, ""))
    ) {
      return false;
    }

    // Adjectives do not normally fit before a phrasal particle ("sluggish
    // down", "gradual up"). Keep the automatic path to adverbial forms.
    if (
      /^(?:down|up|off|on|away|back|forward)$/.test(next ?? "") &&
      !/(?:ly|right|back|away|forward|straight)$/.test(replacement)
    ) {
      return false;
    }

    return true;
  });
}

function automaticBudgetReached(
  settings: RewriteSettingsInput,
  sentenceStart: number,
  sentenceRewriteCounts: Map<number, number>
): boolean {
  if (settings.automaticRewriteStrategy !== "conservative") return false;
  const budget = settings.automaticRewriteBudget ?? maximumAutomaticRewrites(settings.strength);
  return (sentenceRewriteCounts.get(sentenceStart) ?? 0) >= Math.max(0, budget);
}

function automaticMinimumStillNeeded(
  settings: RewriteSettingsInput,
  sentenceStart: number,
  sentenceRewriteCounts: Map<number, number>
): boolean {
  if (settings.automaticRewriteStrategy !== "conservative") return false;
  const minimum = minimumAutomaticRewrites(settings.strength);
  return (sentenceRewriteCounts.get(sentenceStart) ?? 0) < minimum;
}

function recordAutomaticRewrite(
  settings: RewriteSettingsInput,
  sentenceStart: number,
  sentenceRewriteCounts: Map<number, number>
): void {
  if (settings.automaticRewriteStrategy !== "conservative") return;
  sentenceRewriteCounts.set(sentenceStart, (sentenceRewriteCounts.get(sentenceStart) ?? 0) + 1);
}

function recordAutomaticReplacement(
  option: CandidateOption | null,
  automaticReplacementCounts: Map<string, number>
): void {
  if (!option) return;
  const replacement = normalizeWord(option.replacement);
  if (!replacement || replacement === normalizeWord(option.original)) return;
  automaticReplacementCounts.set(replacement, (automaticReplacementCounts.get(replacement) ?? 0) + 1);
}

export function rewriteText(
  text: string,
  settings: RewriteSettingsInput,
  manualChoices: ManualChoiceMap = {},
  extraAlternatives: Record<string, CandidateOption[]> = {}
): RewriteResult {
  const rawTokens = tokenize(text);
  const wordPositions = rawTokens
    .map((token, tokenIndex) => {
      if (token.type !== "word") return null;
      return {
        tokenIndex,
        normalized: normalizeWord(token.text),
      };
    })
    .filter((entry): entry is WordPosition => entry !== null);

  const frozenTokenIndices = collectFrozenWordTokenIndices(rawTokens, settings.freezeWords);
  const phraseMatches = findPhraseMatches(text, frozenTokenIndices);
  const tokens: RewriteToken[] = [];
  const sentenceRewriteCounts = new Map<number, number>();
  const automaticReplacementCounts = new Map<string, number>();
  const seedBase = `${settings.mode}|${settings.strength}|${settings.freezeWords}|${text}`;

  let rawIndex = 0;
  let wordIndex = 0;

  while (rawIndex < rawTokens.length) {
    const rawToken = rawTokens[rawIndex];

    if (rawToken.type === "gap") {
      tokens.push({
        id: `gap-${rawIndex}`,
        text: rawToken.text,
        originalText: rawToken.text,
        isWord: false,
        isPhrase: false,
        alternatives: [],
        selectedAlternativeId: null,
        changed: false,
        frozen: false,
        start: 0,
        end: 0,
        partOfSpeech: "unknown",
        source: "text",
        risk: "low",
        warnings: [],
        originalStart: rawToken.start,
        originalEnd: rawToken.end,
      });
      rawIndex += 1;
      continue;
    }

    const wordPositionIndex = wordPositions.findIndex((entry) => entry.tokenIndex === rawIndex);
    const phraseMatch = phraseMatches.get(wordPositionIndex);

    if (phraseMatch) {
      const lastWordPosition = wordPositions[wordPositionIndex + phraseMatch.length - 1];
      const endRawIndex = lastWordPosition.tokenIndex;
      const originalText = rawTokens.slice(rawIndex, endRawIndex + 1).map((token) => token.text).join("");
      const entry = getSynonymEntry(phraseMatch.key);
      const tokenId = `segment-${wordIndex}`;
      const alternatives = mergeAlternatives(
        entry ? buildCandidateOptions(originalText, entry) : [],
        extraAlternatives[tokenId] ?? [],
        originalText
      );
      const hasManualSelection = Object.prototype.hasOwnProperty.call(manualChoices, tokenId);
      const manualSelection = hasManualSelection ? manualChoices[tokenId] : undefined;
      const frozen = false;

      const selectedAlternativeId =
        manualSelection && alternatives.some((option) => option.id === manualSelection)
          ? manualSelection
          : null;
      const sentence = getSentenceForRange(text, rawTokens[rawIndex].start, rawTokens[endRawIndex].end);

      const ranked = rerankAgainstOutputContext(rankCandidatesByRule(alternatives, {
        fullText: text,
        sentence: sentence.text,
        selectedText: originalText,
        mode: settings.mode,
        strength: settings.strength <= 24 ? 1 : settings.strength <= 49 ? 2 : settings.strength <= 74 ? 3 : 4,
        freezeWords: parseFreezeEntries(settings.freezeWords),
        partOfSpeech: entry?.pos ?? "phrase",
        selectionStart: rawTokens[rawIndex].start,
        selectionEnd: rawTokens[endRawIndex].end,
        sentenceStart: sentence.start,
      }), tokens, automaticReplacementCounts);

      const sentenceForAuto = sentence;
      const modeRanked = modeRankedCandidates(
        automaticCandidates(
          ranked,
          settings,
          sentence.text,
          sentence.start,
          rawTokens[rawIndex].start,
          rawTokens[endRawIndex].end,
          true
        ),
        settings.mode
      );
      const autoPick =
        !hasManualSelection &&
        !settings.disableAutomaticRewrites &&
        selectedAlternativeId === null &&
        !automaticBudgetReached(settings, sentenceForAuto.start, sentenceRewriteCounts) &&
        modeRanked.length > 0 &&
        (automaticMinimumStillNeeded(settings, sentenceForAuto.start, sentenceRewriteCounts) ||
          forcedModeCandidate(modeRanked, settings.mode, settings.strength) !== null ||
          seededFloat(`${seedBase}|${tokenId}|${originalText}`) <
            rewriteChance(settings.mode, settings.strength, originalText))
          ? forcedModeCandidate(modeRanked, settings.mode, settings.strength) ??
            pickAutomaticCandidate(modeRanked, settings.mode, `${seedBase}|${tokenId}`)
          : null;

      if (autoPick) recordAutomaticRewrite(settings, sentenceForAuto.start, sentenceRewriteCounts);
      recordAutomaticReplacement(autoPick, automaticReplacementCounts);

      const selectedAlternative = alternatives.find((option) => option.id === selectedAlternativeId) ?? null;
      const selectedAlternativeAllowed =
        selectedAlternative &&
        (settings.automaticRewriteStrategy !== "conservative" ||
          !automaticCandidateContextIssue(
            selectedAlternative,
            sentence.text,
            sentence.start,
            rawTokens[rawIndex].start,
            rawTokens[endRawIndex].end,
            true
          ))
          ? selectedAlternative
          : null;
      const resolvedOption = selectedAlternativeAllowed ?? autoPick ?? null;

      tokens.push({
        id: tokenId,
        text: resolvedOption?.replacement ?? originalText,
        originalText,
        isWord: true,
        isPhrase: true,
        alternatives,
        selectedAlternativeId: resolvedOption?.id ?? null,
        changed: Boolean(resolvedOption),
        frozen,
        start: 0,
        end: 0,
        partOfSpeech: entry?.pos ?? "phrase",
        source: resolvedOption?.source ?? entry?.source ?? "phrase-bank",
        label: resolvedOption?.label,
        risk: resolvedOption?.risk ?? "low",
        warnings: ranked.find((candidate) => candidate.option.id === resolvedOption?.id)?.warnings ?? [],
        originalStart: rawTokens[rawIndex].start,
        originalEnd: rawTokens[endRawIndex].end,
      });

      rawIndex = endRawIndex + 1;
      wordIndex += 1;
      continue;
    }

    const originalText = rawToken.text;
    const tokenId = `segment-${wordIndex}`;
    const frozen = frozenTokenIndices.has(rawIndex);
    const entry = frozen ? undefined : getSynonymEntry(originalText);
    const alternatives = mergeAlternatives(
      frozen || !entry ? [] : buildCandidateOptions(originalText, entry),
      extraAlternatives[tokenId] ?? [],
      originalText
    );
    const hasManualSelection = Object.prototype.hasOwnProperty.call(manualChoices, tokenId);
    const manualSelection = hasManualSelection ? manualChoices[tokenId] : undefined;

    const selectedAlternativeId =
      manualSelection && alternatives.some((option) => option.id === manualSelection)
        ? manualSelection
        : null;
    const sentence = getSentenceForRange(text, rawToken.start, rawToken.end);

    const ranked = rerankAgainstOutputContext(rankCandidatesByRule(alternatives, {
      fullText: text,
      sentence: sentence.text,
      selectedText: originalText,
      mode: settings.mode,
      strength: settings.strength <= 24 ? 1 : settings.strength <= 49 ? 2 : settings.strength <= 74 ? 3 : 4,
      freezeWords: parseFreezeEntries(settings.freezeWords),
      partOfSpeech: entry?.pos ?? guessPartOfSpeech(originalText),
      selectionStart: rawToken.start,
      selectionEnd: rawToken.end,
      sentenceStart: sentence.start,
    }), tokens, automaticReplacementCounts);

    const modeRanked = modeRankedCandidates(
      automaticCandidates(
        ranked,
        settings,
        sentence.text,
        sentence.start,
        rawToken.start,
        rawToken.end,
        false
      ),
      settings.mode
    );
    const autoPick =
      !frozen &&
      !hasManualSelection &&
      !settings.disableAutomaticRewrites &&
      canAutoRewriteSingleWord(originalText, text, rawToken.end) &&
      selectedAlternativeId === null &&
      !automaticBudgetReached(settings, sentence.start, sentenceRewriteCounts) &&
      modeRanked.length > 0 &&
      (automaticMinimumStillNeeded(settings, sentence.start, sentenceRewriteCounts) ||
        forcedModeCandidate(modeRanked, settings.mode, settings.strength) !== null ||
        seededFloat(`${seedBase}|${tokenId}|${originalText}`) <
          rewriteChance(settings.mode, settings.strength, originalText))
        ? forcedModeCandidate(modeRanked, settings.mode, settings.strength) ??
          pickAutomaticCandidate(modeRanked, settings.mode, `${seedBase}|${tokenId}`)
        : null;

    if (autoPick) recordAutomaticRewrite(settings, sentence.start, sentenceRewriteCounts);
    recordAutomaticReplacement(autoPick, automaticReplacementCounts);

    const selectedAlternative = alternatives.find((option) => option.id === selectedAlternativeId) ?? null;
    const selectedAlternativeAllowed =
      selectedAlternative &&
      (settings.automaticRewriteStrategy !== "conservative" ||
        !automaticCandidateContextIssue(
          selectedAlternative,
          sentence.text,
          sentence.start,
          rawToken.start,
          rawToken.end,
          false
        ))
        ? selectedAlternative
        : null;
    const resolvedOption = selectedAlternativeAllowed ?? autoPick ?? null;

    tokens.push({
      id: tokenId,
      text: resolvedOption?.replacement ?? originalText,
      originalText,
      isWord: true,
      isPhrase: false,
      alternatives,
      selectedAlternativeId: resolvedOption?.id ?? null,
      changed: Boolean(resolvedOption),
      frozen,
      start: 0,
      end: 0,
      partOfSpeech: entry?.pos ?? guessPartOfSpeech(originalText),
      source: resolvedOption?.source ?? entry?.source ?? "text",
      label: resolvedOption?.label,
      risk: resolvedOption?.risk ?? "low",
      warnings: frozen
        ? ["Frozen term"]
        : ranked.find((candidate) => candidate.option.id === resolvedOption?.id)?.warnings ?? [],
      originalStart: rawToken.start,
      originalEnd: rawToken.end,
    });

    rawIndex += 1;
    wordIndex += 1;
  }

  const rangedTokens = assignTokenRanges(tokens);
  const summary = summarizeTokens(rangedTokens);

  return {
    tokens: rangedTokens,
    ...summary,
  };
}

export { countWords, countSentences, parseFreezeEntries, strengthLabel };
