# ws2-full-p14-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Some school districts have switched to a four-day school week to save money and give students more time to rest. Supporters say that teachers are less tired and students come to school more ready to learn. The extra day off can also be used for doctor appointments, jobs, or family time. However, the longer school days can be hard for younger kids who have trouble focusing for that long. Working parents might also have to pay for childcare on the fifth day, which could be a problem for families without much money. Before more districts make this change, they should look closely at how it affects students' learning.

Selected: Supporters say that teachers are less tired and students come to school more [[ready]] to learn.

Instruction given to every model:

> Give 10 replacements for "ready" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "ready" without changing the rest of the sentence. Do not repeat "ready" itself. Put the best options first.

## Output A

ref `o-d68b57a7fda0`, raw sha256 `4b62e7123915d806e48acc3e55f7d732aa370ecd3c956fa880a21fadcb43c775`

Format: lenient (json_object_then_text), 10 options, hit the token limit

1. alert
2. focused
3. enthusiastic
4. alerted
5. alert  — not judged, counts as 0 (fail: duplicate)
6. focused  — not judged, counts as 0 (fail: duplicate)
7. enthusiastic  — not judged, counts as 0 (fail: duplicate)
8. alerted  — not judged, counts as 0 (fail: duplicate)
9. focused  — not judged, counts as 0 (fail: duplicate)
10. enthusiastic  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-cfd87b72296d`, raw sha256 `5470bde603a216ddc072708379e87bd78d36451b16be26eeb712737a6230ef9a`

Format: strict (json_object), 10 options

1. prepared
2. eager
3. willing
4. keen
5. enthusiastic
6. willing to learn
7. inclined to study
8. keen to participate
9. prepared to engage
10. willing to start

## Output C

ref `o-46f4919aaffe`, raw sha256 `976c3cd091eed19b98b9e276f6a64da72b815f7711c9c9f459f19f51e4a8f38d`

Format: lenient (json_object), 8 options

1. prepared
2. eager
3. motivated
4. focused
5. engaged
6. thirsty
7. anxious
8. determined
