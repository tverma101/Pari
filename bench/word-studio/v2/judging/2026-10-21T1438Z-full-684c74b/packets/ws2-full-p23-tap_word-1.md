# ws2-full-p23-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Some people believe the voting age should be lowered from 18 to 16. At sixteen, many teenagers already have jobs, pay taxes, and can drive a car. Laws about schools, the environment, and the economy will affect young people for the rest of their lives, so they should have a say in them. Critics argue that sixteen-year-olds are not mature enough to make good choices about politics. However, studies of places like Austria, where sixteen-year-olds can vote, show that young voters make choices that are just as thought-out as older voters.

Selected: Laws about schools, the environment, and the economy will affect young people for the rest of their lives, so they should have a [[say]] in them.

Instruction given to every model:

> Give 10 replacements for "say" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "say" without changing the rest of the sentence. Do not repeat "say" itself. Put the best options first.

## Output A

ref `o-3c4d522c6a60`, raw sha256 `0b4f800a37310b7941b1b0d66655086a95f0faf5ca2c12840d38ed57584a78fe`

Format: strict (json_object), 10 options

1. a voice
2. an opinion
3. a say
4. input
5. a stake
6. a role
7. a voice in
8. a voice on
9. influence
10. participation

## Output B

ref `o-19fe04791b36`, raw sha256 `7f6189db835e53e21b6a3772b0534e289b8dd314f2fe4048fa73aaaaaf6c1b3c`

Format: strict (json_object), 20 options

1. voice
2. opinion
3. opinion  — not judged, counts as 0 (fail: duplicate)
4. opinion  — not judged, counts as 0 (fail: duplicate)
5. opinion  — not judged, counts as 0 (fail: duplicate)
6. opinion  — not judged, counts as 0 (fail: duplicate)
7. opinion  — not judged, counts as 0 (fail: duplicate)
8. opinion  — not judged, counts as 0 (fail: duplicate)
9. opinion  — not judged, counts as 0 (fail: duplicate)
10. opinion  — not judged, counts as 0 (fail: duplicate)
11. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
12. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
13. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
14. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
15. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
16. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
17. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
18. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
19. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)
20. opinion  — not judged, counts as 0 (fail: beyond_requested, duplicate)

## Output C

ref `o-c94acb7e37bf`, raw sha256 `838d054b738466ec164cc64c28813db5c5ee61ad9fb4287568a983dfed73b193`

Format: strict (json_object), 10 options

1. participate in
2. have a voice in  — not judged, counts as 0 (fail: too_many_words)
3. be involved in
4. have a say in  — not judged, counts as 0 (fail: too_many_words)
5. have a stake in  — not judged, counts as 0 (fail: too_many_words)
6. have a hand in  — not judged, counts as 0 (fail: too_many_words)
7. have input on
8. be consulted on
9. be included in
10. be a part of  — not judged, counts as 0 (fail: too_many_words)
