# ws2-full-p19-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Standardized tests like the SAT are supposed to measure how ready students are for college, but they do not tell the whole story. A student's score can depend a lot on whether their family could pay for tutoring and practice books. Some students are also very nervous test-takers, so their scores do not show what they actually know. Because of this, more than 1,800 colleges have made the SAT optional. I think colleges should look at grades, essays, and activities instead of focusing on one test score.

Selected: Standardized tests like the SAT are supposed to [[measure]] how ready students are for college, but they do not tell the whole story.

Instruction given to every model:

> Give 10 replacements for "measure" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "measure" without changing the rest of the sentence. Do not repeat "measure" itself. Put the best options first.

## Output A

ref `o-8f87765cd5a1`, raw sha256 `1e8d50dfc46b2a0af0c72a28b2c3361145d9e90ce4e65457a55d463ca2320485`

Format: strict (json_object), 10 options

1. assess
2. evaluate
3. determine
4. indicate
5. suggest
6. reflect
7. signify
8. show
9. reveal
10. indicate  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-64c043d16b94`, raw sha256 `96618024bbc58100fdec306c3de803623c24bbe56e24380a3b6326c77175343e`

Format: strict (json_object), 10 options

1. assess
2. determine
3. evaluate
4. judge
5. gauge
6. estimate
7. predict
8. indicate
9. show
10. reflect

## Output C

ref `o-457c0d599856`, raw sha256 `d33973883940103283ed243d861bd95d42bf4f754796c580df55d9e4147e7eb6`

Format: strict (json_object), 10 options

1. evaluate readiness
2. assess preparedness
3. evaluate college readiness
4. judge college readiness
5. assess readiness
6. evaluate suitability
7. judge suitability
8. assess preparedness  — not judged, counts as 0 (fail: duplicate)
9. evaluate suitability  — not judged, counts as 0 (fail: duplicate)
10. judge suitability  — not judged, counts as 0 (fail: duplicate)
