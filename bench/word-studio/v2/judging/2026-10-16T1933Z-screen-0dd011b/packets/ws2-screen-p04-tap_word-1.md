# ws2-screen-p04-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Teenagers need about eight to ten hours of sleep every night, but most of them get a lot less. One reason is that their body clocks change during puberty, so they do not feel tired until late at night. On top of that, many teens stay up looking at their phones, and the blue light makes it even harder to fall asleep. Not getting enough sleep is bad for the brain because it makes it hard to remember things and focus in class. It can also make teens more moody and stressed out. Scientists have found that students who sleep more usually get better grades. This is why some experts think schools should start later in the morning.

Selected: Not getting enough sleep is [[bad]] for the brain because it makes it hard to remember things and focus in class.

Instruction given to every model:

> Give 10 replacements for "bad" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "bad" without changing the rest of the sentence. Do not repeat "bad" itself. Put the best options first.

## Output A

ref `o-61c3d6ac21cc`, raw sha256 `b0767057b80ff1299057fa145d9d3a65e60f06677b2269d943a4d6b2b9c1fc02`

Format: strict (json_object), 10 options

1. detrimental
2. harmful
3. hazardous
4. unfavorable
5. injurious
6. unhealthy
7. perilous
8. ineffective
9. harmful  — not judged, counts as 0 (fail: duplicate)
10. adverse

## Output B

ref `o-37a24eef33b4`, raw sha256 `47832aff5dcc88f17e70865894ce666e2361b1afcb0312fcd102e47dc9b97cfb`

Format: strict (json_object), 10 options

1. negative
2. harmful
3. detrimental
4. harmful  — not judged, counts as 0 (fail: duplicate)
5. damaging
6. harmful  — not judged, counts as 0 (fail: duplicate)
7. detrimental  — not judged, counts as 0 (fail: duplicate)
8. harmful  — not judged, counts as 0 (fail: duplicate)
9. detrimental  — not judged, counts as 0 (fail: duplicate)
10. harmful  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-aa34e3792259`, raw sha256 `5260117ea626f9391f3a3a657c447f6422b52c5c3ab5e87bf4365acc5604257a`

Format: strict (json_object), 10 options

1. harmful
2. detrimental
3. unfavorable
4. adverse
5. disadvantageous
6. negative
7. unfavorable  — not judged, counts as 0 (fail: duplicate)
8. detrimental  — not judged, counts as 0 (fail: duplicate)
9. disadvantageous  — not judged, counts as 0 (fail: duplicate)
10. unfavorable  — not judged, counts as 0 (fail: duplicate)

## Output D

ref `o-b0ebf3573d23`, raw sha256 `c5fa7052b93d579d3e803076d78ad0b7498503358b85a81cd5c035c608bf7bd9`

Format: strict (json_object), 10 options

1. harmful
2. detrimental
3. negative
4. detrimental to
5. harmful to
6. prejudicial
7. adverse
8. disastrous
9. harmful to cognitive function  — not judged, counts as 0 (fail: too_many_words)
10. detrimental to performance

## Output E

ref `o-68dc41c48d49`, raw sha256 `4b3b3458c20e286c7c942d0dbe524350c1e0a6edfbcc222e64f06df0cf8bec1e`

Format: strict (json_object), 10 options

1. harmful
2. detrimental
3. adverse
4. poisonous
5. harmful  — not judged, counts as 0 (fail: duplicate)
6. harmful  — not judged, counts as 0 (fail: duplicate)
7. harmful  — not judged, counts as 0 (fail: duplicate)
8. detrimental  — not judged, counts as 0 (fail: duplicate)
9. adverse  — not judged, counts as 0 (fail: duplicate)
10. negative
