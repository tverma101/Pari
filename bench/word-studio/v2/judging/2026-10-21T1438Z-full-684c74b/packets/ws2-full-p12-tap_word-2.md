# ws2-full-p12-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Antibiotics are medicines that kill bacteria, and they have saved millions of lives since they were discovered. The problem is that bacteria can change over time so that the medicine does not work on them anymore. This happens faster when people take antibiotics they do not really need, like for a cold, which is caused by a virus. It also happens when people stop taking their pills early because they start to feel better. If this keeps going, simple infections could become deadly again. To stop this, doctors need to be careful about giving out antibiotics, and patients need to finish the whole treatment.

Selected: If this keeps going, [[simple]] infections could become deadly again.

Instruction given to every model:

> Give 10 replacements for "simple" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "simple" without changing the rest of the sentence. Do not repeat "simple" itself. Put the best options first.

## Output A

ref `o-6d54c0665e1a`, raw sha256 `c5472a8cdf4a4c4b785aa59e903567f7de97db271b06a6b1495dd3c51a208d09`

Format: strict (json_object), 11 options

1. basic
2. common
3. ordinary
4. general
5. everyday
6. routine
7. basic-level
8. common-cause
9. non-complex
10. uncomplicated
11. usual-infections  — not judged, counts as 0 (fail: beyond_requested)

## Output B

ref `o-69bf3624b29e`, raw sha256 `6e4cbdfa99214acbde0f2e7d1a8c55fae1c5173e9c4fe71b9096be1147703dab`

Format: strict (json_object), 10 options

1. common
2. minor
3. routine
4. uncomplicated
5. ordinary
6. basic
7. mild
8. everyday
9. standard
10. harmless

## Output C

ref `o-80bee8c724bf`, raw sha256 `055a2cbef8ee85860fcc6af6fcc738a1378700006b1c031be3b31ec721685981`

Format: strict (json_object), 10 options

1. common
2. typical
3. ordinary
4. regular
5. typical  — not judged, counts as 0 (fail: duplicate)
6. usual
7. usual  — not judged, counts as 0 (fail: duplicate)
8. standard
9. typical  — not judged, counts as 0 (fail: duplicate)
10. usual  — not judged, counts as 0 (fail: duplicate)
