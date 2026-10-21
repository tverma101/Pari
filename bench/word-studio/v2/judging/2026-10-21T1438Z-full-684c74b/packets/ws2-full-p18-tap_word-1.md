# ws2-full-p18-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Joining the robotics team in tenth grade was one of the best choices I ever made. Our first competition was a disaster because our robot stopped working in the middle of the match. I felt embarrassed, and I wanted to quit the team right then. Instead, our coach told us to figure out what went wrong and try again. We spent weeks testing every part until we found a loose wire in the motor. At our next competition, the robot worked perfectly and we made it to the finals. That experience taught me that failing is just part of getting better.

Selected: I felt [[embarrassed]], and I wanted to quit the team right then.

Instruction given to every model:

> Give 10 replacements for "embarrassed" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "embarrassed" without changing the rest of the sentence. Do not repeat "embarrassed" itself. Put the best options first.

## Output A

ref `o-c705d2ea9044`, raw sha256 `01e625aae8e93e2b6e308241e8d4ff5721aea0132fa32ab5bb87c95483f8b13e`

Format: strict (json_object), 10 options

1. ashamed
2. disheartened
3. stung
4. humiliated
5. shamed  — not judged, counts as 0 (fail: duplicate)
6. mortified
7. self-conscious
8. disappointed
9. ashamed  — not judged, counts as 0 (fail: duplicate)
10. down

## Output B

ref `o-e1249ab3b10f`, raw sha256 `f8647102a82e8a4b774382a619f56132bf7af2a9819fe3a85c1095da556209e0`

Format: strict (json_object), 10 options

1. humiliated
2. ashamed
3. disappointed
4. awkward
5. nervous
6. frustrated
7. tense
8. flustered
9. fazed
10. shaken

## Output C

ref `o-f952b038d429`, raw sha256 `9b1d647920a1dd033bea1fafad33274b680f650067e7e3baf8340d0befe539d2`

Format: lenient (json_object), 10 options

1. puttled
2. humiliated
3. ashamed
4. disheartened
5. self-conscious
6. dejected
7. downcast
8. mortified
9. dismayed
10. downhearted
