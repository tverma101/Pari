# ws2-full-p14-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Some school districts have switched to a four-day school week to save money and give students more time to rest. Supporters say that teachers are less tired and students come to school more ready to learn. The extra day off can also be used for doctor appointments, jobs, or family time. However, the longer school days can be hard for younger kids who have trouble focusing for that long. Working parents might also have to pay for childcare on the fifth day, which could be a problem for families without much money. Before more districts make this change, they should look closely at how it affects students' learning.

Selected: Working parents might also have to pay for childcare on the fifth day, which could be a [[problem]] for families without much money.

Instruction given to every model:

> Give 10 replacements for "problem" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "problem" without changing the rest of the sentence. Do not repeat "problem" itself. Put the best options first.

## Output A

ref `o-b5345d2d3a14`, raw sha256 `1fab5a6686529c4df92161959396162a537e72a61ce47bc98aa6687545e218e2`

Format: lenient (json_object), 10 options, hit the token limit

1. issue
2. challenge
3. difficulty
4. concern
5. burden
6. obstacle
7. hurdle
8. problem  — not judged, counts as 0 (fail: echo)
9. difficulty  — not judged, counts as 0 (fail: duplicate)
10. difficulty  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-89d0e6439c55`, raw sha256 `6129cbc96ad96c5fef8ac0f98586585991ce9d12b0415cf6db6dbc1e351e1da3`

Format: strict (json_object), 10 options

1. concern
2. issue
3. challenge
4. complication
5. dilemma
6. obstacle
7. difficulty
8. burden
9. hurdle
10. setback

## Output C

ref `o-6d02f0103885`, raw sha256 `fdecbd86d0f3a7ed485f33951f93990f7567ced0fb1d3d71936ca25fe5c60db7`

Format: strict (json_object), 10 options

1. challenge
2. issue
3. dilemma
4. concern
5. difficulty
6. obstacle
7. burden
8. hurdle
9. drawback
10. issue  — not judged, counts as 0 (fail: duplicate)
