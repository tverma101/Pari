# ws2-screen-p04-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Teenagers need about eight to ten hours of sleep every night, but most of them get a lot less. One reason is that their body clocks change during puberty, so they do not feel tired until late at night. On top of that, many teens stay up looking at their phones, and the blue light makes it even harder to fall asleep. Not getting enough sleep is bad for the brain because it makes it hard to remember things and focus in class. It can also make teens more moody and stressed out. Scientists have found that students who sleep more usually get better grades. This is why some experts think schools should start later in the morning.

Selected: It can also make teens more moody and [[stressed out]].

Instruction given to every model:

> Give 10 single words that can replace "stressed out" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-952a7d8cb6ed`, raw sha256 `b62910d8cbef971df1906b94f6d6c1b1326411bf322f585341fbbe77cd868cc0`

Format: strict (json_object), 10 options

1. anxious
2. frustrated
3. irritated
4. upset
5. tense
6. distressed
7. agitated
8. worried
9. uneasy
10. turbulent

## Output B

ref `o-a2a6265b1871`, raw sha256 `220315ee1b80517930cb2c1b9fb270f2e88603eb8eedf05ed147ac8272f6f551`

Format: strict (json_object), 10 options

1. anxious
2. irritable
3. tense
4. frustrated
5. exhausted
6. worried
7. upset
8. distressed
9. agitated
10. nervous

## Output C

ref `o-7d157be29e80`, raw sha256 `74b2470843b29922a8004b794d62edf9f21637651fd40847c9f9b3ab5ba10aba`

Format: strict (json_object), 10 options

1. anxious
2. tense
3. nervous
4. worried
5. distressed
6. upset
7. stressful
8. stressed
9. tense  — not judged, counts as 0 (fail: duplicate)
10. nervous  — not judged, counts as 0 (fail: duplicate)

## Output D

ref `o-a3914269ef3a`, raw sha256 `540c11b2d103e33900f741c55b7d2aec10d40d75812227bdea0924762d95c0b8`

Format: strict (json_object), 10 options

1. anxious
2. tense
3. worried
4. upset
5. frustrated
6. nervous
7. upset  — not judged, counts as 0 (fail: duplicate)
8. worried  — not judged, counts as 0 (fail: duplicate)
9. tense  — not judged, counts as 0 (fail: duplicate)
10. upset  — not judged, counts as 0 (fail: duplicate)

## Output E

ref `o-0743e7a275e0`, raw sha256 `3b871e4ed7b29361214192b263a88cc03ea0dcda5ff36f7aae6846bd9a9d0c78`

Format: unparseable (unparseable), 0 options

No options to judge.

