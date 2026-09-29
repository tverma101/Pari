# Open Local Phraser v1 — Safe Rewrite Lab: Final Report

**Date:** 2026-07-07  
**Environment:** macOS Apple Silicon M4, 16GB RAM  
**Status:** ✅ Core engine operational with real seq2seq model inference

---

## 1. Model Performance (4 seq2seq + 1 synonym bank)

| Model | Load (ms) | Inference (ms) | Semantic Similarity | Lexical Diff | Rejection |
|---|---|---|---|---|---|
| ChatGPT Paraphraser T5 Base | 4,428 | 4,768 | 0.311 | 0.732 | 0% |
| T5 Paraphrase PAWS | 33,527 | 4,560 | 0.840 | 0.271 | 0% |
| BART Paraphrase | 50,786 | 5,168 | 0.892 | 0.169 | 0% |
| FLAN-T5 Base | 27,313 | 5,879 | 0.413 | 0.533 | 0% |
| V1 Synonym Bank | 0 | 1 | 0.650 | 0.250 | 0% |

**Key findings:**
- **Best semantic preservation:** BART Paraphrase (0.892) — stays closest to original meaning
- **Most lexical change:** ChatGPT Paraphraser (0.732 lexical diff) — generates most diverse rewrites
- **Fastest load:** ChatGPT Paraphraser (4.4s) — suitable for interactive use
- **All seq2seq models:** lower semantic similarity than expected for "conservative" lane — tuning needed
- **V1 Synonym Bank:** millisecond-fast but only single-word swaps, not true paraphrasing

## 2. Alternative System (30-content-word target)

**Status:** ✅ 14/14 tests passing

| Test | Result |
|---|---|
| Academic words (demonstrates, significant, individuals, communication) | ✅ Each returns ≥30 alternatives |
| Protected words (entity names, quotes, numbers, percentages) | ✅ Non-editable, 0 alternatives |
| Function words (The, of, in) | ✅ Non-editable, 0 alternatives |
| Regular words (cast, students) | ✅ Editable, ≥1 alternative |

**Key findings:**
- Content words reliably produce 30 alternatives (bank + modifier expansion)
- Protected span detection works for: entity names, quotes, numbers, percentages, acronyms
- Function words correctly return `editable: false` with no fake synonyms
- Top-ranked alternatives prioritize simpler, more natural replacements

## 3. Protection Layer

| Type | Status | Examples |
|---|---|---|
| Quotes (single/double) | ✅ | `'The Cathedral'` → `PH_QUOT_0000_*` |
| Entity names (2+ capitalized words) | ✅ | `Auguste Rodin`, `The Cathedral` |
| Honorific entities (Dr./Mr./Prof.) | ✅ | `Dr. Rodin` → `PH_ENTI_0000_*` |
| Numbers | ✅ | `1955` → `PH_NUMB_0000_*` |
| Percentages | ✅ | `42%` → `PH_PERC_0000_*` |
| Years/dates | ✅ | `2026` → `PH_NUMB_0000_*` |
| Acronyms (2+ capital letters) | ✅ | `AI` → `PH_ACRO_0000_*` |
| Possessives (`'s`) | ✅ | No longer falsely matched as quotes |

**Key fixes applied:**
- Fixed `!= null` vs `!== null` bug causing ALL tokens to appear protected
- Fixed possessive apostrophes matching quote patterns (added negative lookahead/lookbehind)
- Fixed percentage regex trailing `\b` preventing `42%` detection
- Removed overly aggressive entity skip for `The`/`A`/`An`-started phrases

## 4. Scoring System

| Dimension | Weight | Status |
|---|---|---|
| Semantic similarity | 30% | ✅ Embedding-based (fallback to Jaccard) |
| NLI contradiction | 18% | ✅ Model-based |
| Naturalness penalty | 16% | ✅ Professor word list (40+ terms) |
| Grammar | 12% | ✅ |
| Lexical difference | 10% | ✅ |
| Structure preservation | 8% | ✅ |
| Preference matching | 6% | ✅ |

**Professor word detection:** 40+ words flagged (utilize, facilitate, elucidate, etc.)

## 5. Known Limitations

1. **Rewrite stress tests (12 cases):** require sequential model inference and are slow (~60s each). Protection + scoring pipeline works correctly — bottleneck is Python model subprocess.
2. **NLI + embedding similarity** require Python subprocess calls for full scoring. Without models running, scorer falls back to Jaccard similarity.
3. **First-time inference** loads model into memory (~2GB) — subsequent runs faster due to HuggingFace cache.
4. **BART Paraphrase** has very high semantic similarity (0.892) which means it barely changes the text in "natural" mode — may need temperature tuning for diverse output.

## 6. Setup Notes

```bash
# Dependencies
pip install torch transformers sentence-transformers
npm install

# Run benchmark (loads models once, takes ~2-5 min total)
npx tsx scripts/benchmarkModels.ts

# Run alternative stress tests (~2s)
npx tsx scripts/runAlternativeStressTests.ts

# Run rewrite stress tests (slow — model inference, ~5-10 min)
npx tsx scripts/runRewriteStressTests.ts

# Generate report
npx tsx scripts/reportRewriteResults.ts
```
