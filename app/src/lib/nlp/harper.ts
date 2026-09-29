import type { GrammarIssue } from "./grammar";

type HarperLinter = import("harper.js").Linter;

let linterPromise: Promise<HarperLinter> | null = null;

function severityForKind(kind: string): GrammarIssue["severity"] {
  if (/agreement|grammar|punctuation|typo|spelling|word order/i.test(kind)) return "high";
  if (/usage|word choice|capitalization|formatting|redundancy|repetition/i.test(kind)) return "medium";
  return "low";
}

function findProblemRange(text: string, start: number, end: number, problem: string): { start: number; end: number } {
  const direct = text.slice(start, end);
  if (direct === problem) return { start, end };

  const nearbyStart = Math.max(0, start - 32);
  const nearbyIndex = text.indexOf(problem, nearbyStart);
  if (nearbyIndex >= 0 && nearbyIndex <= end + 32) {
    return { start: nearbyIndex, end: nearbyIndex + problem.length };
  }

  return { start, end };
}

async function getLinter(): Promise<HarperLinter> {
  if (!linterPromise) {
    linterPromise = (async () => {
      const [{ LocalLinter }, { binaryInlined }] = await Promise.all([
        import("harper.js"),
        import("harper.js/binaryInlined"),
      ]);
      // harper.js starts `binary.setup()` from the LocalLinter constructor
      // without awaiting it. In WKWebView, a failed inline WASM load would
      // therefore leak an unhandled rejection even though our awaited linter
      // setup is caught by the caller and the built-in rules remain available.
      // Keep the constructor's fire-and-forget hook harmless; createLinter()
      // still performs the real, awaited binary load below.
      const guardedBinary = new Proxy(binaryInlined, {
        get(target, property, receiver) {
          if (property === "setup") return () => Promise.resolve();
          return Reflect.get(target, property, receiver);
        },
      });
      const linter = new LocalLinter({ binary: guardedBinary });
      await linter.setup();
      return linter;
    })();
  }

  return linterPromise;
}

export async function analyzeHarperGrammar(text: string): Promise<GrammarIssue[]> {
  const trimmed = text.trim();
  if (!trimmed) return [];

  const linter = await getLinter();
  const lints = await linter.lint(text, {
    language: "plaintext",
    dedup: true,
    isolateEnglish: true,
  });

  return lints.flatMap((lint, index) => {
    try {
      const span = lint.span();
      const problem = lint.get_problem_text();
      const range = findProblemRange(text, span.start, span.end, problem);
      const kind = lint.lint_kind_pretty() || lint.lint_kind() || "Grammar";
      const detail = lint.message() || "Review this wording.";
      span.free();

      return [{
        id: `harper-${lint.lint_kind()}-${range.start}-${range.end}-${index}`,
        severity: severityForKind(kind),
        label: kind,
        detail,
        sample: problem || undefined,
        start: range.start,
        end: range.end,
      }];
    } finally {
      lint.free();
    }
  });
}

export async function warmHarperGrammar(): Promise<void> {
  await getLinter();
}
