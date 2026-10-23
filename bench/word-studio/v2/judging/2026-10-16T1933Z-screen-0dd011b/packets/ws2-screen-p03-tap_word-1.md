# ws2-screen-p03-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The printing press was one of the most important inventions in history. Before Johannes Gutenberg built his press around 1440, books had to be copied by hand, which took a really long time. Because of this, books were very expensive and only rich people and churches could have them. After the press was invented, books could be made much faster and for a lot less money. More people started learning how to read, and new ideas spread across Europe quickly. Some historians say that the press helped cause big changes like the Reformation and the Scientific Revolution. Without it, the world we live in today would probably be very different.

Selected: More people started learning how to read, and new ideas [[spread]] across Europe quickly.

Instruction given to every model:

> Give 10 replacements for "spread" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "spread" without changing the rest of the sentence. Do not repeat "spread" itself. Put the best options first.

## Output A

ref `o-cb8dcc7584a8`, raw sha256 `5e9cc65973a29d037704df4d2e29374e12e6d75580fb786a42e8ca7e899b8cc6`

Format: strict (json_object), 10 options

1. flow
2. circulate
3. pass
4. go
5. trickle
6. radiate
7. percolate
8. circulate  — not judged, counts as 0 (fail: duplicate)
9. pervade
10. disseminate

## Output B

ref `o-cdb0af41f462`, raw sha256 `9ab86a7171b9c7f841fbf9a4cdbe2c3ee93a179488a91a40a6891938d13607e7`

Format: strict (json_object), 10 options

1. widespread
2. disseminate
3. circulate
4. propagate
5. dissperse
6. disperse  — not judged, counts as 0 (fail: duplicate)
7. disseminate  — not judged, counts as 0 (fail: duplicate)
8. widespread  — not judged, counts as 0 (fail: duplicate)
9. disseminate  — not judged, counts as 0 (fail: duplicate)
10. dispersal

## Output C

ref `o-3da57949f0ae`, raw sha256 `f0c5f3fc75eae10f6bfad73035604ac1e71fc096c85ba0b530dc7ce8295729b3`

Format: strict (json_object), 10 options

1. disseminated
2. circulated
3. propagated
4. disseminated  — not judged, counts as 0 (fail: duplicate)
5. circulated  — not judged, counts as 0 (fail: duplicate)
6. propagated  — not judged, counts as 0 (fail: duplicate)
7. transmitted
8. disseminated  — not judged, counts as 0 (fail: duplicate)
9. disseminated  — not judged, counts as 0 (fail: duplicate)
10. circulated  — not judged, counts as 0 (fail: duplicate)

## Output D

ref `o-c7de14d0b2a7`, raw sha256 `560cba1964133015c12824f581fe52efeb1183f7a2d39d29022b00aae6afac4f`

Format: strict (json_object), 10 options

1. propagate
2. diffuse
3. spread  — not judged, counts as 0 (fail: echo)
4. radiate
5. circulate
6. disseminate
7. transmit
8. spread  — not judged, counts as 0 (fail: duplicate, echo)
9. flow
10. move

## Output E

ref `o-63bcb4f34013`, raw sha256 `7d185048fba0225c3502a619b9a5181b1b643e1b795c82e8bec6a29f712ac302`

Format: strict (json_object), 10 options

1. travelled
2. circulated
3. disseminated
4. moved
5. traveled  — not judged, counts as 0 (fail: duplicate)
6. flowed
7. went
8. traveled  — not judged, counts as 0 (fail: duplicate)
9. propagated
10. broke out
