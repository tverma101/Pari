# ws2-full-p23-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Some people believe the voting age should be lowered from 18 to 16. At sixteen, many teenagers already have jobs, pay taxes, and can drive a car. Laws about schools, the environment, and the economy will affect young people for the rest of their lives, so they should have a say in them. Critics argue that sixteen-year-olds are not mature enough to make good choices about politics. However, studies of places like Austria, where sixteen-year-olds can vote, show that young voters make choices that are just as thought-out as older voters.

Selected: Critics argue that sixteen-year-olds are not [[mature]] enough to make good choices about politics.

Instruction given to every model:

> Give 10 replacements for "mature" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "mature" without changing the rest of the sentence. Do not repeat "mature" itself. Put the best options first.

## Output A

ref `o-070966361512`, raw sha256 `10666ca94c2d2de3c972213fedb3c401be2f78fbb36ffd2027f5b9a208916891`

Format: strict (json_object), 10 options

1. adult
2. sophisticated
3. well-developed
4. disciplined
5. experienced
6. capable
7. adept
8. competent
9. competent  — not judged, counts as 0 (fail: duplicate)
10. skilled

## Output B

ref `o-8453efa1762d`, raw sha256 `d2b3e70fbf89ee48a7ca0e8e0135eeaa83795b359897386e4127586e08a5e2a4`

Format: lenient (json_object), 1 options

1. capable

## Output C

ref `o-19cea10f4602`, raw sha256 `8d4a769528ef6d6fae1d8c33ca64498a119206fc9301135e97d7fb3211415dcd`

Format: strict (json_object), 10 options

1. wise
2. developed
3. experienced
4. sophisticated
5. responsible
6. prudent
7. knowledgeable
8. seasoned
9. judicious
10. informed
