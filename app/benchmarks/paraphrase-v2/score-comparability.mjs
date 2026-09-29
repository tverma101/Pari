export function scoreBundleComparability(bundles) {
  if (bundles.length <= 1) {
    return {
      comparable: true,
      reasons: [],
      judgeFingerprints: bundles.map((bundle) => bundle.judge?.fingerprint ?? null),
      corpusHashes: bundles.map((bundle) => bundle.corpus?.sha256 ?? null),
    };
  }

  const reasons = [];
  const judgeFingerprints = bundles.map((bundle) => bundle.judge?.fingerprint ?? null);
  const corpusHashes = bundles.map((bundle) => bundle.corpus?.sha256 ?? null);
  const corpusVersions = bundles.map((bundle) => bundle.corpus?.version ?? null);
  const postprocessModes = bundles.map((bundle) => Boolean(bundle.outputs?.productionPostprocess));

  if (judgeFingerprints.some((value) => !value)) {
    reasons.push("one or more score bundles do not record a judge fingerprint");
  } else if (new Set(judgeFingerprints).size !== 1) {
    reasons.push("score bundles were produced by different judge revisions");
  }

  if (corpusHashes.some((value) => !value)) {
    reasons.push("one or more score bundles do not record a corpus SHA-256");
  } else if (new Set(corpusHashes).size !== 1) {
    reasons.push("score bundles were produced from different corpus contents");
  }

  if (new Set(corpusVersions).size !== 1) {
    reasons.push("score bundles report different corpus versions");
  }

  if (new Set(postprocessModes).size !== 1) {
    reasons.push("score bundles mix raw and production-postprocessed outputs");
  }

  return {
    comparable: reasons.length === 0,
    reasons,
    judgeFingerprints,
    corpusHashes,
    corpusVersions,
    productionPostprocess: postprocessModes,
  };
}

export function assertComparableScoreBundles(bundles, { allowMixed = false } = {}) {
  const result = scoreBundleComparability(bundles);
  if (!result.comparable && !allowMixed) {
    throw new Error(
      `score bundles are not directly comparable: ${result.reasons.join("; ")}. ` +
      "Re-score under one judge/corpus, or pass --allow-mixed-judge only for an explicitly non-comparable forensic report.",
    );
  }
  return result;
}
