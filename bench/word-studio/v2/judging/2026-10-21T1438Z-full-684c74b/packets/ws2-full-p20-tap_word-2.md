# ws2-full-p20-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Romeo and Juliet is often called a love story, but it is also a story about how acting too fast can lead to disaster. Romeo and Juliet meet, fall in love, and get married in less than a week. Neither of them stops to think about what their families will do when they find out. Friar Laurence even warns Romeo that "they stumble that run fast," but Romeo does not listen. When Romeo hears that Juliet is dead, he kills himself right away instead of waiting to learn the truth. If the two young lovers had slowed down, the play might have had a happy ending.

Selected: Friar Laurence even [[warns]] Romeo that "they stumble that run fast," but Romeo does not listen.

Instruction given to every model:

> Give 10 replacements for "warns" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "warns" without changing the rest of the sentence. Do not repeat "warns" itself. Put the best options first.

## Output A

ref `o-33905ce6f85f`, raw sha256 `6551330ae8c869f78b39cd192de6bc01469fed2ba8511bf901bcd2333451dfd2`

Format: lenient (json_object), 10 options

1. advises
2. cautions
3. admonishes
4. urges
5. implies
6. reminds
7. pleads
8. persuades
9. urges  — not judged, counts as 0 (fail: duplicate)
10. encourages

## Output B

ref `o-1f95af6d5d9c`, raw sha256 `ae127c27536516074298de035d670e1e8589a89ce6fb7acc943e16121ee73d76`

Format: strict (json_object), 10 options

1. cautions
2. advises
3. alerts
4. cites
5. notifies
6. informs
7. tells
8. says
9. mentions
10. points out

## Output C

ref `o-164bd00bad20`, raw sha256 `9ead55ee32427dfb36673d6670e3a4792205017c7199c59cd7c98c58448afa7e`

Format: strict (json_object), 10 options

1. cautions
2. advises
3. tells
4. reminds
5. alerts
6. urges
7. speaks
8. states
9. says
10. notices
