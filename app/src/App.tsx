import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { countSentences, getSentenceForRange, splitSentences } from "@/lib/nlp/sentenceSplit";
import { countWords, normalizeWord, tokenize } from "@/lib/nlp/tokenizer";
import { analyzeGrammar, mergeGrammarIssues, type GrammarIssue } from "@/lib/nlp/grammar";
import { analyzeHarperGrammar } from "@/lib/nlp/harper";
import { rankCandidatesByRule } from "@/lib/ranking/ruleBasedRanker";
import type { CandidateOption, RankingResult } from "@/lib/ranking/types";
import { rewriteText } from "@/lib/phraseEngine/rewriteText";
import type { RewriteResult, RewriteToken } from "@/lib/phraseEngine/types";
import { clamp, MODE_OPTIONS, percentToStrengthLevel, strengthLabel } from "@/lib/phraseEngine/rules";
import { generateLocalParaphrase } from "@/lib/generation/localParaphrase";
import {
  generateAdvancedAlternatives,
  MAX_VISIBLE_SYNONYMS,
} from "@/lib/rewriteStack/advancedParaphrase";
import type { LocalModelFailure } from "@/lib/rewriteStack/modelManager";
import {
  createEmptyPreferenceMemory,
  learnFromApproval,
  rankCandidatesByMemory,
  type ApprovedExample,
  type PreferenceMemory,
} from "@/lib/personalization/approvalMemory";
import {
  appendGroupedEdit,
  describeTextEdit,
  type ParaphraseSession,
  type TextEditMetadata,
} from "@/lib/personalization/editHistory";
import { loadApprovalState, persistApproval, usesNativePersistence } from "@/lib/persistence/approvalStore";
import { loadCustomStyles } from "@/lib/persistence/styleStore";
import {
  hashText,
  serializeProtectedSpans,
  validateProtectedContent,
} from "@/lib/safety/protectedContent";
import { readClipboardText, writeClipboardText } from "@/lib/platform/nativeClipboard";
import { applyTheme, loadSettings, saveSettings, type AppSettings } from "@/lib/settings/settingsStore";
import {
  customModeForStyle,
  customStyleIdFromMode,
  effectiveStyleStrength,
  engineModeForStyle,
  type CustomStyle,
} from "@/lib/styles/customStyles";
import type { AppMode } from "@/lib/types";
import { cn } from "@/utils/cn";

const SAMPLE_TEXT =
  "Artificial intelligence is changing the way people work and learn. It can help students improve their writing, find new ideas quickly, and understand difficult topics. Many companies use these powerful tools to make their work more efficient.";

const SYNONYM_LIMIT = MAX_VISIBLE_SYNONYMS;
const INLINE_WORD_TOOL_STOP_WORDS = new Set([
  "a", "about", "after", "again", "also", "an", "and", "are", "as", "been", "before", "being", "between", "both",
  "can", "could", "does", "each", "for", "from", "have", "if", "in", "into", "is", "it", "just", "more", "most", "much", "must", "of", "on", "only", "or",
  "other", "over", "same", "should", "some", "such", "than", "that", "the", "their", "them", "there", "these",
  "they", "this", "those", "through", "to", "under", "very", "was", "were", "which", "while", "with", "will", "would", "you", "your",
]);

function hasInlineWordTool(token: RewriteToken): boolean {
  const normalized = normalizeWord(token.text);
  if (!token.isWord || token.frozen || INLINE_WORD_TOOL_STOP_WORDS.has(normalized)) return false;
  return token.alternatives.length > 0 || normalized.length >= 4;
}

function popoverStyle(anchorRect: DOMRect | null): CSSProperties {
  if (!anchorRect || typeof window === "undefined") return { opacity: 0 };

  const width = Math.min(300, Math.max(260, window.innerWidth - 32));
  const left = Math.min(
    window.innerWidth - width - 16,
    Math.max(16, anchorRect.left + anchorRect.width / 2 - width / 2)
  );
  const estimatedHeight = 340;
  const top =
    anchorRect.bottom + estimatedHeight + 12 <= window.innerHeight
      ? anchorRect.bottom + 8
      : Math.max(12, anchorRect.top - estimatedHeight - 8);

  return {
    position: "fixed",
    top,
    left,
    width,
    maxHeight: Math.max(250, window.innerHeight - 24),
  };
}

function buildChangedTokenIds(originalText: string, currentText: string, result: RewriteResult): Set<string> {
  const originalWords = tokenize(originalText).filter((token) => token.type === "word");
  const currentWords = tokenize(currentText).filter((token) => token.type === "word");
  const matchedCurrentWords = new Set<number>();
  let originalCursor = 0;

  for (let currentIndex = 0; currentIndex < currentWords.length; currentIndex += 1) {
    const currentWord = normalizeWord(currentWords[currentIndex].text);
    const matchIndex = originalWords.findIndex(
      (word, index) => index >= originalCursor && normalizeWord(word.text) === currentWord
    );
    if (matchIndex < 0) continue;
    matchedCurrentWords.add(currentIndex);
    originalCursor = matchIndex + 1;
  }

  const changedIds = new Set<string>();
  for (const token of result.tokens) {
    if (!token.isWord || token.frozen) continue;
    const overlapsChangedWord = currentWords.some((word, index) =>
      word.start >= token.start && word.end <= token.end && !matchedCurrentWords.has(index)
    );
    if (overlapsChangedWord) changedIds.add(token.id);
  }
  return changedIds;
}

function getEditorText(element: HTMLDivElement): string {
  return (element.innerText || element.textContent || "").replace(/\u00a0/g, " ");
}

function renderInlineEditorContent(
  element: HTMLDivElement,
  result: RewriteResult,
  changedTokenIds: Set<string>,
  grammarWarningTokenIds: Set<string>,
  grammarWarningMessages: Map<string, string>,
  activeTokenId: string | null
): void {
  const fragment = document.createDocumentFragment();

  for (const token of result.tokens) {
    const clickable = hasInlineWordTool(token);
    const changed = changedTokenIds.has(token.id);
    const grammarWarning = grammarWarningTokenIds.has(token.id);
    if (!clickable && !changed && !grammarWarning) {
      fragment.appendChild(document.createTextNode(token.text));
      continue;
    }

    const span = document.createElement("span");
    span.textContent = token.text;
    span.className = cn(
      "inline-token",
      clickable && "inline-token-candidate",
      changed && "inline-token-changed",
      grammarWarning && "inline-token-warning",
      activeTokenId === token.id && "inline-token-active"
    );
    // Tokens are interactive spans inside the editor's single editing host.
    // Marking each one contentEditable made every token its own editing host.
    // Nested editing hosts are not supported in WebKit — the engine this app
    // ships in — and in the browser the host swallowed Enter before it reached
    // the popover, which left the word tools keyboard-inoperable.
    span.contentEditable = "false";
    span.dataset.tokenState = grammarWarning ? "warning" : changed ? "changed" : clickable ? "candidate" : "text";
    if (grammarWarning) {
      span.dataset.grammarWarningToken = token.id;
      span.title = grammarWarningMessages.get(token.id) ?? "Review this grammar or flow note.";
    }
    if (clickable) {
      span.dataset.inlineToken = token.id;
      span.setAttribute("role", "button");
      span.setAttribute("tabindex", "0");
      span.setAttribute("aria-haspopup", "dialog");
      span.setAttribute("aria-expanded", activeTokenId === token.id ? "true" : "false");
      span.setAttribute("aria-controls", "synonym-popover");
      span.setAttribute("aria-label", `Choose a synonym for ${token.text}`);
    }
    fragment.appendChild(span);
  }

  element.replaceChildren(fragment);
}

const InlineRewriteEditor = memo(function InlineRewriteEditor({
  editorRef,
  result,
  text,
  originalText,
  grammarIssues,
  activeTokenId,
  onActivate,
  onAnchorChange,
  onChange,
  onPaste,
}: {
  editorRef: RefObject<HTMLDivElement | null>;
  result: RewriteResult;
  text: string;
  originalText: string;
  grammarIssues: GrammarIssue[];
  activeTokenId: string | null;
  onActivate: (tokenId: string, element: HTMLElement) => void;
  onAnchorChange: (element: HTMLElement | null) => void;
  onChange: (value: string) => void;
  onPaste: () => void;
}) {
  const changedTokenIds = useMemo(
    () => buildChangedTokenIds(originalText, text, result),
    [originalText, result, text]
  );
  const grammarWarningTokenIds = useMemo(() => {
    const ids = new Set<string>();
    for (const issue of grammarIssues) {
      if (typeof issue.start !== "number" || typeof issue.end !== "number") continue;
      for (const token of result.tokens) {
        if (token.end > issue.start && token.start < issue.end) ids.add(token.id);
      }
    }
    return ids;
  }, [grammarIssues, result.tokens]);
  const grammarWarningMessages = useMemo(() => {
    const messages = new Map<string, string>();
    for (const issue of grammarIssues) {
      if (typeof issue.start !== "number" || typeof issue.end !== "number") continue;
      for (const token of result.tokens) {
        if (token.end > issue.start && token.start < issue.end && !messages.has(token.id)) {
          messages.set(token.id, `${issue.label}: ${issue.detail}`);
        }
      }
    }
    return messages;
  }, [grammarIssues, result.tokens]);

  useEffect(() => {
    const element = editorRef.current;
    if (!element) return;

    const renderedWarningIds = new Set(
      Array.from(element.querySelectorAll<HTMLElement>("[data-grammar-warning-token]"))
        .map((tokenElement) => tokenElement.dataset.grammarWarningToken)
        .filter((value): value is string => Boolean(value))
    );
    const warningMarkupMatches = renderedWarningIds.size === grammarWarningTokenIds.size &&
      [...renderedWarningIds].every((tokenId) => grammarWarningTokenIds.has(tokenId));
    if (getEditorText(element) !== text || !warningMarkupMatches) {
      renderInlineEditorContent(element, result, changedTokenIds, grammarWarningTokenIds, grammarWarningMessages, activeTokenId);
      return;
    }

    element.querySelectorAll<HTMLElement>("[data-inline-token]").forEach((tokenElement) => {
      const tokenId = tokenElement.dataset.inlineToken;
      tokenElement.classList.toggle("inline-token-active", tokenId === activeTokenId);
      // Opening the popover changes only activeTokenId, so the text-match fast
      // path runs and aria-expanded was never refreshed: the word that opened it
      // kept announcing false, and the previously opened one kept announcing
      // true. Keep it in step here.
      tokenElement.setAttribute("aria-expanded", String(tokenId === activeTokenId));
      tokenElement.classList.toggle("inline-token-changed", tokenId ? changedTokenIds.has(tokenId) : false);
      tokenElement.classList.toggle("inline-token-warning", tokenId ? grammarWarningTokenIds.has(tokenId) : false);
      if (tokenId && grammarWarningTokenIds.has(tokenId)) {
        tokenElement.title = grammarWarningMessages.get(tokenId) ?? "Review this grammar or flow note.";
      }
    });
  }, [activeTokenId, changedTokenIds, editorRef, grammarWarningMessages, grammarWarningTokenIds, result, text]);

  useEffect(() => {
    const element = editorRef.current;
    if (!element || !activeTokenId) {
      onAnchorChange(null);
      return;
    }

    const activeElement = Array.from(element.querySelectorAll<HTMLElement>("[data-inline-token]"))
      .find((tokenElement) => tokenElement.dataset.inlineToken === activeTokenId) ?? null;
    onAnchorChange(activeElement);
  }, [activeTokenId, editorRef, onAnchorChange, result, text]);

  const handleInput = () => {
    const element = editorRef.current;
    if (element) onChange(getEditorText(element));
  };

  const activateFromEvent = (event: ReactMouseEvent<HTMLDivElement> | ReactKeyboardEvent<HTMLDivElement>) => {
    const target = event.target instanceof HTMLElement
      ? event.target.closest<HTMLElement>("[data-inline-token]")
      : null;
    const tokenId = target?.dataset.inlineToken;
    if (target && tokenId) onActivate(tokenId, target);
  };

  return (
    <div
      ref={editorRef}
      contentEditable
      role="textbox"
      aria-multiline="true"
      aria-label="Editable paraphrased text with inline word tools"
      className="inline-editor"
      onInput={handleInput}
      onPaste={onPaste}
      onClick={activateFromEvent}
      onKeyDown={(event) => {
        // Space must stay available: this is the primary editing surface and a
        // textbox has to accept it. Enter activates the token.
        if (event.key !== "Enter") return;
        // Each token is its own contenteditable host, so the key event can land
        // on the token or bubble from the parent. Resolve either way, and fall
        // back to the focused element.
        const fromEvent = event.target instanceof HTMLElement
          ? event.target.closest<HTMLElement>("[data-inline-token]")
          : null;
        const target =
          fromEvent ??
          (document.activeElement instanceof HTMLElement
            ? document.activeElement.closest<HTMLElement>("[data-inline-token]")
            : null);
        if (!target?.dataset.inlineToken) return;
        event.preventDefault();
        onActivate(target.dataset.inlineToken, target);
      }}
      spellCheck
      suppressContentEditableWarning
    />
  );
});

function SynonymPopover({
  token,
  results,
  style,
  onSelect,
  onRevertWord,
  onRevertSentence,
  onCopySentence,
  canRevertSentence,
  loadingAlternatives,
  onClose,
}: {
  token: RewriteToken;
  results: RankingResult[];
  style: CSSProperties;
  onSelect: (replacement: string | null) => void;
  onRevertWord: () => void;
  onRevertSentence: () => void;
  onCopySentence: () => void;
  canRevertSentence: boolean;
  loadingAlternatives: boolean;
  onClose: () => void;
}) {
  return (
    <div
      data-popover="true"
      data-testid="synonym-popover"
      id="synonym-popover"
      role="dialog"
      aria-modal="false"
      aria-label={`Local word choices for ${token.text}`}
      style={style}
      className="synonym-popover z-50 max-h-[360px] overflow-hidden shadow-xl animate-fade-in"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="synonym-header flex items-start justify-between gap-3 px-3.5 py-3">
        <div className="min-w-0">
          <div className="synonym-eyebrow text-[10px] font-semibold uppercase tracking-[0.16em]">Local choices</div>
          <div className="synonym-title mt-0.5 truncate text-[15px] font-semibold">{token.text}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="ghost-button rounded-full px-2.5 py-1 text-[11px]"
          aria-label="Close word choices"
        >
          Close
        </button>
      </div>

      <div className="synonym-list max-h-[248px] overflow-auto px-2 py-2">
        <button
          type="button"
          onClick={() => onSelect(null)}
          className="synonym-original mb-1.5 flex w-full items-center justify-between rounded-[10px] px-3 py-2 text-left text-[12.5px] font-medium"
        >
          <span className="truncate">{token.originalText}</span>
          <span className="synonym-label ml-2 flex-none text-[10px]">Original</span>
        </button>

        {results.map((result) => (
          <button
            key={result.option.id}
            type="button"
            onClick={() => onSelect(result.option.replacement)}
            className="synonym-option flex w-full items-center justify-between rounded-[10px] px-3 py-2 text-left text-[12.5px]"
          >
            <span className="font-semibold">{result.option.replacement}</span>
            {result.option.label && <span className="synonym-label ml-2 flex-none text-[10px]">{result.option.label}</span>}
          </button>
        ))}

        {loadingAlternatives && (
          <div className="empty-note rounded-[10px] px-3 py-2 text-[11.5px]" aria-live="polite">
            Finding local context-aware alternatives…
          </div>
        )}
        {!loadingAlternatives && results.length === 0 && (
          <div className="empty-note rounded-[10px] px-3 py-2 text-[11.5px]">
            No safe local alternatives for this word.
          </div>
        )}
      </div>

      <div className="synonym-footer flex flex-wrap gap-1.5 px-2.5 py-2.5">
        <button
          type="button"
          onClick={onRevertWord}
          className="synonym-action rounded-full px-2.5 py-1 text-[10px]"
        >
          Revert word
        </button>
        {canRevertSentence && (
          <button
            type="button"
            onClick={onRevertSentence}
            className="synonym-action rounded-full px-2.5 py-1 text-[10px]"
          >
            Revert sentence
          </button>
        )}
        <button
          type="button"
          onClick={onCopySentence}
          className="synonym-action rounded-full px-2.5 py-1 text-[10px]"
        >
          Copy sentence
        </button>
      </div>
    </div>
  );
}

function replaceRange(text: string, start: number, end: number, replacement: string): string {
  return `${text.slice(0, start)}${replacement}${text.slice(end)}`;
}

function copyToClipboard(text: string): Promise<void> {
  if (!text.trim()) return Promise.resolve();
  return writeClipboardText(text);
}

function RewriteControls({
  mode,
  customStyles,
  savedPreferenceCount,
  onModeChange,
  strength,
  onStrengthChange,
  disabled,
}: {
  mode: AppSettings["mode"];
  customStyles: CustomStyle[];
  savedPreferenceCount: number;
  onModeChange: (mode: AppMode) => void;
  strength: number;
  onStrengthChange: (strength: number) => void;
  disabled: boolean;
}) {
  const normalizedStrength = clamp(Math.round(strength), 0, 100);
  const strengthLevel = percentToStrengthLevel(normalizedStrength);
  const options = [
    ...MODE_OPTIONS,
    ...customStyles.map((style) => ({
      value: customModeForStyle(style),
      label: style.name,
      hint: style.description || "Agent-created custom mode using Pari's shared engine",
    })),
  ];
  const selectedOption = options.find((option) => option.value === mode) ?? options[0];

  return (
    <div className="rewrite-controls">
      <div className="rewrite-controls-top">
        <div className="min-w-0">
          <div className="control-label">Rewrite style</div>
          <div className="control-hint">
            {selectedOption.hint}. {savedPreferenceCount > 0
              ? `Pari has learned from ${savedPreferenceCount} approved edit${savedPreferenceCount === 1 ? "" : "s"} on this device.`
              : "Pari learns from the edits you approve."}
          </div>
          <div className="mode-picker mt-2" role="radiogroup" aria-label="Rewrite style">
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={mode === option.value}
                className={cn("mode-option", mode === option.value && "is-selected")}
                onClick={() => onModeChange(option.value)}
                disabled={disabled}
                title={option.hint}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="strength-control">
          <div className="strength-heading">
            <span className="control-label">Rewrite amount</span>
            <span className="strength-value">{strengthLabel(normalizedStrength)}</span>
          </div>
          <div className="strength-meter" aria-hidden="true">
            {[1, 2, 3, 4].map((level) => (
              <span key={level} className={cn("strength-segment", level <= strengthLevel && "is-active")} />
            ))}
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={normalizedStrength}
            disabled={disabled}
            onInput={(event) => {
              onStrengthChange(clamp(Number(event.currentTarget.value), 0, 100));
            }}
            onChange={(event) => {
              onStrengthChange(clamp(Number(event.currentTarget.value), 0, 100));
            }}
            className="strength-range"
            aria-label="Rewrite amount"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={normalizedStrength}
            aria-valuetext={`${strengthLabel(normalizedStrength)} (${normalizedStrength}%)`}
            title="Drag to choose how much wording changes"
          />
        </div>
      </div>
    </div>
  );
}

function buildApprovedExample(
  session: ParaphraseSession,
  now: string
): ApprovedExample {
  const id = `approved-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    id,
    createdAt: now,
    originalText: session.originalText,
    finalText: session.currentEditedText,
    originalHash: hashText(session.originalText),
    finalHash: hashText(session.currentEditedText),
    protectedSpansSnapshot: session.protectedSpans,
    groupedEditSummary: session.groupedEditEvents.map((event, index) => ({
      ...event,
      id: `${id}-edit-${index + 1}`,
      approvedExampleId: id,
      sequence: index + 1,
    })),
    appVersion: "0.3.0",
    schemaVersion: 1,
  };
}

function ensureLiveEditEvent(
  session: ParaphraseSession,
  liveEditedText: string
): ParaphraseSession {
  if (liveEditedText === session.generatedText) return session;

  const generatedToLive = describeTextEdit(
    session.generatedText,
    liveEditedText,
    "typed",
    {},
    Date.now() - session.startedAt
  );
  const hasMatchingEvent = session.groupedEditEvents.some(
    (event) =>
      event.originalFragment === generatedToLive.originalFragment &&
      event.replacementFragment === generatedToLive.replacementFragment
  );
  if (hasMatchingEvent) return session;

  return {
    ...session,
    currentEditedText: liveEditedText,
    groupedEditEvents: appendGroupedEdit(session.groupedEditEvents, generatedToLive),
  };
}

export default function App() {
  const [input, setInput] = useState("");
  const [settings, setSettings] = useState<AppSettings>(() => loadSettings());
  const [session, setSession] = useState<ParaphraseSession | null>(null);
  const [approvedExamples, setApprovedExamples] = useState<ApprovedExample[]>([]);
  const [preferenceMemory, setPreferenceMemory] = useState<PreferenceMemory>(() => createEmptyPreferenceMemory());
  const [customStyles, setCustomStyles] = useState<CustomStyle[]>([]);
  const [customStylesLoaded, setCustomStylesLoaded] = useState(false);
  const [isLoadingMemory, setIsLoadingMemory] = useState(true);
  const [isParaphrasing, setIsParaphrasing] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [generationNotice, setGenerationNotice] = useState<string | null>(null);
  const [approvalMessage, setApprovalMessage] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [persistenceError, setPersistenceError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [activeTokenId, setActiveTokenId] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [contextualAlternatives, setContextualAlternatives] = useState<Record<string, CandidateOption[]>>({});
  const [contextualLoadingTokenId, setContextualLoadingTokenId] = useState<string | null>(null);
  const [harperIssues, setHarperIssues] = useState<GrammarIssue[]>([]);
  const [harperStatus, setHarperStatus] = useState<"idle" | "checking" | "ready" | "unavailable">("idle");

  const activeAnchorRef = useRef<HTMLElement | null>(null);
  const sessionRef = useRef<ParaphraseSession | null>(null);
  const requestIdRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const outputEditSourceRef = useRef<"typed" | "paste">("typed");
  const outputEditorRef = useRef<HTMLDivElement | null>(null);
  const contextualRequestRef = useRef(0);
  const strengthRegenerationTimerRef = useRef<number | null>(null);

  const clearStrengthRegeneration = () => {
    if (strengthRegenerationTimerRef.current === null) return;
    window.clearTimeout(strengthRegenerationTimerRef.current);
    strengthRegenerationTimerRef.current = null;
  };

  useEffect(() => {
    saveSettings(settings);
    applyTheme(settings.theme);
  }, [settings]);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const refreshCustomStyles = useCallback(async () => {
    try {
      setCustomStyles(await loadCustomStyles());
    } catch (error) {
      setPersistenceError(error instanceof Error ? error.message : String(error));
    } finally {
      setCustomStylesLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refreshCustomStyles();
    window.addEventListener("focus", refreshCustomStyles);
    return () => window.removeEventListener("focus", refreshCustomStyles);
  }, [refreshCustomStyles]);

  useEffect(() => {
    if (!customStylesLoaded || !customStyleIdFromMode(settings.mode)) return;
    if (!customStyles.some((style) => customModeForStyle(style) === settings.mode)) {
      setSettings((current) => ({ ...current, mode: "personal" }));
    }
  }, [customStyles, customStylesLoaded, settings.mode]);

  useEffect(() => {
    let mounted = true;
    void loadApprovalState()
      .then((state) => {
        if (!mounted) return;
        setApprovedExamples(state.examples);
        setPreferenceMemory(state.memory);
      })
      .catch((error) => {
        if (mounted) setPersistenceError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (mounted) setIsLoadingMemory(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("[data-inline-token]") || target?.closest("[data-popover='true']")) return;
      setActiveTokenId(null);
      activeAnchorRef.current = null;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeTokenTools();
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
      if (activeAnchorRef.current) setAnchorRect(activeAnchorRef.current.getBoundingClientRect());
    };
    refresh();
    window.addEventListener("resize", refresh);
    window.addEventListener("scroll", refresh, true);
    return () => {
      window.removeEventListener("resize", refresh);
      window.removeEventListener("scroll", refresh, true);
    };
  }, [activeTokenId]);

  useEffect(() => {
    const text = session?.currentEditedText.trim() ?? "";
    if (!text) {
      setHarperIssues([]);
      setHarperStatus("idle");
      return undefined;
    }

    let active = true;
    setHarperStatus("checking");
    const timer = window.setTimeout(() => {
      void analyzeHarperGrammar(text)
        .then((issues) => {
          if (!active) return;
          setHarperIssues(issues);
          setHarperStatus("ready");
        })
        .catch(() => {
          if (!active) return;
          setHarperIssues([]);
          setHarperStatus("unavailable");
        });
    }, 180);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [session?.currentEditedText]);

  const activeCustomStyle = useMemo(
    () => customStyles.find((style) => customModeForStyle(style) === settings.mode) ?? null,
    [customStyles, settings.mode]
  );
  const generationStyle = useMemo(
    () => activeCustomStyle ? { ...activeCustomStyle, strength: settings.strength } : null,
    [activeCustomStyle, settings.strength]
  );
  const engineMode = activeCustomStyle
    ? engineModeForStyle(generationStyle)
    : settings.mode === "warmth" ? "warmth" : "personal";
  const engineStrength = activeCustomStyle
    ? effectiveStyleStrength(generationStyle, settings.strength)
    : settings.strength;

  const preview = useMemo<RewriteResult | null>(() => {
    if (!session) return null;
    return rewriteText(
      session.currentEditedText,
      {
        mode: engineMode,
        strength: engineStrength,
        freezeWords: serializeProtectedSpans(session.protectedSpans),
        disableAutomaticRewrites: true,
      },
      {},
      contextualAlternatives
    );
  }, [contextualAlternatives, engineMode, engineStrength, session]);

  const grammarIssues = useMemo(
    () => session
      ? mergeGrammarIssues(analyzeGrammar(session.currentEditedText), harperIssues)
      : [],
    [harperIssues, session?.currentEditedText]
  );
  const grammarReviewCount = grammarIssues.filter((issue) => issue.severity !== "low").length;

  const activeToken = useMemo(
    () => preview?.tokens.find((token) => token.id === activeTokenId) ?? null,
    [activeTokenId, preview]
  );

  const activeResults = useMemo(() => {
    if (!activeToken) return [];
    const sentence = session
      ? getSentenceForRange(session.currentEditedText, activeToken.start, activeToken.end)
      : { text: activeToken.text, start: activeToken.start };
    const ranked = rankCandidatesByRule(activeToken.alternatives, {
      fullText: session?.currentEditedText ?? activeToken.text,
      sentence: sentence.text,
      selectedText: activeToken.text,
      mode: engineMode,
      strength: percentToStrengthLevel(engineStrength),
      freezeWords: [],
      partOfSpeech: activeToken.partOfSpeech,
      selectionStart: activeToken.start,
      selectionEnd: activeToken.end,
      sentenceStart: sentence.start,
    });
    return rankCandidatesByMemory(ranked, activeToken.originalText, preferenceMemory).slice(0, SYNONYM_LIMIT);
  }, [activeToken, engineMode, engineStrength, preferenceMemory, session?.currentEditedText]);

  const activeSentenceCanRevert = useMemo(() => {
    if (!activeToken || !session) return false;
    const currentSentence = getSentenceForRange(session.currentEditedText, activeToken.start, activeToken.end);
    const currentSentences = splitSentences(session.currentEditedText);
    const originalSentences = splitSentences(session.originalText);
    const sentenceIndex = currentSentences.findIndex(
      (sentence) => sentence.start === currentSentence.start && sentence.end === currentSentence.end
    );
    const originalSentence = sentenceIndex >= 0 ? originalSentences[sentenceIndex] : undefined;
    return Boolean(originalSentence && currentSentence.text !== originalSentence.text);
  }, [activeToken, session]);
  const canRevertParagraph = Boolean(session && session.currentEditedText !== session.generatedText);
  const hasDraft = input.trim().length > 0;
  const hasOutput = Boolean(session && preview);
  const inputWordCount = countWords(input);
  const inputSentenceCount = countSentences(input);
  const outputWordCount = session ? countWords(session.currentEditedText) : 0;
  const outputSentenceCount = session ? countSentences(session.currentEditedText) : 0;
  const activeMode = activeCustomStyle
    ? { value: settings.mode, label: activeCustomStyle.name, hint: activeCustomStyle.description || "Agent-created custom mode" }
    : MODE_OPTIONS.find((option) => option.value === settings.mode) ?? MODE_OPTIONS[0];

  // The draft on screen was produced by the style that was selected at the
  // time, not by whatever is selected now. Resolve the draft's own label so
  // the output panel never claims a style it did not use, and surface a
  // regeneration prompt when the controls have drifted away from the draft.
  const styleOptions = useMemo(
    () => [
      ...MODE_OPTIONS,
      ...customStyles.map((style) => ({
        value: customModeForStyle(style),
        label: style.name,
        hint: style.description || "Agent-created custom mode",
      })),
    ],
    [customStyles],
  );
  const labelForStyle = (value: string | undefined) =>
    styleOptions.find((option) => option.value === value)?.label ?? null;
  const draftStyle = session?.generationMetadata.mode;
  const draftStyleLabel = labelForStyle(draftStyle);
  const draftStrength = session?.generationMetadata.strength;
  const styleDrifted = Boolean(session) && draftStyle !== undefined && draftStyle !== settings.mode;
  const amountDrifted =
    Boolean(session) && draftStrength !== undefined && draftStrength !== clamp(Math.round(settings.strength), 0, 100);
  const draftDiffersFromControls = styleDrifted || amountDrifted;
  // A draft restored from an older build has no recorded style. Say so rather
  // than implying the current selection produced it.
  const draftStyleUnknown = Boolean(session) && draftStyle === undefined;

  // A fixed six-line placeholder misrepresents a one-line note and a long essay
  // equally. Shape the placeholder from the sentence count of the real input so
  // the wait looks like the work that is happening.
  const skeletonLineCount = useMemo(
    () => Math.min(10, Math.max(1, Math.ceil(inputSentenceCount / 2))),
    [inputSentenceCount],
  );
  const skeletonLineWidths = useMemo(
    () =>
      Array.from({ length: skeletonLineCount }, (_, index) => {
        // Deterministic taper: long lines with occasional short ones, so it does
        // not read as a perfectly regular comb.
        const base = 96 - index * 7;
        const shorten = index % 3 === 2 ? 18 : index % 4 === 3 ? 9 : 0;
        return `${Math.max(38, base - shorten)}%`;
      }),
    [skeletonLineCount],
  );

  const closeTokenTools = useCallback(() => {
    // Focus is the only positional cue a screen-reader user has, and the
    // popover is portalled to the end of the document. Without this, every
    // dismiss path (Close, Escape, choosing a synonym) unmounts the focused
    // element and drops focus to <body>, so the next Tab restarts at the top.
    const anchor = activeAnchorRef.current;
    setActiveTokenId(null);
    setAnchorRect(null);
    activeAnchorRef.current = null;
    if (anchor?.isConnected) anchor.focus();
  }, []);

  const applyEditedText = useCallback(
    (nextText: string, source: "typed" | "paste" | "synonym" | "revert" | "sentence_rephrase" = "typed", metadata: TextEditMetadata = {}) => {
      contextualRequestRef.current += 1;
      setContextualLoadingTokenId(null);
      setContextualAlternatives({});
      setSession((current) => {
        if (!current || current.currentEditedText === nextText) return current;
        const event = describeTextEdit(
          current.currentEditedText,
          nextText,
          source,
          metadata,
          Date.now() - current.startedAt
        );
        return {
          ...current,
          currentEditedText: nextText,
          groupedEditEvents: appendGroupedEdit(current.groupedEditEvents, event),
        };
      });
      setApprovalMessage(null);
      setApprovalError(null);
      setGenerationNotice(null);
    },
    []
  );

  const handleInputChange = (value: string) => {
    clearStrengthRegeneration();
    contextualRequestRef.current += 1;
    setContextualLoadingTokenId(null);
    setContextualAlternatives({});
    if (session) {
      controllerRef.current?.abort();
      requestIdRef.current += 1;
      setSession(null);
      closeTokenTools();
    }
    setInput(value);
    setApprovalMessage(null);
    setApprovalError(null);
    // Editing the source retires the draft, because the draft belongs to the
    // text it was made from. It used to happen with no message at all, so a
    // single stray keystroke silently destroyed the rewrite *and* every manual
    // correction and synonym swap in it, with nothing to recover from. Say so
    // explicitly, and say more when there was real editing to lose.
    setGenerationNotice(
      session && session.currentEditedText !== session.generatedText
        ? "Source text changed, so the draft and your edits to it were discarded. Press Paraphrase to work on the new text."
        : session
        ? "Source text changed, so the previous draft was discarded. Press Paraphrase to work on the new text."
        : null,
    );
  };

  const handleOpenToken = (tokenId: string, element: HTMLElement) => {
    const token = preview?.tokens.find((entry) => entry.id === tokenId);
    if (!token || !hasInlineWordTool(token) || !session) return;
    activeAnchorRef.current = element;
    setAnchorRect(element.getBoundingClientRect());
    setActiveTokenId(tokenId);

    if (token.alternatives.length >= SYNONYM_LIMIT || contextualAlternatives[tokenId]) return;

    const requestId = contextualRequestRef.current + 1;
    contextualRequestRef.current = requestId;
    setContextualLoadingTokenId(tokenId);
    setGenerationNotice("Finding more local alternatives for this word…");
    const modelFailures: LocalModelFailure[] = [];
    void generateAdvancedAlternatives(
      token,
      session.currentEditedText,
      engineMode,
      percentToStrengthLevel(engineStrength),
      {
        onModelFailure: (failure) => {
          if (!modelFailures.some((entry) => entry.modelId === failure.modelId)) {
            modelFailures.push(failure);
          }
        },
      }
    )
      .then((alternatives) => {
        if (contextualRequestRef.current !== requestId) return;
        setContextualAlternatives((current) => ({ ...current, [tokenId]: alternatives }));
        setContextualLoadingTokenId(null);
        if (modelFailures.length > 0) {
          const firstFailure = modelFailures[0];
          setGenerationNotice(
            alternatives.length > 0
              ? `${firstFailure.label} is unavailable. Built-in offline choices are still available. ${firstFailure.message}`
              : `No additional safe local alternatives were found for this word. ${firstFailure.message}`
          );
        } else {
          setGenerationNotice(alternatives.length > 0 ? "Local contextual alternatives are ready." : "No additional safe local alternatives were found.");
        }
      })
      .catch((error) => {
        if (contextualRequestRef.current !== requestId) return;
        setContextualLoadingTokenId(null);
        setGenerationNotice(error instanceof Error ? error.message : "Contextual alternatives were unavailable.");
      });
  };

  const handleParaphrase = async (strengthOverride?: number) => {
    if (!hasDraft) return;
    clearStrengthRegeneration();
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const originalText = input.trim();
    const requestedStrength = clamp(Math.round(strengthOverride ?? settings.strength), 0, 100);
    const requestedStyle = activeCustomStyle
      ? { ...activeCustomStyle, strength: requestedStrength }
      : null;
    const requestedMode = requestedStyle
      ? engineModeForStyle(requestedStyle)
      : settings.mode === "warmth" ? "warmth" : "personal";
    const requestedEngineStrength = requestedStyle
      ? effectiveStyleStrength(requestedStyle, requestedStrength)
      : requestedStrength;

    setIsParaphrasing(true);
    contextualRequestRef.current += 1;
    setContextualLoadingTokenId(null);
    setContextualAlternatives({});
    setGenerationNotice("Preparing the private on-device paraphraser…");
    setApprovalMessage(null);
    setApprovalError(null);
    closeTokenTools();

    try {
      const result = await generateLocalParaphrase({
        originalText,
        examples: approvedExamples,
        memory: preferenceMemory,
        mode: requestedMode,
        strength: requestedEngineStrength,
        style: requestedStyle ?? undefined,
        signal: controller.signal,
      });
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;
      setSession({
        startedAt: Date.now(),
        originalText,
        generatedText: result.text,
        currentEditedText: result.text,
        protectedSpans: result.protectedSpans,
        groupedEditEvents: [],
        generationMetadata: {
          source: result.source,
          durationMs: result.durationMs,
          retryCount: result.retryCount,
          retrievedExampleCount: result.retrievedExampleCount,
          safe: result.safe,
          notice: result.notice,
          mode: settings.mode,
          strength: requestedStrength,
        },
      });
      setGenerationNotice(result.notice ?? `Ready in ${result.durationMs} ms. Review the wording, then save it to teach Pari.`);
    } catch (error) {
      if (controller.signal.aborted || requestId !== requestIdRef.current) return;
      setGenerationNotice(error instanceof Error ? error.message : String(error));
      setSession(null);
    } finally {
      if (requestId === requestIdRef.current) setIsParaphrasing(false);
    }
  };

  const handleStrengthChange = (nextStrength: number) => {
    const normalizedStrength = clamp(Math.round(nextStrength), 0, 100);
    setSettings((current) => ({ ...current, strength: normalizedStrength }));

    if (!session || isParaphrasing) {
      setGenerationNotice(null);
      return;
    }

    clearStrengthRegeneration();
    if (session.currentEditedText !== session.generatedText) {
      setGenerationNotice(
        `Rewrite amount set to ${strengthLabel(normalizedStrength)}. Press Paraphrase to apply it without replacing your manual edits.`
      );
      return;
    }

    setGenerationNotice(`Rewriting at ${strengthLabel(normalizedStrength)}…`);
    strengthRegenerationTimerRef.current = window.setTimeout(() => {
      strengthRegenerationTimerRef.current = null;
      void handleParaphrase(normalizedStrength);
    }, 450);
  };

  const handleCancel = () => {
    clearStrengthRegeneration();
    controllerRef.current?.abort();
    requestIdRef.current += 1;
    setIsParaphrasing(false);
    setGenerationNotice("Paraphrase cancelled. Nothing was saved.");
  };

  const handleCopy = async (text = session?.currentEditedText ?? "") => {
    try {
      await copyToClipboard(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setApprovalError("Copy is unavailable in this environment.");
    }
  };

  const handleSelectSynonym = (replacement: string | null) => {
    if (!activeToken || !session) return;
    const nextText = replaceRange(
      session.currentEditedText,
      activeToken.start,
      activeToken.end,
      replacement ?? activeToken.originalText
    );
    applyEditedText(nextText, replacement === null ? "revert" : "synonym", {
      type: replacement === null ? "word-revert" : "synonym-replacement",
      originalFragment: activeToken.originalText,
      replacementFragment: replacement ?? activeToken.originalText,
    });
    closeTokenTools();
  };

  const handleRevertWord = () => handleSelectSynonym(null);

  const handleRevertSentence = () => {
    if (!activeToken || !session) return;
    const currentSentence = getSentenceForRange(session.currentEditedText, activeToken.start, activeToken.end);
    const currentSentences = splitSentences(session.currentEditedText);
    const originalSentences = splitSentences(session.originalText);
    const sentenceIndex = currentSentences.findIndex(
      (sentence) => sentence.start === currentSentence.start && sentence.end === currentSentence.end
    );
    const originalSentence = sentenceIndex >= 0 ? originalSentences[sentenceIndex] : undefined;
    if (!originalSentence || currentSentence.text === originalSentence.text) return;
    const nextText = replaceRange(
      session.currentEditedText,
      currentSentence.start,
      currentSentence.end,
      originalSentence.text
    );
    applyEditedText(nextText, "revert", { type: "sentence-revert" });
    closeTokenTools();
  };

  const handleRevertParagraph = () => {
    if (!session) return;
    applyEditedText(session.generatedText, "revert", {
      type: "paragraph-revert",
      originalFragment: session.currentEditedText,
      replacementFragment: session.generatedText,
    });
  };

  const handleCopySentence = () => {
    if (!activeToken || !session) return;
    const sentence = getSentenceForRange(session.currentEditedText, activeToken.start, activeToken.end);
    void handleCopy(sentence.text);
  };

  const handleApprove = async () => {
    if (!session || isApproving) return;
    clearStrengthRegeneration();
    // Read the live editor once more at the approval boundary. This keeps a
    // direct contenteditable edit from being lost if a browser/WebView input
    // event arrives between the last React state update and Save & learn.
    const liveEditedText = outputEditorRef.current
      ? getEditorText(outputEditorRef.current)
      : session.currentEditedText;
    const approvalSession = liveEditedText === session.currentEditedText
      ? session
      : {
          ...session,
          currentEditedText: liveEditedText,
          groupedEditEvents: [
            ...session.groupedEditEvents,
            describeTextEdit(
              session.currentEditedText,
              liveEditedText,
              "typed",
              {},
              Date.now() - session.startedAt
            ),
          ],
        };
    const finalApprovalSession = ensureLiveEditEvent(approvalSession, liveEditedText);
    const validation = validateProtectedContent(finalApprovalSession.originalText, finalApprovalSession.currentEditedText, finalApprovalSession.protectedSpans);
    if (!validation.safe) {
      setApprovalError(validation.reason ?? "Links, names, and numbers must remain unchanged before saving.");
      return;
    }

    const record = buildApprovedExample(finalApprovalSession, new Date().toISOString());
    const nextMemory = learnFromApproval(preferenceMemory, record);
    setPersistenceError(null);
    setIsApproving(true);
    try {
      const nextState = await persistApproval(record, nextMemory);
      setApprovedExamples(nextState.examples);
      setPreferenceMemory(nextState.memory);
      setSession(null);
      closeTokenTools();
      setApprovalMessage("Saved locally. Pari will use this preference in future rewrites.");
      setGenerationNotice(null);
      setApprovalError(null);
    } catch (error) {
      setPersistenceError(error instanceof Error ? error.message : String(error));
      setApprovalError("Approval was not saved. Your draft is still here; try again.");
    } finally {
      setIsApproving(false);
    }
  };

  const handleDiscard = () => {
    clearStrengthRegeneration();
    controllerRef.current?.abort();
    requestIdRef.current += 1;
    setIsParaphrasing(false);
    setSession(null);
    contextualRequestRef.current += 1;
    setContextualLoadingTokenId(null);
    setContextualAlternatives({});
    closeTokenTools();
    setApprovalError(null);
    setGenerationNotice("Draft discarded. Nothing was saved or learned.");
    setApprovalMessage(null);
  };

  const handlePasteOutput = () => {
    outputEditSourceRef.current = "paste";
  };

  const storageLabel = usesNativePersistence() ? "Private app storage" : "Private local storage";
  const setTheme = (theme: AppSettings["theme"]) => {
    setSettings((current) => (current.theme === theme ? current : { ...current, theme }));
  };

  return (
    <div className="app-shell min-h-[100dvh] antialiased">
      <a href="#workspace" className="skip-link">Skip to workspace</a>
      <header className="app-header sticky top-0 z-40 backdrop-blur">
        <div className="app-header-inner mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div className="brand-mark flex h-[36px] w-[36px] flex-none items-center justify-center rounded-[11px] text-[17px]">P</div>
            <div className="min-w-0">
              <div className="brand-name text-[20px] font-[700]">Pari</div>
              <div className="brand-sub text-[12px]">Local paraphrasing tool</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            {isLoadingMemory ? (
              <span className="muted-text">Loading preferences…</span>
            ) : (
              <span className="status-badge" title={`${storageLabel}. Nothing leaves this Mac unless you explicitly choose an online route.`}>
                <span className="status-dot" aria-hidden="true" />
                {storageLabel}
              </span>
            )}
            <div className="theme-segmented" role="group" aria-label="Color theme">
              {(["light", "dark", "system"] as const).map((theme) => (
                <button
                  key={theme}
                  type="button"
                  className={cn("theme-seg-btn", settings.theme === theme && "is-active")}
                  aria-pressed={settings.theme === theme}
                  onClick={() => setTheme(theme)}
                  title={theme === "system" ? "Follow system appearance" : `Use ${theme} mode`}
                >
                  {theme === "light" ? "Light" : theme === "dark" ? "Dark" : "Auto"}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main id="workspace" tabIndex={-1} className="mx-auto max-w-[1240px] scroll-mt-20 px-3 py-4 outline-none sm:px-5 sm:py-5 lg:px-8">
        {/* A live region only announces changes to an element already in the
            accessibility tree. Every status message in the app was mounted
            together with its own text, so the first message after an idle
            period — including "Preparing the private on-device paraphraser…"
            when Paraphrase is pressed — was never announced. These two regions
            are always present; the visible notices stay presentational. */}
        <div role="status" aria-live="polite" className="sr-only">
          {generationNotice ?? approvalMessage ?? ""}
        </div>
        <div role="alert" aria-live="assertive" className="sr-only">
          {approvalError ?? persistenceError ?? ""}
        </div>
        <section className="intro-card mb-4 rounded-[18px] px-4 py-3.5 sm:px-5" aria-label="Rewrite settings">
          <RewriteControls
            mode={settings.mode}
            customStyles={customStyles}
            savedPreferenceCount={approvedExamples.length}
            onModeChange={(mode) => {
              const selectedStyle = customStyles.find((style) => customModeForStyle(style) === mode);
              setSettings((current) => ({
                ...current,
                mode,
                strength: selectedStyle?.strength ?? current.strength,
              }));
              setContextualAlternatives({});
              setGenerationNotice(null);
            }}
            strength={settings.strength}
            onStrengthChange={handleStrengthChange}
            disabled={isParaphrasing}
          />
        </section>

        <section className="grid items-stretch gap-4 lg:grid-cols-[minmax(320px,0.92fr)_minmax(460px,1.08fr)]" aria-label="Paraphrase workspace">
          <div className="app-panel workspace-panel-a flex min-h-[320px] flex-col rounded-[18px]">
            <div className="panel-header flex items-start justify-between gap-3 px-4 py-3 sm:px-5">
              <div className="min-w-0">
                <div className="panel-title text-[13.5px] font-[650]">Original text</div>
                <div className="panel-sub mt-0.5 text-[12px] leading-relaxed">Paste or type the paragraph you want to reshape.</div>
              </div>
              <div className="flex flex-none items-center gap-1.5 text-[12px]">
                <button type="button" onClick={async () => {
                  try { const text = await readClipboardText(); if (text) handleInputChange(text); }
                  catch { setApprovalError("Paste is unavailable in this environment."); }
                }} className="text-action px-2.5 py-1">Paste</button>
                <button type="button" onClick={() => handleInputChange(input ? "" : SAMPLE_TEXT)} className="text-action px-2.5 py-1 underline decoration-dotted underline-offset-2">
                  {input ? "Clear" : "Example"}
                </button>
              </div>
            </div>

            <textarea
              value={input}
              onChange={(event) => handleInputChange(event.target.value)}
              placeholder="Paste text to paraphrase…"
              maxLength={10000}
              className="input-editor min-h-[220px] flex-1 resize-none text-[15px] leading-[1.72] outline-none"
              aria-label="Original text"
            />

            <div className="panel-footer flex items-center justify-between gap-3 px-4 py-3 sm:px-5">
              <div className="muted-text count-num text-[12px]">{inputWordCount} words · {inputSentenceCount} sentences</div>
              <button
                type="button"
                onClick={isParaphrasing ? handleCancel : () => { void handleParaphrase(); }}
                disabled={!hasDraft && !isParaphrasing}
                className="primary-button rounded-full px-5 py-[9px] text-[13px] font-[650] transition"
              >
                {isParaphrasing ? "Cancel" : "Paraphrase"}
              </button>
            </div>
          </div>

          <div
            className="app-panel workspace-panel-b flex min-h-[320px] flex-col rounded-[18px]"
            data-generation-source={session?.generationMetadata.source ?? ""}
          >
            <div className="panel-header flex items-start justify-between gap-3 px-4 py-3 sm:px-5">
              <div className="min-w-0">
                <div className="panel-title accent-text text-[13.5px] font-[650]">
                  {draftStyleLabel ? `Your ${draftStyleLabel} rewrite` : "Your rewrite"}
                </div>
                <div className="panel-sub mt-0.5 text-[12px] leading-relaxed">Edit directly, or select a highlighted word for local choices.</div>
                {draftDiffersFromControls && (
                  <div className="draft-drift mt-2" role="status">
                    <span className="draft-drift-text">
                      {styleDrifted
                        ? `Drafted in ${draftStyleLabel ?? "another style"}; ${activeMode.label} is now selected.`
                        : `Drafted at ${strengthLabel(clamp(Math.round(draftStrength ?? 0), 0, 100))}; ${strengthLabel(clamp(Math.round(settings.strength), 0, 100))} is now selected.`}
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleParaphrase()}
                      disabled={isParaphrasing}
                      className="draft-drift-action"
                    >
                      Rewrite with {activeMode.label}
                    </button>
                  </div>
                )}
                {draftStyleUnknown && !draftDiffersFromControls && (
                  <div className="draft-drift-text mt-2">
                    This draft was created before Pari recorded its style, so its origin is unknown.
                  </div>
                )}
                {(session || isParaphrasing) && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-live="polite">
                    <span className={cn("quality-chip", grammarReviewCount > 0 && "quality-chip-warning")}>
                      {harperStatus === "checking"
                        ? "Checking grammar locally…"
                        : grammarReviewCount > 0
                        ? `${grammarReviewCount} grammar or flow note${grammarReviewCount === 1 ? "" : "s"}`
                        : harperStatus === "unavailable" ? "Built-in grammar rules" : "Grammar checked"}
                    </span>
                    {grammarIssues.some((issue) => typeof issue.start === "number") && (
                      <span className="muted-text text-[10.5px]">Underlined text has a review note.</span>
                    )}
                  </div>
                )}
                {hasOutput && (
                  <div className="quality-legend mt-2" data-testid="quality-legend" aria-label="Rewrite highlighting key">
                    <span className="legend-item"><span className="legend-swatch legend-swatch-changed" aria-hidden="true" /> Changed wording</span>
                    <span className="legend-item"><span className="legend-swatch legend-swatch-choice" aria-hidden="true" /> Local word choices</span>
                    <span className="legend-item"><span className="legend-swatch legend-swatch-warning" aria-hidden="true" /> Grammar or flow note</span>
                  </div>
                )}
                {(generationNotice || approvalMessage || approvalError || persistenceError) && (
                  <div className={cn("notice mt-2.5 rounded-[12px] border px-3 py-2 text-[12.5px] leading-relaxed", approvalError || persistenceError ? "notice-error" : "notice-success")} aria-live="polite">
                    {approvalError ?? persistenceError ?? approvalMessage ?? generationNotice}
                  </div>
                )}
              </div>
              <button type="button" onClick={() => void handleCopy()} disabled={!hasOutput} className="text-action flex-none rounded-full px-2.5 py-1 text-[12px]">
                {copied ? "Copied" : "Copy"}
              </button>
            </div>

            <div className="flex-1 overflow-auto px-4 py-4 sm:px-5">
              {!hasOutput && !isParaphrasing && (
                <div className="empty-editor flex gap-3 rounded-[14px] px-4 py-5 text-[13px] leading-6">
                  <span className="empty-icon" aria-hidden="true">
                    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                      <path d="M2.5 4.5h11" />
                      <path d="M2.5 8h7" />
                      <path d="M2.5 11.5h9" />
                      <path d="M11.6 7.2l1.9 1.9 2.6-2.9" strokeWidth="1.5" />
                    </svg>
                  </span>
                  <span>Your {activeMode.label} rewrite will appear here after you paraphrase. Select any highlighted word to see local alternatives.</span>
                </div>
              )}
              {isParaphrasing && (
                <div className="space-y-3 pr-4" aria-live="polite">
                  {skeletonLineCount > 0 ? (
                    Array.from({ length: skeletonLineCount }, (_, index) => (
                      <div
                        key={index}
                        className="skeleton-line h-[14px] rounded-full"
                        style={{ width: skeletonLineWidths[index] }}
                      />
                    ))
                  ) : (
                    <div className="skeleton-line h-[14px] w-[62%] rounded-full" />
                  )}
                  <div className="muted-text pt-2 text-[12px]">Keeping the editor responsive while the local draft is prepared…</div>
                </div>
              )}
              {!isParaphrasing && session && preview && (
                <InlineRewriteEditor
                  editorRef={outputEditorRef}
                  result={preview}
                  text={session.currentEditedText}
                  originalText={session.originalText}
                  grammarIssues={grammarIssues}
                  activeTokenId={activeTokenId}
                  onActivate={handleOpenToken}
                  onAnchorChange={(element) => {
                    if (activeAnchorRef.current === element) return;
                    activeAnchorRef.current = element;
                    setAnchorRect(element?.getBoundingClientRect() ?? null);
                  }}
                  onChange={(value) => {
                    const source = outputEditSourceRef.current;
                    outputEditSourceRef.current = "typed";
                    applyEditedText(value, source);
                  }}
                  onPaste={handlePasteOutput}
                />
              )}
            </div>

            <div className="panel-footer flex flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-5">
              <div className="flex min-w-0 flex-wrap items-center gap-2 text-[12px]">
                <span className="muted-text count-num">{hasOutput ? `${outputWordCount} words · ${outputSentenceCount} sentences` : "No draft yet"}</span>
                {session && <span className="status-badge">Links, names, and numbers stay protected</span>}
              </div>
              <div className="flex items-center gap-2">
                {session && (
                  <button type="button" onClick={handleRevertParagraph} disabled={!canRevertParagraph} className="secondary-button rounded-full px-3 py-[6px] text-[11.5px]">Revert edits</button>
                )}
                {session && (
                  <>
                    <button type="button" onClick={handleDiscard} className="secondary-button rounded-full px-3.5 py-[7px] text-[12px]">Discard</button>
                    <button type="button" onClick={() => void handleApprove()} disabled={isApproving} className="approve-button rounded-full px-4 py-[7px] text-[12px] font-[650]" aria-busy={isApproving}>{isApproving ? "Saving…" : "Save & learn"}</button>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* One closing statement, not two. The save/discard reassurance only
            matters before there is anything to save, and the privacy note
            applies the whole time, so they are merged into a single line
            instead of sitting stacked and saying adjacent things. */}
        <p className="muted-text mt-4 pb-6 text-center text-[11.5px]">
          {session
            ? `${storageLabel}. Nothing leaves this Mac unless you explicitly choose an online route.`
            : `${storageLabel}. Nothing leaves this Mac unless you explicitly choose an online route, and nothing is saved until you press Save & learn.`}
        </p>
      </main>

      {activeToken && anchorRect && typeof document !== "undefined"
        ? createPortal(
            <SynonymPopover
              token={activeToken}
              results={activeResults}
              style={popoverStyle(anchorRect)}
              onSelect={handleSelectSynonym}
              onRevertWord={handleRevertWord}
              onRevertSentence={handleRevertSentence}
              onCopySentence={handleCopySentence}
              canRevertSentence={activeSentenceCanRevert}
              loadingAlternatives={contextualLoadingTokenId === activeTokenId}
              onClose={closeTokenTools}
            />,
            document.body
          )
        : null}
    </div>
  );
}
