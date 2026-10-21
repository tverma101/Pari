# ws2-full-p47-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> I will be the first person in my family to go to college, and that comes with a lot of pressure. My parents did not have the chance to continue their education because they had to start working when they were teenagers. They have always told me that school is the key to a better life. Filling out applications was confusing because no one at home had done it before, so I had to ask my counselor for help with almost every step. Even though the process was hard, it made me more determined to succeed. I want to make my parents proud and show my younger cousins that college is possible for them too.

Selected: Filling out applications was [[confusing]] because no one at home had done it before, so I had to ask my counselor for help with almost every step.

Instruction given to every model:

> Give 10 replacements for "confusing" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "confusing" without changing the rest of the sentence. Do not repeat "confusing" itself. Put the best options first.

## Output A

ref `o-b44cd173ee5e`, raw sha256 `131dbd28f8821483a2225824d450a76cc39682f9103a9a2c4f3e3708fe43ca15`

Format: strict (json_object), 10 options

1. puzzling
2. daunting
3. baffling
4. bewildering
5. overwhelming
6. complex
7. intricate
8. complicated
9. daunting process
10. challenging

## Output B

ref `o-f85d8543f157`, raw sha256 `3d8999f2bec3bffe8a1e80b1dbc4cea8a918a180f21d3fb0528f640af96520bd`

Format: strict (json_object), 10 options

1. challenging
2. daunting
3. overwhelming
4. complex
5. arduous
6. difficult
7. arduous  — not judged, counts as 0 (fail: duplicate)
8. demanding
9. time-consuming
10. frustrating

## Output C

ref `o-80ea05948817`, raw sha256 `f9bad19ef2df828b4326832426cd23b8fa4d9a3d826600cf903f38408f395f69`

Format: strict (json_object), 10 options

1. puzzling
2. overwhelming
3. complicated
4. daunting
5. maddening
6. troublesome
7. perplexing
8. frustrating
9. intimidating
10. bewildering
