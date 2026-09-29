/**
 * Lightweight production NLI / role-preservation judge (Issue #7).
 *
 * The learned DeBERTa judge remains the general semantic signal. This module
 * is the deterministic safety rail used alongside it and when learned assets
 * are unavailable. Its rules therefore stay deliberately conservative:
 * reject only high-confidence contradictions that can be established from
 * surface structure without pretending to perform full entailment.
 */

import { guessPartOfSpeech } from "@/lib/nlp/posTagger";
import type { EntailmentLabel } from "./englishQuality";

export interface NliJudge {
  judge(premise: string, hypothesis: string): Promise<{ label: EntailmentLabel; score: number; reason: string }>;
}

function normalize(text: string): string {
  return text.trim().toLowerCase();
}

function wordTokens(text: string): string[] {
  return (normalize(text).match(/[a-z]+(?:['’][a-z]+)?/g) ?? [])
    .map((token) => token.replace(/’/g, "'"));
}

function wordSet(text: string): Set<string> {
  return new Set(wordTokens(text));
}

const NEGATION_WORDS = new Set([
  "not", "no", "never", "without", "neither", "nor", "cannot",
  "can't", "cant", "couldn't", "couldnt", "didn't", "didnt",
  "doesn't", "doesnt", "don't", "dont", "hadn't", "hadnt",
  "hasn't", "hasnt", "haven't", "havent", "isn't", "isnt",
  "mustn't", "mustnt", "needn't", "neednt", "shouldn't", "shouldnt",
  "wasn't", "wasnt", "weren't", "werent", "won't", "wont",
  "wouldn't", "wouldnt", "shan't", "shant", "aren't", "arent",
]);

/** Positive carrier left after removing a contraction's negative force. */
const NEGATED_BASE_FORMS = new Map<string, string>([
  ["cannot", "can"], ["can't", "can"], ["cant", "can"],
  ["couldn't", "could"], ["couldnt", "could"],
  ["didn't", "did"], ["didnt", "did"],
  ["doesn't", "does"], ["doesnt", "does"],
  ["don't", "do"], ["dont", "do"],
  ["hadn't", "had"], ["hadnt", "had"],
  ["hasn't", "has"], ["hasnt", "has"],
  ["haven't", "have"], ["havent", "have"],
  ["isn't", "is"], ["isnt", "is"],
  ["aren't", "are"], ["arent", "are"],
  ["mustn't", "must"], ["mustnt", "must"],
  ["needn't", "need"], ["neednt", "need"],
  ["shouldn't", "should"], ["shouldnt", "should"],
  ["wasn't", "was"], ["wasnt", "was"],
  ["weren't", "were"], ["werent", "were"],
  ["won't", "will"], ["wont", "will"],
  ["wouldn't", "would"], ["wouldnt", "would"],
  ["shan't", "shall"], ["shant", "shall"],
]);

function isNegationToken(token: string): boolean {
  return NEGATION_WORDS.has(token) || token.endsWith("n't");
}

const QUANT_WORDS = new Set(["all", "every", "each", "none", "only", "always", "never"]);

function negationCount(text: string): number {
  return wordTokens(text).filter(isNegationToken).length;
}

/**
 * Strip only negative force while preserving its auxiliary/modal carrier.
 * This gives equivalent signatures to `couldn't approve` and
 * `could not approve`, while still making `could approve` vs
 * `couldn't approve` directly comparable as a real negation flip.
 */
function negationSignature(text: string): string {
  const kept: string[] = [];
  for (const token of wordTokens(text)) {
    const positiveBase = NEGATED_BASE_FORMS.get(token);
    if (positiveBase) {
      kept.push(positiveBase);
      continue;
    }
    if (isNegationToken(token)) continue;
    kept.push(token);
  }
  return kept.join(" ");
}

function directNegationFlip(premise: string, hypothesis: string): boolean {
  if (negationCount(premise) === negationCount(hypothesis)) return false;
  return negationSignature(premise) === negationSignature(hypothesis);
}

function hasQuantityMismatch(premise: string, hypothesis: string): boolean {
  const p = wordSet(premise);
  const h = wordSet(hypothesis);
  for (const q of QUANT_WORDS) {
    if ((p.has(q) || h.has(q)) && p.has(q) !== h.has(q)) return true;
  }
  return false;
}

const ROLE_FUNCTION_WORDS = new Set([
  "a", "an", "the", "this", "that", "these", "those",
  "and", "or", "but", "yet", "of", "to", "for", "with", "from", "into", "onto",
  "in", "on", "at", "through", "during", "after", "before", "around", "about", "by",
  "am", "is", "are", "was", "were", "be", "been", "being",
  "do", "does", "did", "have", "has", "had",
  "can", "could", "may", "might", "must", "shall", "should", "will", "would",
]);
const BE_AUXILIARIES = new Set(["am", "is", "are", "was", "were", "be", "been", "being"]);

function roleTokens(text: string): string[] {
  return normalize(text).match(/[a-z]+/g) ?? [];
}

function isVerbAnchor(token: string): boolean {
  return !ROLE_FUNCTION_WORDS.has(token) && guessPartOfSpeech(token) === "verb";
}

function isReferentToken(token: string): boolean {
  if (ROLE_FUNCTION_WORDS.has(token)) return false;
  const part = guessPartOfSpeech(token);
  return part !== "verb" && part !== "adverb" && part !== "adjective";
}

function nearestReferent(tokens: string[], start: number, direction: -1 | 1): string | null {
  for (let index = start + direction; index >= 0 && index < tokens.length; index += direction) {
    if (isReferentToken(tokens[index])) return tokens[index];
  }
  return null;
}

function collectReferents(tokens: string[], start: number, end = tokens.length): Set<string> {
  const result = new Set<string>();
  for (let index = Math.max(0, start); index < Math.min(end, tokens.length); index += 1) {
    if (isReferentToken(tokens[index])) result.add(tokens[index]);
  }
  return result;
}

interface ShallowRoles {
  agent: string;
  nonAgents: Set<string>;
}

function shallowRoles(tokens: string[], verbIndex: number): ShallowRoles | null {
  let passiveAuxIndex = -1;
  for (let index = Math.max(0, verbIndex - 2); index < verbIndex; index += 1) {
    if (BE_AUXILIARIES.has(tokens[index])) passiveAuxIndex = index;
  }
  const byIndex = tokens.indexOf("by", verbIndex + 1);

  if (passiveAuxIndex >= 0 && byIndex > verbIndex) {
    const patient = nearestReferent(tokens, passiveAuxIndex, -1);
    const agent = nearestReferent(tokens, byIndex, 1);
    if (!patient || !agent || patient === agent) return null;
    const nonAgents = collectReferents(tokens, verbIndex + 1, byIndex);
    nonAgents.add(patient);
    nonAgents.delete(agent);
    return { agent, nonAgents };
  }

  const agent = nearestReferent(tokens, verbIndex, -1);
  if (!agent) return null;
  const nonAgents = collectReferents(tokens, verbIndex + 1);
  nonAgents.delete(agent);
  if (nonAgents.size === 0) return null;
  return { agent, nonAgents };
}

/**
 * Conservative same-verb role-swap rail.
 *
 * We intentionally skip comma/semicolon-heavy clauses: a shallow deterministic
 * parser should not pretend it can resolve attachment across complex syntax.
 * For simple clauses, a contradiction is high-confidence when the premise's
 * agent reappears in a non-agent role while the hypothesis's agent occupied a
 * non-agent role in the premise. Passive `... was VERBed by ...` is normalized
 * first, so a valid active/passive rewrite is not mistaken for a swap.
 */
function genericRoleSwap(premise: string, hypothesis: string): boolean {
  if (/[;,]/.test(premise) || /[;,]/.test(hypothesis)) return false;

  const pTokens = roleTokens(premise);
  const hTokens = roleTokens(hypothesis);
  if (pTokens.length < 3 || hTokens.length < 3) return false;

  const hypothesisVerbPositions = new Map<string, number[]>();
  hTokens.forEach((token, index) => {
    if (!isVerbAnchor(token)) return;
    const positions = hypothesisVerbPositions.get(token) ?? [];
    positions.push(index);
    hypothesisVerbPositions.set(token, positions);
  });

  for (let pIndex = 0; pIndex < pTokens.length; pIndex += 1) {
    const verb = pTokens[pIndex];
    if (!isVerbAnchor(verb)) continue;
    const hPositions = hypothesisVerbPositions.get(verb);
    if (!hPositions) continue;

    const premiseRoles = shallowRoles(pTokens, pIndex);
    if (!premiseRoles) continue;

    for (const hIndex of hPositions) {
      const hypothesisRoles = shallowRoles(hTokens, hIndex);
      if (!hypothesisRoles || premiseRoles.agent === hypothesisRoles.agent) continue;
      if (
        premiseRoles.nonAgents.has(hypothesisRoles.agent) &&
        hypothesisRoles.nonAgents.has(premiseRoles.agent)
      ) {
        return true;
      }
    }
  }

  return false;
}

export function createRuleNliJudge(): NliJudge {
  return {
    async judge(premise: string, hypothesis: string) {
      if (!premise.trim() || !hypothesis.trim()) {
        return { label: "neutral", score: 0.5, reason: "empty input" };
      }

      const negP = negationCount(premise);
      const negH = negationCount(hypothesis);
      if (negP !== negH && directNegationFlip(premise, hypothesis)) {
        return { label: "contradict", score: 0.9, reason: `negation count ${negP}→${negH}` };
      }
      if (hasQuantityMismatch(premise, hypothesis)) {
        return { label: "contradict", score: 0.75, reason: "quantity/quantifier mismatch" };
      }
      if (genericRoleSwap(premise, hypothesis)) {
        return { label: "contradict", score: 0.88, reason: "reciprocal role swap around shared verb" };
      }

      // Cheap invented-number guard. Full protected-span/anchor validation is
      // still authoritative elsewhere in the production pipeline.
      const pNums = new Set((premise.match(/\b\d+[\d.,]*%?\b/g) ?? []).map((s) => s.replace(/,/g, "")));
      const hNums = hypothesis.match(/\b\d+[\d.,]*%?\b/g) ?? [];
      for (const n of hNums) {
        if (!pNums.has(n.replace(/,/g, ""))) {
          return { label: "contradict", score: 0.7, reason: `invented number ${n}` };
        }
      }
      return { label: "neutral", score: 0.55, reason: "no contradiction signal" };
    },
  };
}

export function createPipelineNliJudge(
  pipeline: (premise: string, hypothesis: string) => Promise<{ label: string; score: number }>
): NliJudge {
  return {
    async judge(premise: string, hypothesis: string) {
      try {
        const result = await pipeline(premise, hypothesis);
        const raw = result.label.toLowerCase();
        const label: EntailmentLabel =
          raw.includes("contradict") ? "contradict" : raw.includes("entail") ? "entail" : "neutral";
        return { label, score: result.score, reason: `onnx ${result.label} ${result.score.toFixed(2)}` };
      } catch {
        return createRuleNliJudge().judge(premise, hypothesis);
      }
    },
  };
}
