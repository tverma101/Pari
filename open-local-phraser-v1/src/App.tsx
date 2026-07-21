import { memo, startTransition, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type RefObject } from "react";
import { createPortal } from "react-dom";

import { analyzeGrammar, grammarHealthScore } from "@/lib/nlp/grammar";
import { getSentenceForRange } from "@/lib/nlp/sentenceSplit";
import { rankCandidatesByEmbedding, rankCandidatesByEmbeddingEnsemble } from "@/lib/ranking/embeddingRanker";
import { detectProtectedEntityTerms } from "@/lib/ranking/entityGuard";
import { getRankingModelEstimatedMemoryMb, getRankingModelIds } from "@/lib/ranking/modelRegistry";
import { getModelInfoSnapshot, probeModelInfo } from "@/lib/ranking/modelManager";
import { rankCandidatesByRule } from "@/lib/ranking/ruleBasedRanker";
import type { ModelInfo, RankingResult } from "@/lib/ranking/types";
import { MODE_OPTIONS, percentToStrengthLevel } from "@/lib/phraseEngine/rules";
import { countSentences, countWords, parseFreezeEntries, rewriteText } from "@/lib/phraseEngine/rewriteText";
import type { RewriteToken } from "@/lib/phraseEngine/types";
import {
  generateAdvancedAlternatives,
  selectTokensForEnhancement,
} from "@/lib/rewriteStack/advancedParaphrase";
import {
  getRewriteAssistantEstimatedMemoryMb,
  getRewriteAssistantModelIds,
} from "@/lib/rewriteStack/modelRegistry";
import { applyTheme, STRENGTH_STEPS, loadSettings, saveSettings, type AppSettings } from "@/lib/settings/settingsStore";
import type { RiskLevel } from "@/lib/types";
import { cn } from "@/utils/cn";

const SAMPLE_TEXT =
  "Artificial intelligence is changing the way people work and learn. It can help students improve their writing, find new ideas quickly, and understand difficult topics. Many companies use these powerful tools to make their work more efficient.";

const ADVANCED_ALTERNATIVE_DELAY_MS = 850;
const ADVANCED_SUGGESTION_MIN_OPTIONS = 40;
const OPTION_PREVIEW_LIMIT = 40;
const BACKGROUND_INDEX_DELAY_MS = 90;
const BACKGROUND_INDEX_TOKEN_LIMIT = 32;
const SEMANTIC_REFINEMENT_LIMIT = 24;
const INTERACTIVE_RERANK_DELAY_MS = 260;
const SEMANTIC_REFINEMENT_DELAY_MS = 1200;
interface RankingState {
  tokenId: string;
  provider: "rule-based" | "embedding";
  loading: boolean;
  results: RankingResult[];
  notice?: string;
}

type AppliedRewriteSettings = Pick<
  AppSettings,
  "freezeWords" | "mode" | "rankingProvider" | "semanticModel" | "strength"
>;

function toAppliedRewriteSettings(settings: AppSettings): AppliedRewriteSettings {
  return {
    mode: settings.mode,
    strength: settings.strength,
    freezeWords: settings.freezeWords,
    rankingProvider: settings.rankingProvider,
    semanticModel: settings.semanticModel,
  };
}

function loadStartupSettings(): AppSettings {
  const loaded = loadSettings();

  return {
    ...loaded,
    rankingProvider: "rule-based",
  };
}

function riskBadgeClass(risk: RiskLevel): string {
  if (risk === "high") return "badge-risk-high";
  if (risk === "medium") return "badge-risk-medium";
  return "badge-risk-low";
}

function modelStatusBadge(status: ModelInfo["status"]): string {
  switch (status) {
    case "downloading": return "badge-info";
    case "loading": return "badge-info";
    case "ready": return "badge-status-ready";
    case "failed": return "badge-risk-high";
    default: return "badge-muted";
  }
}

function modelStatusText(status: ModelInfo["status"]): string {
  switch (status) {
    case "downloading": return "Downloading";
    case "loading": return "Loading";
    case "ready": return "Ready";
    case "failed": return "Needs retry";
    default: return "Idle";
  }
}

function candidateSourceLabel(source: RewriteToken["source"] | RankingResult["option"]["source"]): string {
  switch (source) {
    case "generator": return "AI";
    case "contextual-mlm": return "Ctx";
    case "deep-bank": return "Deep";
    case "phrase-bank": return "Phrase";
    case "static-bank": return "Bank";
    default: return "Rule";
  }
}

function popoverStyle(anchorRect: DOMRect | null): CSSProperties {
  if (!anchorRect || typeof window === "undefined") return { opacity: 0 };

  const vw = window.innerWidth;
  const vh = window.innerHeight;

  if (vw < 760) {
    const mobileWidth = Math.min(286, Math.max(248, vw - 90));
    const left = Math.min(
      vw - mobileWidth - 12,
      Math.max(12, Math.round(anchorRect.left + anchorRect.width / 2 - mobileWidth / 2))
    );

    return {
      position: "fixed",
      left,
      bottom: 10,
      width: mobileWidth,
      maxWidth: "calc(100vw - 48px)",
      maxHeight: Math.min(310, vh - 24),
    };
  }

  const w = Math.min(320, Math.max(286, vw - 40));
  const estH = 328;
  const left = Math.min(vw - w - 12, Math.max(12, anchorRect.left + anchorRect.width / 2 - w / 2));
  const canBelow = anchorRect.bottom + estH + 12 <= vh;
  const top = canBelow
    ? Math.min(vh - estH - 12, anchorRect.bottom + 8)
    : Math.max(12, anchorRect.top - estH - 8);

  return { position: "fixed", top, left, width: w, maxWidth: "calc(100vw - 24px)" };
}

const OutputText = memo(function OutputText({
  tokens,
  activeTokenId,
  onActivate,
}: {
  tokens: RewriteToken[];
  activeTokenId: string | null;
  onActivate: (tokenId: string, element: HTMLButtonElement) => void;
}) {
  return (
    <div className="whitespace-pre-wrap break-words text-[15px] leading-7 text-[var(--text)]">
      {tokens.map((token) => {
        if (!token.isWord) return <span key={token.id}>{token.text}</span>;

        if (token.frozen || token.alternatives.length === 0) {
          return (
            <span
              key={token.id}
              className={cn("px-0.5 rounded", token.frozen ? "output-word-btn frozen" : "")}
            >
              {token.text}
            </span>
          );
        }

        const active = activeTokenId === token.id;
        return (
          <button
            key={token.id}
            type="button"
            data-word-token="true"
            data-token-id={token.id}
            onFocus={(e) => onActivate(token.id, e.currentTarget)}
            onClick={(e) => onActivate(token.id, e.currentTarget)}
            className={cn(
              "output-word-btn",
              !token.changed && "candidate",
              token.changed && "changed",
              active && "active"
            )}
          >
            {token.text}
          </button>
        );
      })}
    </div>
  );
});

function AlternativesList({
  token,
  rankingState,
  onPick,
  compact = false,
}: {
  token: RewriteToken;
  rankingState: RankingState | null;
  onPick: (tokenId: string, alternativeId: string | null) => void;
  compact?: boolean;
}) {
  const results = rankingState?.tokenId === token.id ? rankingState.results : [];
  const visibleResults = results.slice(0, OPTION_PREVIEW_LIMIT);
  const hiddenCount = Math.max(0, results.length - visibleResults.length);

  return (
    <div className={cn("space-y-1", compact && "space-y-0.5")}>
      <button
        type="button"
        onClick={() => onPick(token.id, null)}
        className={cn(
          "flex w-full items-center justify-between rounded-[8px] border text-left transition",
          compact ? "px-2 py-1.5 text-[11px]" : "px-3 py-2 text-sm",
          token.selectedAlternativeId === null
            ? "border-[#a7d5b5] bg-[#e9f5ec] text-[#24342c]"
            : "border-[#d7e2da] bg-white text-[#24342c] hover:bg-[#f3f8f5]"
        )}
      >
        <span className="min-w-0 truncate">
          <span className="font-medium">{token.originalText}</span>
          <span className="ml-1.5 text-[9px] uppercase tracking-[0.12em] text-[#8b9a90]">Original</span>
        </span>
        {token.selectedAlternativeId === null && (
          <svg className="h-3.5 w-3.5 shrink-0 text-[#499557]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
      </button>

      {visibleResults.map((result) => {
        const selected = token.selectedAlternativeId === result.option.id;
        return (
          <button
            type="button"
            key={result.option.id}
            onClick={() => onPick(token.id, result.option.id)}
            className={cn(
              "flex w-full items-start justify-between gap-2 rounded-[8px] border text-left transition",
              compact ? "px-2 py-1.5" : "px-3 py-2",
              selected
                ? "border-[#a7d5b5] bg-[#e9f5ec] text-[#24342c]"
                : "border-[#d7e2da] bg-white text-[#24342c] hover:bg-[#f3f8f5]"
            )}
            style={compact ? { minHeight: 32 } : undefined}
          >
            <span className="min-w-0">
              <span className={cn("block truncate font-semibold", compact ? "text-[12px]" : "text-sm")}>
                {result.option.replacement}
              </span>
              <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[9px] text-[#8b9a90]">
                <span>{candidateSourceLabel(result.option.source)}</span>
                {result.option.label && <span>{result.option.label}</span>}
                {result.risk !== "low" && (
                  <span className={cn("rounded-full border px-1.5 py-0.5", riskBadgeClass(result.risk))}>
                    {result.risk}
                  </span>
                )}
                {!compact && typeof result.semanticScore === "number" && <span>semantic fit</span>}
                {!compact && typeof result.grammarScore === "number" && <span>grammar fit</span>}
              </span>
              {result.warnings.length > 0 && !compact && (
                <span className="mt-1 block text-[10px] leading-3 text-[#8b9a90]">
                  {result.warnings.join(" | ")}
                </span>
              )}
            </span>
            <span className="shrink-0 text-right">
              {selected ? (
                <svg className="h-3.5 w-3.5 shrink-0 text-[#499557]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              ) : null}
            </span>
          </button>
        );
      })}

      {hiddenCount > 0 && (
        <div className="px-2 py-1 text-[10px] text-[#7a8b82]">
          +{hiddenCount} more local matches ranked below.
        </div>
      )}

      {results.length === 0 && (
        <div className="rounded-[8px] border border-dashed border-[#d7e2da] px-2 py-2 text-[11px] text-[#7a8b82]">
          No local alternatives for this word yet.
        </div>
      )}

      {rankingState?.tokenId === token.id && rankingState.loading && (
        <div className="rounded-[8px] border border-dashed border-[#d7e2da] px-2 py-1.5 text-[10px] text-[#7a8b82]">
          Loading deeper matches.
        </div>
      )}
    </div>
  );
}

function AlternativesPopover({
  token,
  rankingState,
  modelInfo,
  style,
  onPick,
  onRevertSentence,
  canRevertSentence,
  onClose,
  popoverRef,
}: {
  token: RewriteToken;
  rankingState: RankingState | null;
  modelInfo: ModelInfo;
  style: CSSProperties;
  onPick: (tokenId: string, alternativeId: string | null) => void;
  onRevertSentence: (tokenId: string) => void;
  canRevertSentence: boolean;
  onClose: () => void;
  popoverRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      ref={popoverRef}
      data-popover="true"
      data-testid="synonym-popover"
      style={style}
      className="z-50 max-h-[340px] overflow-hidden rounded-[10px] border border-[#d7e2da] bg-white shadow-xl animate-fade-in"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="border-b border-[#eef2ef] px-2.5 py-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[8px] font-semibold uppercase tracking-[0.18em] text-[#839089]">
              Synonyms
            </div>
            <div className="truncate text-[13px] font-semibold text-[#24342c]">
              {token.originalText}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md border border-[#d7e2da] bg-white px-2 py-1 text-[10px] text-[#7a8c81] transition hover:bg-[#f3f8f5]"
          >
            Close
          </button>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[9px]">
          <span className={cn("rounded-full border px-1.5 py-0.5 font-medium", modelStatusBadge(modelInfo.status))}>
            {rankingState?.provider === "embedding" ? "Semantic" : "Fast"}
          </span>
          <span className="rounded-full border border-[#d7e2da] px-1.5 py-0.5 text-[#7a8c81]">
            {candidateSourceLabel(token.source)}
          </span>
          <span className="rounded-full border border-[#d7e2da] px-1.5 py-0.5 text-[#7a8c81]">
            {token.alternatives.length} choices
          </span>
          {canRevertSentence && (
            <button
              type="button"
              onClick={() => onRevertSentence(token.id)}
              className="rounded-full border border-[#cddfd3] bg-[#f5faf6] px-2 py-0.5 font-semibold text-[#2f7b4c] transition hover:bg-[#e9f5ec]"
            >
              Revert sentence
            </button>
          )}
        </div>
      </div>

      <div className="max-h-[254px] overflow-auto px-1.5 py-1.5">
        <AlternativesList token={token} rankingState={rankingState} onPick={onPick} compact />
      </div>
    </div>
  );
}

export default function App() {
  const [input, setInput] = useState("");
  const [submittedInput, setSubmittedInput] = useState("");
  const [settings, setSettings] = useState(() => loadStartupSettings());
  const [appliedSettings, setAppliedSettings] = useState<AppliedRewriteSettings>(() => toAppliedRewriteSettings(loadStartupSettings()));
  const [manualChoices, setManualChoices] = useState<Record<string, string | null>>({});
  const [semanticChoices, setSemanticChoices] = useState<Record<string, string | null>>({});
  const [modelAlternatives, setModelAlternatives] = useState<Record<string, RankingResult["option"][]>>({});
  const [activeTokenId, setActiveTokenId] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [copied, setCopied] = useState(false);
  const [modelInfo, setModelInfo] = useState<ModelInfo>(() => getModelInfoSnapshot());
  const [entityGuardTerms, setEntityGuardTerms] = useState<string[]>([]);
  const [entityGuardError, setEntityGuardError] = useState<string | null>(null);
  const [rankingState, setRankingState] = useState<RankingState | null>(null);
  const [isParaphrasing, setIsParaphrasing] = useState(false);
  const [isSemanticRefining, setIsSemanticRefining] = useState(false);
  const [isAdvancedGenerating, setIsAdvancedGenerating] = useState(false);
  const [isBackgroundIndexing, setIsBackgroundIndexing] = useState(false);

  const popoverRef = useRef<HTMLDivElement>(null);
  const activeAnchorRef = useRef<HTMLButtonElement | null>(null);
  const pulseTimerRef = useRef<number | null>(null);

  useEffect(() => { saveSettings(settings); }, [settings]);

  useEffect(() => {
    const update = () => { applyTheme(settings.theme); };
    update();
    if (settings.theme !== "system") return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [settings.theme]);

  useEffect(() => {
    probeModelInfo(settings.semanticModel).then(setModelInfo).catch(() => undefined);
  }, [settings.semanticModel]);

  useEffect(() => {
    return () => {
      if (pulseTimerRef.current) window.clearTimeout(pulseTimerRef.current);
    };
  }, []);

  useEffect(() => {
    setActiveTokenId(null);
    setRankingState(null);
    activeAnchorRef.current = null;
    setModelAlternatives({});
    setIsBackgroundIndexing(false);
  }, [input]);

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (target.closest("[data-word-token='true']")) return;
      if (target.closest("[data-popover='true']")) return;
      if (target.closest("[data-inspector-token='true']")) return;
      setActiveTokenId(null);
      setRankingState(null);
      activeAnchorRef.current = null;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setActiveTokenId(null);
        setRankingState(null);
        activeAnchorRef.current = null;
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (!activeTokenId) return undefined;
    const refresh = () => {
      const element = activeAnchorRef.current;
      if (element) setAnchorRect(element.getBoundingClientRect());
    };
    refresh();
    window.addEventListener("resize", refresh);
    window.addEventListener("scroll", refresh, true);
    return () => {
      window.removeEventListener("resize", refresh);
      window.removeEventListener("scroll", refresh, true);
    };
  }, [activeTokenId]);

  const effectiveFreezeWords = useMemo(
    () => [appliedSettings.freezeWords, entityGuardTerms.join(", ")]
      .map((entry) => entry.trim())
      .filter(Boolean)
      .join(", "),
    [appliedSettings.freezeWords, entityGuardTerms]
  );

  const freezeEntries = useMemo(() => parseFreezeEntries(effectiveFreezeWords), [effectiveFreezeWords]);
  const resolvedChoices = useMemo(
    () => ({ ...semanticChoices, ...manualChoices }),
    [manualChoices, semanticChoices]
  );

  const rewrite = useMemo(
    () => rewriteText(submittedInput, {
      mode: appliedSettings.mode,
      strength: appliedSettings.strength,
      freezeWords: effectiveFreezeWords,
    }, resolvedChoices, modelAlternatives),
    [appliedSettings.mode, appliedSettings.strength, effectiveFreezeWords, modelAlternatives, resolvedChoices, submittedInput]
  );

  const activeToken = useMemo(
    () => rewrite.tokens.find((token) => token.id === activeTokenId) ?? null,
    [activeTokenId, rewrite.tokens]
  );

  const hasDraft = input.trim().length > 0;
  const hasSubmitted = submittedInput.trim().length > 0;
  const hasOutput = rewrite.outputText.trim().length > 0;
  const hasPendingRewriteSettings = useMemo(
    () =>
      settings.mode !== appliedSettings.mode ||
      settings.strength !== appliedSettings.strength ||
      settings.freezeWords !== appliedSettings.freezeWords ||
      settings.rankingProvider !== appliedSettings.rankingProvider ||
      settings.semanticModel !== appliedSettings.semanticModel,
    [appliedSettings, settings]
  );
  const draftChanged = hasSubmitted && (input !== submittedInput || hasPendingRewriteSettings);
  const inputWords = countWords(input);
  const inputSentences = countSentences(input);
  const outputWords = countWords(rewrite.outputText);
  const outputSentences = countSentences(rewrite.outputText);
  const changedTokens = useMemo(
    () => rewrite.tokens.filter((token) => token.isWord && token.changed),
    [rewrite.tokens]
  );
  const candidateTokens = useMemo(
    () => rewrite.tokens.filter((token) => token.isWord && token.alternatives.length > 0),
    [rewrite.tokens]
  );
  const grammarText = hasOutput ? rewrite.outputText : input;
  const grammarIssues = useMemo(() => analyzeGrammar(grammarText), [grammarText]);
  const grammarScore = useMemo(() => grammarHealthScore(grammarIssues), [grammarIssues]);
  const activeMode = MODE_OPTIONS.find((mode) => mode.value === settings.mode) ?? MODE_OPTIONS[0];
  const activeStrengthIndex = Math.max(0, STRENGTH_STEPS.findIndex((step) => step.value === settings.strength));
  const ensembleModelIds = useMemo(() => getRankingModelIds(), []);
  const rewriteAssistantIds = useMemo(() => getRewriteAssistantModelIds(), []);
  const estimatedModelMemoryMb = useMemo(() => getRankingModelEstimatedMemoryMb(), []);
  const estimatedRewriteStackMemoryMb = useMemo(() => getRewriteAssistantEstimatedMemoryMb(), []);
  const estimatedTotalStackMemoryMb = estimatedModelMemoryMb + estimatedRewriteStackMemoryMb;
  const strengthFill =
    STRENGTH_STEPS.length > 1
      ? (activeStrengthIndex / (STRENGTH_STEPS.length - 1)) * 100
      : 0;
  const freezeWordChips = useMemo(() => parseFreezeEntries(effectiveFreezeWords), [effectiveFreezeWords]);
  const sliderLevel = activeStrengthIndex + 1;
  const charCount = input.length;
  const showRewriteActivity = isAdvancedGenerating && activeToken !== null;

  const buildTokenRankingContext = useCallback((token: RewriteToken) => {
    const sentence = getSentenceForRange(rewrite.outputText, token.start, token.end);
    return {
      fullText: rewrite.outputText,
      sentence: sentence.text,
      selectedText: token.text,
      mode: appliedSettings.mode,
      strength: percentToStrengthLevel(appliedSettings.strength),
      freezeWords: freezeEntries,
      partOfSpeech: token.partOfSpeech,
      selectionStart: token.start,
      selectionEnd: token.end,
      sentenceStart: sentence.start,
    } as const;
  }, [appliedSettings.mode, appliedSettings.strength, freezeEntries, rewrite.outputText]);

  const buildBaseRankingResults = useCallback((token: RewriteToken) => {
    const context = buildTokenRankingContext(token);
    return {
      context,
      results: rankCandidatesByRule(token.alternatives, context),
    };
  }, [buildTokenRankingContext]);

  const getSentenceTokens = useCallback((token: RewriteToken) => {
    const sentence = getSentenceForRange(rewrite.outputText, token.start, token.end);
    return rewrite.tokens.filter((entry) => {
      if (!entry.isWord) return false;
      return entry.start >= sentence.start && entry.end <= sentence.end;
    });
  }, [rewrite.outputText, rewrite.tokens]);

  const activeSentenceCanRevert = useMemo(
    () => (activeToken ? getSentenceTokens(activeToken).some((token) => token.changed) : false),
    [activeToken, getSentenceTokens]
  );

  useEffect(() => {
    if (!activeToken || !hasSubmitted || !activeToken.isWord || activeToken.frozen) {
      return;
    }
    if (activeToken.alternatives.length >= ADVANCED_SUGGESTION_MIN_OPTIONS) {
      return;
    }
    if (Object.prototype.hasOwnProperty.call(modelAlternatives, activeToken.id)) {
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (cancelled) return;
      setIsAdvancedGenerating(true);

      generateAdvancedAlternatives(
        activeToken,
        submittedInput,
        appliedSettings.mode,
        percentToStrengthLevel(appliedSettings.strength)
      )
        .then((suggestions) => {
          if (cancelled || suggestions.length === 0) return;
          startTransition(() => {
            setModelAlternatives((current) => ({
              ...current,
              [activeToken.id]: suggestions,
            }));
          });
        })
        .catch((error) => {
          if (!cancelled) {
            console.warn("advanced token suggestions failed", error);
          }
        })
        .finally(() => {
          if (!cancelled) {
            setIsAdvancedGenerating(false);
          }
        });
    }, ADVANCED_ALTERNATIVE_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    activeToken,
    hasSubmitted,
    modelAlternatives,
    appliedSettings.mode,
    appliedSettings.strength,
    submittedInput,
  ]);

  useEffect(() => {
    if (!hasSubmitted || rewrite.tokens.length === 0) {
      setIsBackgroundIndexing(false);
      return;
    }

    const tokensToIndex = selectTokensForEnhancement(rewrite.tokens, BACKGROUND_INDEX_TOKEN_LIMIT)
      .filter((token) =>
        !token.isPhrase &&
        token.alternatives.length > 0 &&
        token.alternatives.length < OPTION_PREVIEW_LIMIT &&
        !Object.prototype.hasOwnProperty.call(modelAlternatives, token.id)
      );

    if (tokensToIndex.length === 0) {
      setIsBackgroundIndexing(false);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        if (cancelled) return;
        setIsBackgroundIndexing(true);
        const indexed: Record<string, RankingResult["option"][]> = {};

        for (const token of tokensToIndex) {
          if (cancelled) return;
          try {
            indexed[token.id] = await generateAdvancedAlternatives(
              token,
              submittedInput,
              appliedSettings.mode,
              percentToStrengthLevel(appliedSettings.strength)
            );
          } catch {
            indexed[token.id] = [];
          }
        }

        if (cancelled) return;
        startTransition(() => {
          setModelAlternatives((current) => ({
            ...current,
            ...indexed,
          }));
          setIsBackgroundIndexing(false);
        });
      })();
    }, BACKGROUND_INDEX_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    appliedSettings.mode,
    appliedSettings.strength,
    hasSubmitted,
    modelAlternatives,
    rewrite.tokens,
    submittedInput,
  ]);

  useEffect(() => {
    if (!hasSubmitted || appliedSettings.rankingProvider !== "embedding" || activeTokenId !== null) {
      setSemanticChoices({});
      setIsSemanticRefining(false);
      return;
    }

    const draft = rewriteText(submittedInput, {
      mode: appliedSettings.mode,
      strength: appliedSettings.strength,
      freezeWords: effectiveFreezeWords,
    }, {}, modelAlternatives);
    const tokensToRefine = draft.tokens
      .filter((token) =>
        token.isWord &&
        token.alternatives.length > 0 &&
        (token.changed || (modelAlternatives[token.id]?.length ?? 0) > 0)
      )
      .slice(0, SEMANTIC_REFINEMENT_LIMIT);

    if (tokensToRefine.length === 0) {
      setSemanticChoices({});
      setIsSemanticRefining(false);
      return;
    }

    let cancelled = false;

    const runRefinement = async () => {
      if (cancelled) return;
      setIsSemanticRefining(true);
      const nextChoices: Record<string, string | null> = {};

      for (const token of tokensToRefine) {
        const sentence = getSentenceForRange(draft.outputText, token.start, token.end);
        const context = {
          fullText: draft.outputText,
          sentence: sentence.text,
          selectedText: token.text,
          mode: appliedSettings.mode,
          strength: percentToStrengthLevel(appliedSettings.strength),
          freezeWords: freezeEntries,
          partOfSpeech: token.partOfSpeech,
          selectionStart: token.start,
          selectionEnd: token.end,
          sentenceStart: sentence.start,
        } as const;

        try {
          const ranked = await rankCandidatesByEmbeddingEnsemble(token.alternatives, context);
          const top = ranked[0];
          if (
            top &&
            top.option.id !== token.selectedAlternativeId &&
            top.risk !== "high" &&
            (top.semanticScore ?? 0) >= 0.72
          ) {
            nextChoices[token.id] = top.option.id;
          }
        } catch {
          if (!cancelled) {
            setIsSemanticRefining(false);
          }
          return;
        }
      }

      if (cancelled) return;
      startTransition(() => {
        setSemanticChoices(nextChoices);
        setIsSemanticRefining(false);
      });
    };

    const timer = window.setTimeout(() => {
      void runRefinement();
    }, SEMANTIC_REFINEMENT_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    effectiveFreezeWords,
    freezeEntries,
    hasSubmitted,
    appliedSettings.mode,
    modelAlternatives,
    appliedSettings.rankingProvider,
    appliedSettings.strength,
    activeTokenId,
    submittedInput,
  ]);

  useEffect(() => {
    if (!activeToken || !activeToken.isWord || activeToken.alternatives.length === 0) {
      setRankingState(null);
      return;
    }

    const { context, results: baseResults } = buildBaseRankingResults(activeToken);

    if (appliedSettings.rankingProvider !== "embedding" || modelInfo.status !== "ready") {
      setRankingState({ tokenId: activeToken.id, provider: "rule-based", loading: false, results: baseResults });
      return;
    }

    let cancelled = false;
    setRankingState({
      tokenId: activeToken.id,
      provider: "embedding",
      loading: true,
      results: baseResults,
      notice: "Re-ranking with the fast local semantic model.",
    });

    const timer = window.setTimeout(() => {
      rankCandidatesByEmbedding(activeToken.alternatives, context, appliedSettings.semanticModel)
        .then((results) => {
          if (!cancelled) setRankingState({ tokenId: activeToken.id, provider: "embedding", loading: false, results });
        })
        .catch(() => {
          if (!cancelled) setRankingState({
            tokenId: activeToken.id,
            provider: "rule-based",
            loading: false,
            results: baseResults,
            notice: "Semantic ranking failed. Rule-based ordering is active.",
          });
        });
    }, INTERACTIVE_RERANK_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    activeToken,
    appliedSettings.rankingProvider,
    appliedSettings.semanticModel,
    buildBaseRankingResults,
    modelInfo.status,
  ]);

  const closeTokenTools = () => {
    setActiveTokenId(null);
    setRankingState(null);
    activeAnchorRef.current = null;
  };

  const setStrengthLevel = (level: number) => {
    const clamped = Math.max(1, Math.min(STRENGTH_STEPS.length, level));
    setSettings((current) => ({ ...current, strength: STRENGTH_STEPS[clamped - 1].value }));
  };

  const setRankingProvider = (provider: AppSettings["rankingProvider"]) => {
    setSettings((current) => ({ ...current, rankingProvider: provider }));
    setAppliedSettings((current) => ({ ...current, rankingProvider: provider }));
    closeTokenTools();
  };

  const handleOpenToken = (tokenId: string, element: HTMLButtonElement) => {
    if (activeTokenId === tokenId) {
      activeAnchorRef.current = element;
      setAnchorRect(element.getBoundingClientRect());
      return;
    }
    const token = rewrite.tokens.find((entry) => entry.id === tokenId) ?? null;
    activeAnchorRef.current = element;
    setAnchorRect(element.getBoundingClientRect());
    if (token && token.isWord && token.alternatives.length > 0) {
      const { results } = buildBaseRankingResults(token);
      const canSemanticRerank = appliedSettings.rankingProvider === "embedding" && modelInfo.status === "ready";
      setRankingState({
        tokenId: token.id,
        provider: canSemanticRerank ? "embedding" : "rule-based",
        loading: canSemanticRerank,
        results,
        notice: canSemanticRerank
          ? "Re-ranking with the fast local semantic model."
          : undefined,
      });
    } else {
      setRankingState(null);
    }
    setActiveTokenId(tokenId);
  };

  const handlePickAlternative = (tokenId: string, alternativeId: string | null) => {
    setManualChoices((current) => ({ ...current, [tokenId]: alternativeId }));
    closeTokenTools();
  };

  const handleParaphrase = async () => {
    if (!hasDraft) return;
    setIsParaphrasing(true);
    setEntityGuardError(null);

    let protectedTerms: string[] = [];
    if (settings.rankingProvider === "embedding") {
      try {
        protectedTerms = await detectProtectedEntityTerms(input);
      } catch (error) {
        setEntityGuardError(error instanceof Error ? error.message : String(error));
      }
    }

    setEntityGuardTerms(protectedTerms);
    startTransition(() => {
      setSubmittedInput(input);
      setAppliedSettings(toAppliedRewriteSettings(settings));
      setManualChoices({});
      setSemanticChoices({});
      setModelAlternatives({});
      closeTokenTools();
    });
    if (pulseTimerRef.current) window.clearTimeout(pulseTimerRef.current);
    pulseTimerRef.current = window.setTimeout(() => setIsParaphrasing(false), 260);
  };

  const handleRevertSentence = (tokenId: string) => {
    const token = rewrite.tokens.find((entry) => entry.id === tokenId);
    if (!token) return;

    const sentenceTokens = getSentenceTokens(token);
    if (sentenceTokens.length === 0) return;

    setManualChoices((current) => {
      const next = { ...current };
      sentenceTokens.forEach((entry) => {
        next[entry.id] = null;
      });
      return next;
    });
    setSemanticChoices((current) => {
      const next = { ...current };
      sentenceTokens.forEach((entry) => {
        delete next[entry.id];
      });
      return next;
    });
    closeTokenTools();
  };

  const handleCopy = async () => {
    if (!hasOutput) return;
    try {
      await navigator.clipboard.writeText(rewrite.outputText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access is best-effort in the desktop shell.
    }
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) setInput(text);
    } catch {
      // Clipboard access is best-effort in the desktop shell.
    }
  };

  const handleClear = () => {
    setInput("");
    setSubmittedInput("");
    setManualChoices({});
    setSemanticChoices({});
    setEntityGuardTerms([]);
    setEntityGuardError(null);
    setIsSemanticRefining(false);
    setIsAdvancedGenerating(false);
    setIsBackgroundIndexing(false);
    setModelAlternatives({});
    setAppliedSettings(toAppliedRewriteSettings(settings));
    closeTokenTools();
  };

  return (
    <div className="min-h-screen bg-[#f7f8f6] text-[#1f2522] antialiased" style={{ fontFamily: "'Open Sans', 'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif" }}>
      <header className="sticky top-0 z-40 border-b border-[#e6ebe7] bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1320px] flex-col gap-2 px-4 py-2.5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-[32px] w-[32px] items-center justify-center rounded-[8px] bg-[#499557] text-[15px] font-bold text-white">P</div>
            <div>
              <div className="text-[19px] font-[700] tracking-[-0.015em] text-[#1d6b43]">Open Local Phraser V2</div>
              <div className="text-[11px] text-[#73837b]">Local paraphrasing only. Tap words to swap.</div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#5d6f66]">
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">Local only</span>
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
              {ensembleModelIds.length + rewriteAssistantIds.length + 1} bundled models
            </span>
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
              {(estimatedTotalStackMemoryMb / 1024).toFixed(1)} GB est.
            </span>
            <span className={cn("rounded-full border px-2.5 py-1", modelStatusBadge(modelInfo.status))}>
              {modelStatusText(modelInfo.status)}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1320px] px-3 py-3 sm:px-5 lg:px-6">
        <section className="mb-3 rounded-[14px] border border-[#e1e8e3] bg-white px-3 py-2.5 shadow-sm">
          <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex min-w-0 items-center gap-1.5 overflow-x-auto no-scrollbar">
              <span className="mr-1 shrink-0 text-[11px] font-[700] uppercase tracking-[0.14em] text-[#74847b]">Mode</span>
            {MODE_OPTIONS.map((mode) => {
              const selected = mode.value === settings.mode;
              return (
                <button
                  key={mode.value}
                  type="button"
                  onClick={() => setSettings((current) => ({ ...current, mode: mode.value }))}
                  className={cn(
                    "whitespace-nowrap rounded-full border px-3 py-1.5 text-[12px] transition",
                    selected
                      ? "border-[#a7d5b5] bg-[#e9f5ec] font-[600] text-[#227449]"
                      : "border-[#dde5e0] bg-white text-[#4b5d55] hover:bg-[#f7faf8]"
                  )}
                >
                  {mode.label}
                </button>
              );
            })}
            </div>

            <div className="flex flex-col gap-2 lg:flex-row lg:items-center xl:min-w-[560px]">
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <span className="shrink-0 text-[12px] font-[700] text-[#44544c]">Synonyms</span>
                <button type="button" onClick={() => setStrengthLevel(sliderLevel - 1)} className="text-[18px] leading-none text-[#718078] hover:text-[#2a392f]">‹</button>
                <div className="relative flex-1">
                  <div className="relative h-[6px] rounded-full bg-[#e4ebe6]">
                  <div className="absolute left-0 top-0 h-[6px] rounded-full bg-gradient-to-r from-[#71b98b] to-[#e2c14a]" style={{ width: `${strengthFill}%` }} />
                  {[1, 2, 3, 4, 5].map((level) => (
                    <button
                      key={level}
                      type="button"
                      onClick={() => setStrengthLevel(level)}
                      className={cn(
                        "absolute top-1/2 h-[18px] w-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] bg-white transition",
                        level <= sliderLevel ? "border-[#499557] shadow" : "border-[#cfd8d2]"
                      )}
                      style={{ left: `${((level - 1) / 4) * 100}%` }}
                      aria-label={`Level ${level}`}
                    />
                  ))}
                  </div>
                </div>
                <button type="button" onClick={() => setStrengthLevel(sliderLevel + 1)} className="text-[18px] leading-none text-[#718078] hover:text-[#2a392f]">›</button>
                <span className="w-[58px] shrink-0 rounded-full border border-[#dde5e1] bg-[#f3f7f4] px-2 py-1 text-center text-[10.5px] text-[#66756c]">
                  L{sliderLevel}
                </span>
              </div>

              <div className="flex shrink-0 items-center gap-1 rounded-full border border-[#dce5df] bg-[#f7faf8] p-0.5">
                {(["rule-based", "embedding"] as const).map((provider) => {
                  const selected = settings.rankingProvider === provider;
                  return (
                    <button
                      key={provider}
                      type="button"
                      onClick={() => setRankingProvider(provider)}
                      className={cn(
                        "rounded-full px-2.5 py-1 text-[11px] font-[600] transition",
                        selected ? "bg-white text-[#227449] shadow-sm" : "text-[#6f8077] hover:text-[#31463a]"
                      )}
                    >
                      {provider === "rule-based" ? "Fast" : "Semantic"}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-3 lg:grid-cols-[minmax(320px,0.86fr)_minmax(460px,1.14fr)]">
          <div className="flex min-h-[390px] flex-col rounded-[14px] border border-[#e1e8e3] bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-[#eef2ef] px-4 py-3">
              <div>
                <div className="text-[13px] font-[600] text-[#32443a]">Input</div>
                <div className="text-[11px] text-[#86958c]">Paste or type text to paraphrase.</div>
              </div>
              <div className="flex items-center gap-3 text-[12.5px] text-[#7a8b82]">
                <button type="button" onClick={handlePaste} className="hover:text-[#2d4236]">Paste</button>
                <button
                  type="button"
                  onClick={() => (input ? handleClear() : setInput(SAMPLE_TEXT))}
                  className="underline decoration-dotted underline-offset-2 hover:text-[#2d4236]"
                >
                  {input ? "Clear" : "Example"}
                </button>
              </div>
            </div>

            <div className="relative flex-1">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Enter text to paraphrase…"
                className="h-full min-h-[320px] w-full resize-none bg-transparent px-4 py-4 text-[15px] leading-[1.72] text-[#24342c] outline-none placeholder-[#9aa8a0]"
                maxLength={10000}
              />
              {!input && (
                <div className="pointer-events-none absolute bottom-5 left-4 right-4 text-[12px] text-[#8e9f96]">
                  The output keeps real replacements clickable so you can tap and swap words after paraphrasing.
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-[#eef2ef] px-4 py-3">
              <div className="text-[12px] text-[#798982]">
                {inputWords} words · {inputSentences} sentences · {charCount}/10,000 chars
              </div>
              <button
                type="button"
                onClick={handleParaphrase}
                disabled={!input.trim() || isParaphrasing}
                className="rounded-full bg-[#499557] px-5 py-[9px] text-[13px] font-[600] text-white shadow-sm transition hover:bg-[#3d8450] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isParaphrasing ? "Paraphrasing…" : draftChanged ? "Update draft" : "Paraphrase"}
              </button>
            </div>
          </div>

          <div className="flex min-h-[390px] flex-col rounded-[14px] border border-[#e1e8e3] bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-[#eef2ef] px-4 py-3">
              <div>
                <div className="text-[13px] font-[600] text-[#2b7b4f]">Paraphrased</div>
                <div className="text-[11px] text-[#86958c]">
                  {hasPendingRewriteSettings && hasSubmitted
                    ? "Mode or strength changed. Press Paraphrase to apply it to this sentence."
                    : "Tap highlighted words to open compact synonym choices."}
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-1.5 text-[12px] text-[#6f8077]">
                <button type="button" onClick={handleCopy} className="rounded-full border border-transparent px-2 py-1 hover:border-[#d7e2da] hover:text-[#2f4337]">
                  {copied ? "Copied" : "Copy"}
                </button>
                <button type="button" onClick={handleParaphrase} className="rounded-full border border-transparent px-2 py-1 hover:border-[#d7e2da] hover:text-[#2f4337]">Rephrase</button>
              </div>
            </div>

            <div className="relative flex-1 overflow-auto px-4 py-4 text-[15px] leading-[1.74] text-[#24342c]">
              {!hasOutput && !isParaphrasing && (
                <div className="text-[#9aa9a0]">
                  Your paraphrased text will appear here after you press Paraphrase.
                </div>
              )}
              {isParaphrasing && (
                <div className="space-y-3 pr-6">
                  {[...Array(5)].map((_, index) => (
                    <div
                      key={index}
                      className="h-[14px] animate-pulse rounded-full bg-gradient-to-r from-[#eef5f0] via-[#dff0e4] to-[#eef5f0]"
                      style={{ width: `${92 - index * 10}%` }}
                    />
                  ))}
                  <div className="pt-2 text-[12.5px] text-[#73947f]">Rewriting with {activeMode.label} mode…</div>
                </div>
              )}
              {!isParaphrasing && hasOutput && (
                <OutputText
                  tokens={rewrite.tokens}
                  activeTokenId={activeTokenId}
                  onActivate={handleOpenToken}
                />
              )}
            </div>

            <div className="flex items-center justify-between border-t border-[#eef2ef] px-4 py-3 text-[12px] text-[#7d8d83]">
              <span>{hasOutput ? `${outputWords} words · ${outputSentences} sentences` : "0 words"}</span>
              <button
                type="button"
                onClick={handleCopy}
                className="rounded-full border border-[#d7e2da] px-3 py-[6px] text-[#476157] hover:bg-[#f5f9f6]"
              >
                {copied ? "Copied" : "Copy all"}
              </button>
            </div>
          </div>
        </section>

        <section className="mt-3 rounded-[14px] border border-[#e1e8e3] bg-white px-4 py-2.5 shadow-sm">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#687970]">
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
              {changedTokens.length} changed
            </span>
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
              {candidateTokens.length} swappable
            </span>
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
              Grammar {grammarScore}/100
            </span>
            <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
              {rewriteAssistantIds.length}-model rewrite stack
            </span>
            {freezeWordChips.length > 0 && (
              <span className="rounded-full border border-[#d7e2da] bg-[#f5f9f6] px-2.5 py-1">
                Protected: {freezeWordChips.slice(0, 4).join(", ")}
              </span>
            )}
          </div>
          {(showRewriteActivity || isBackgroundIndexing || isSemanticRefining || entityGuardError) && (
            <div className={cn("mt-2 text-[12px]", entityGuardError ? "inline-error rounded-md border px-2 py-1" : "text-[#6a8f77]")}>
              {entityGuardError
                ? entityGuardError
                : showRewriteActivity
                ? "Expanding contextual replacements with the fast local context model…"
                : isBackgroundIndexing
                ? "Indexing deeper local synonym matches toward 40 choices…"
                : isSemanticRefining
                ? "Refining word choices in the background…"
                : null}
            </div>
          )}
        </section>
      </main>

      {activeToken && anchorRect && typeof document !== "undefined"
        ? createPortal(
            <AlternativesPopover
              token={activeToken}
              rankingState={rankingState}
              modelInfo={modelInfo}
              style={popoverStyle(anchorRect)}
              onPick={handlePickAlternative}
              onRevertSentence={handleRevertSentence}
              canRevertSentence={activeSentenceCanRevert}
              onClose={closeTokenTools}
              popoverRef={popoverRef}
            />,
            document.body
          )
        : null}
    </div>
  );
}
