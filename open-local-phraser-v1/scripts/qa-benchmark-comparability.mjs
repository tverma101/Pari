#!/usr/bin/env node
import assert from "node:assert/strict";
import {
  assertComparableScoreBundles,
  scoreBundleComparability,
} from "../benchmarks/paraphrase-v2/score-comparability.mjs";

function bundle({
  judge = "a".repeat(64),
  corpus = "b".repeat(64),
  version = 2,
  postprocess = true,
} = {}) {
  return {
    judge: judge ? { fingerprint: judge } : undefined,
    corpus: { sha256: corpus, version },
    outputs: { productionPostprocess: postprocess },
  };
}

const same = [bundle(), bundle()];
assert.equal(scoreBundleComparability(same).comparable, true, "identical judge/corpus bundles should compare");
assert.doesNotThrow(() => assertComparableScoreBundles(same), "identical bundles were rejected");

for (const [label, pair, expectedReason] of [
  [
    "judge revision drift",
    [bundle(), bundle({ judge: "c".repeat(64) })],
    /different judge revisions/,
  ],
  [
    "missing judge provenance",
    [bundle(), bundle({ judge: null })],
    /do not record a judge fingerprint/,
  ],
  [
    "corpus content drift",
    [bundle(), bundle({ corpus: "d".repeat(64) })],
    /different corpus contents/,
  ],
  [
    "corpus version drift",
    [bundle(), bundle({ version: 3 })],
    /different corpus versions/,
  ],
  [
    "postprocess mode drift",
    [bundle(), bundle({ postprocess: false })],
    /mix raw and production-postprocessed outputs/,
  ],
]) {
  const result = scoreBundleComparability(pair);
  assert.equal(result.comparable, false, `${label}: incompatible bundles were accepted`);
  assert(result.reasons.some((reason) => expectedReason.test(reason)), `${label}: expected reason missing: ${result.reasons.join("; ")}`);
  assert.throws(() => assertComparableScoreBundles(pair), /not directly comparable/, `${label}: fail-closed assertion did not throw`);
  assert.doesNotThrow(
    () => assertComparableScoreBundles(pair, { allowMixed: true }),
    `${label}: explicit forensic override was ignored`,
  );
}

assert.equal(
  scoreBundleComparability([{}]).comparable,
  true,
  "a single legacy score bundle should remain inspectable without pretending it is a comparison",
);

console.log("qa:benchmark:comparability passed");
