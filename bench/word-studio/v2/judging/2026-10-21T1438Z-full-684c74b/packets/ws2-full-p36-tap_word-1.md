# ws2-full-p36-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Renewable energy comes from sources that do not run out, like the sun, wind, and water. Unlike coal and oil, these sources do not release a lot of greenhouse gases when they make electricity. In the last ten years, the cost of solar panels has dropped so much that solar power is now cheaper than coal in many places. One problem is that the sun does not always shine and the wind does not always blow, so we need better batteries to store the energy. Even with these challenges, switching to renewable energy is one of the best ways to slow down climate change.

Selected: In the last ten years, the cost of solar panels has [[dropped]] so much that solar power is now cheaper than coal in many places.

Instruction given to every model:

> Give 10 replacements for "dropped" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "dropped" without changing the rest of the sentence. Do not repeat "dropped" itself. Put the best options first.

## Output A

ref `o-2cf21e75295a`, raw sha256 `ea23481b38091961629cc6db704bd2cfe8dfc414931108e096f0db7efab76ed2`

Format: strict (json_object), 10 options

1. decreased
2. fallen
3. plummeted
4. sunk
5. declined
6. slumped
7. dropped  — not judged, counts as 0 (fail: echo)
8. waned
9. lessened
10. decreased  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-92990e9ff77f`, raw sha256 `5efa49862857b37616c360029ed36ce16eeb656b0731cffc3e71e7af253e1fab`

Format: strict (json_object), 10 options

1. fallen
2. decreased
3. plummeted
4. reduced
5. diminished
6. declined
7. fallen  — not judged, counts as 0 (fail: duplicate)
8. slashed
9. cut
10. lowered

## Output C

ref `o-4568eaeff4ec`, raw sha256 `0bcbb245a0c276567a8518953e3ac9efe7ed26f34414cfa9909540b734a4eff1`

Format: strict (json_object), 10 options

1. fallen
2. declined
3. decreased
4. fallen sharply
5. gone down
6. fallen significantly
7. plummeted
8. fallen to record lows  — not judged, counts as 0 (fail: too_many_words)
9. fallen rapidly
10. fallen dramatically
