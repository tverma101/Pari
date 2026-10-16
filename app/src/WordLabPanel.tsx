import type { EditorSpanSelection } from "@/lib/editor/spanSelection";

export type WordLabView = "word" | "sentence";
export type WordLabTransformKind = "condense" | "one-word" | "same-length" | "academic";

export interface WordLabSentenceExample {
  id: string;
  replacement: string;
  label: string;
  sentence: string;
}

export interface WordLabTransformOption {
  id: string;
  label: string;
  replacement: string;
}

const TRANSFORM_CHOICES: ReadonlyArray<{ id: WordLabTransformKind; label: string }> = [
  { id: "condense", label: "Condense" },
  { id: "one-word", label: "Phrase → one word" },
  { id: "same-length", label: "Same length" },
  { id: "academic", label: "More academic" },
];

export function WordLabPanel({
  view,
  onViewChange,
  selection,
  wordExamples,
  transformKind,
  onTransformKindChange,
  transformOptions,
  onApplyWordExample,
  onApplyTransform,
  onClose,
}: {
  view: WordLabView;
  onViewChange: (view: WordLabView) => void;
  selection: EditorSpanSelection | null;
  wordExamples: WordLabSentenceExample[];
  transformKind: WordLabTransformKind;
  onTransformKindChange: (kind: WordLabTransformKind) => void;
  transformOptions: WordLabTransformOption[];
  onApplyWordExample: (replacement: string) => void;
  onApplyTransform: (option: WordLabTransformOption) => void;
  onClose: () => void;
}) {
  return (
    <aside className="word-lab-panel app-panel flex min-h-[320px] flex-col rounded-[18px]" aria-label="Word Lab">
      <div className="word-lab-header flex shrink-0 items-start justify-between gap-3 px-4 py-3">
        <div>
          <div className="panel-title accent-text text-[13.5px] font-[650]">Word Lab</div>
          <div className="panel-sub mt-0.5 text-[11.5px]">Explore a word or reshape a selected phrase.</div>
        </div>
        <button type="button" className="secondary-button rounded-full px-3 py-1.5 text-[11.5px]" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="word-lab-tabs flex shrink-0 gap-1.5 px-3 pb-3" role="tablist" aria-label="Word Lab tools">
        <button
          type="button"
          role="tab"
          aria-selected={view === "word"}
          className="word-lab-tab rounded-full px-2.5 py-1.5 text-[10.5px] font-[600]"
          onClick={() => onViewChange("word")}
        >
          Word → sentences
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "sentence"}
          className="word-lab-tab rounded-full px-2.5 py-1.5 text-[10.5px] font-[600]"
          onClick={() => onViewChange("sentence")}
        >
          Sentence → fewer words
        </button>
      </div>

      <div className="word-lab-content min-h-0 flex-1 overflow-auto px-3 pb-3">
        {view === "word" ? (
          <>
            {selection?.kind === "word" ? (
              <>
                <div className="word-lab-context mb-2 rounded-[10px] px-3 py-2">
                  <div className="word-lab-eyebrow text-[9.5px] font-semibold uppercase tracking-[0.12em]">Selected word</div>
                  <div className="mt-0.5 break-words text-[12.5px] font-semibold">{selection.text}</div>
                </div>
                <p className="word-lab-hint mb-2 text-[10.5px] leading-relaxed">
                  Each option keeps the sentence around this word so you can judge the fit in context.
                </p>
                {wordExamples.length > 0 ? (
                  <div className="space-y-2">
                    {wordExamples.map((example) => (
                      <article className="word-lab-card rounded-[11px] p-2.5" key={example.id}>
                        <div className="mb-1 flex items-center justify-between gap-2">
                          <span className="text-[11.5px] font-semibold">{example.replacement}</span>
                          <span className="word-lab-label text-[9.5px]">{example.label}</span>
                        </div>
                        <p className="word-lab-example text-[11px] leading-[1.55]">{example.sentence}</p>
                        <button
                          type="button"
                          className="word-lab-action mt-2 rounded-full px-2.5 py-1 text-[10.5px] font-[600]"
                          aria-label={`Use ${example.replacement} in my sentence`}
                          onClick={() => onApplyWordExample(example.replacement)}
                        >
                          Use in my sentence
                        </button>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="word-lab-empty rounded-[10px] px-3 py-3 text-[11px] leading-relaxed">
                    There are no safe essay-fit alternatives for this word in the current local set.
                  </p>
                )}
              </>
            ) : (
              <p className="word-lab-empty rounded-[10px] px-3 py-3 text-[11px] leading-relaxed">
                Choose a word in the essay to see sentence examples that keep this paragraph’s context.
              </p>
            )}
          </>
        ) : (
          <>
            {selection && selection.kind !== "word" ? (
              <>
                <div className="word-lab-context mb-2 rounded-[10px] px-3 py-2">
                  <div className="word-lab-eyebrow text-[9.5px] font-semibold uppercase tracking-[0.12em]">Selected text</div>
                  <p className="mt-0.5 text-[11px] leading-relaxed">{selection.text}</p>
                </div>
                <div className="word-lab-transform-tabs mb-2 flex flex-wrap gap-1" role="tablist" aria-label="Sentence transformations">
                  {TRANSFORM_CHOICES.map((choice) => (
                    <button
                      key={choice.id}
                      type="button"
                      role="tab"
                      aria-selected={transformKind === choice.id}
                      className="word-lab-transform rounded-full px-2 py-1 text-[9.5px] font-[600]"
                      onClick={() => onTransformKindChange(choice.id)}
                    >
                      {choice.label}
                    </button>
                  ))}
                </div>
                {transformOptions.length > 0 ? (
                  <div className="space-y-2">
                    {transformOptions.map((option) => (
                      <article className="word-lab-card rounded-[11px] p-2.5" key={option.id}>
                        <div className="word-lab-label mb-1 text-[9.5px]">{option.label}</div>
                        <p className="word-lab-example text-[11px] leading-[1.55]">{option.replacement}</p>
                        <button
                          type="button"
                          className="word-lab-action mt-2 rounded-full px-2.5 py-1 text-[10.5px] font-[600]"
                          onClick={() => onApplyTransform(option)}
                        >
                          Use this version
                        </button>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="word-lab-empty rounded-[10px] px-3 py-3 text-[11px] leading-relaxed">
                    No safe local option fits this transformation. Try a longer phrase or a different category.
                  </p>
                )}
              </>
            ) : (
              <p className="word-lab-empty rounded-[10px] px-3 py-3 text-[11px] leading-relaxed">
                Select a sentence or phrase in the essay to see local alternatives here.
              </p>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
