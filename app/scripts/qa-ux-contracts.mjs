// Contract checks for the editor/persistence/native surfaces that the rewrite
// QA suites never touch.
//
// Every fix in the recent adversarial rounds lived in App.tsx, index.css,
// nativeBridge.ts and approvalStore.ts, and none of it was covered by CI: the
// rewrite suites never import those files, so "19/19 green" said nothing about
// any of it. These assertions are narrow on purpose -- they guard the specific
// regressions that actually happened, not general code style.

import fs from "fs";
import path from "path";
import vm from "vm";
import ts from "typescript";

const ROOT = path.resolve(new URL("..", import.meta.url).pathname);
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

let failures = 0;
const check = (ok, label, detail) => {
  if (ok) {
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` -- ${detail}` : ""}`);
  }
};

// ---------------------------------------------------------------------------
// 1. isNativeBridgeUnavailable, executed for real.
//
// The bridge error is classified by a `code` property rather than by matching
// error text. Matching text silently swallowed genuine read failures whose
// message happened to contain "unavailable", and also swallowed the 2.5s bridge
// timeout, after which the app fell back to an empty store and claimed a clean
// slate. This regressed once already; assert the classifier directly.
// ---------------------------------------------------------------------------
{
  const source = read("src/lib/platform/nativeBridge.ts");
  const js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;

  // Strip the ESM export statements so the module can run inside a vm context.
  const body = js
    .replace(/^export\s+/gm, "")
    .replace(/\bexport\s*\{[^}]*\}\s*;?/g, "");

  const sandbox = { window: undefined, console, Promise, Error, Object, Boolean, String, Number, Date };
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  try {
    vm.runInContext(`${body}\nglobalThis.__probe = isNativeBridgeUnavailable;`, context, {
      filename: "nativeBridge.js",
    });
    const probe = sandbox.__probe;
    const coded = Object.assign(new Error("The native bridge is unavailable in this environment."), {
      code: "native-bridge-unavailable",
    });
    check(typeof probe === "function", "isNativeBridgeUnavailable is exported");
    check(probe(coded) === true, "a genuinely absent bridge is recognised");
    check(probe(new Error("The native bridge request timed out.")) === false, "a bridge timeout is NOT treated as absent");
    check(probe(new Error("storage unavailable on this Mac")) === false, "an unrelated 'unavailable' error is NOT treated as absent");
    check(probe(undefined) === false, "non-error values are not treated as absent");
  } catch (error) {
    check(false, "nativeBridge classifier executes", String(error).slice(0, 120));
  }
}

// ---------------------------------------------------------------------------
// 2. Badge cascade order.
//
// The unreadable-store badge was invisible twice: first because the warning
// rule preceded the base rule, then because the dark-theme rule outranked it.
// Both are pure source-order/specificity facts that a browser test caught late
// and CI never would.
// ---------------------------------------------------------------------------
{
  const css = read("src/index.css");
  const lines = css.split("\n");
  const indexOfRule = (pattern) => lines.findIndex((l) => pattern.test(l));
  const base = indexOfRule(/^\.status-badge \{/);
  const warn = indexOfRule(/^\.status-badge-warning \{/);
  check(base >= 0 && warn > base, "light warning rule follows the base badge rule", `base=${base} warn=${warn}`);

  const darkBase = indexOfRule(/^:root\[data-theme="dark"\] \.status-badge,/);
  const darkWarn = indexOfRule(/^:root\[data-theme="dark"\] \.status-badge-warning \{/);
  check(darkBase >= 0, "dark-theme badge rule exists");
  check(darkWarn > darkBase, "dark warning override follows the dark badge rule", `base=${darkBase} warn=${darkWarn}`);
  check(indexOfRule(/^\.status-badge-warning \.status-dot \{/) >= 0, "the green health dot is restyled in the warning state");

  // The dark override must actually set a background, otherwise it is a no-op.
  const darkBlock = lines.slice(darkWarn, darkWarn + 6).join("\n");
  check(/background:\s*var\(--notice-error-bg\)/.test(darkBlock), "dark override sets the warning background");

  let depth = 0;
  let unbalancedAt = null;
  lines.forEach((line, i) => {
    for (const ch of line) {
      if (ch === "{") depth += 1;
      if (ch === "}") {
        depth -= 1;
        if (depth < 0 && unbalancedAt === null) unbalancedAt = i + 1;
      }
    }
  });
  check(depth === 0 && unbalancedAt === null, "stylesheet braces are balanced", `depth=${depth} firstNegativeLine=${unbalancedAt}`);
}

// ---------------------------------------------------------------------------
// 3. Developer text must not reach the DOM.
// ---------------------------------------------------------------------------
{
  const main = read("src/main.tsx");
  check(!/error\.stack \|\| error\.message/.test(main), "main.tsx does not render a stack trace");

  const paraphrase = read("src/lib/generation/localParaphrase.ts");
  const noticeLines = paraphrase
    .split("\n")
    .filter((l) => l.includes("notice:") && l.includes("`"));
  const leaky = noticeLines.filter((l) => /modelId|error\.message|String\(error\)/.test(l));
  check(leaky.length === 0, "no notice template leaks a model id or raw error", leaky.join(" | ").slice(0, 140));

  const app = read("src/App.tsx");
  check(!/notice:.*\$\{native\.modelId\}/.test(app), "App.tsx notices do not interpolate a model id");

  // "on this device" is only truthful for a local route; the route label can be
  // "through FreeLLMAPI", which produced a false privacy claim.
  const onlineClaim = paraphrase
    .split("\n")
    .filter((l) => /notice:/.test(l) && /on this device/.test(l) && /RouteLabel/.test(l));
  check(onlineClaim.length === 0, "no notice asserts 'on this device' for a route that may be online", onlineClaim.join(" | ").slice(0, 140));
}

// ---------------------------------------------------------------------------
// 4. An unreadable store must not be reported as an empty one.
// ---------------------------------------------------------------------------
{
  const store = read("src/lib/persistence/approvalStore.ts");
  const loadBody = store.slice(store.indexOf("export async function loadApprovalState"));
  const idxBody = loadBody.slice(0, loadBody.indexOf("export function persistApproval"));
  check(
    !/catch[^}]*return\s*\{\s*schemaVersion/.test(idxBody.replace(/\n/g, "\\n")),
    "loadApprovalState never returns a synthetic empty state from a catch",
  );
  check(
    /isNativeBridgeUnavailable/.test(idxBody),
    "only a genuinely absent bridge falls back to IndexedDB",
  );
  check(
    !/could not be read[^`"]*\(\$\{/.test(idxBody),
    "the storage error message does not interpolate internals",
  );

  // The Swift side must refuse to merge into an unreadable history.
  const swift = read("Sources/OpenLocalPhraser/ApprovalPersistence.swift");
  check(/ok"\]\s*as\?\s*Bool\s*==\s*false/.test(swift), "saveApproval refuses to write over an unreadable history");
  check(/FileManager\.default\.fileExists/.test(swift), "loadState distinguishes a missing file from a corrupt one");
}

if (failures === 0) {
  console.log("  ux-contracts: all checks passed");
  process.exit(0);
}
console.log(`  ux-contracts: ${failures} check(s) failed`);
process.exit(1);
