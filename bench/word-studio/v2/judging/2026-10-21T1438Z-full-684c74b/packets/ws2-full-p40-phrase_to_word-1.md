# ws2-full-p40-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> The Silk Road was not one single road but a network of trade routes that connected China to the Middle East and Europe. Merchants traveled these routes for more than a thousand years, carrying goods like silk, spices, and paper. But the Silk Road did more than move products from one place to another. It also helped spread religions, languages, and inventions between very different cultures. For example, Buddhism traveled from India to China along these routes. In many ways, the Silk Road was an early example of how the world is connected.

Selected: It also helped spread religions, languages, and inventions between [[very different]] cultures.

Instruction given to every model:

> Give 10 single words that can replace "very different" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-b7076033a618`, raw sha256 `36febf510726e8beacadbfc03129bb3ef1e6f3620f1276e1bcf9738e59a7cc53`

Format: strict (json_object), 10 options

1. distinct
2. diverse
3. unique
4. different
5. varied
6. unique  — not judged, counts as 0 (fail: duplicate)
7. distinct  — not judged, counts as 0 (fail: duplicate)
8. separate
9. unlike
10. other

## Output B

ref `o-93144964ba71`, raw sha256 `588b592253d1c29ec212fedc436c0a53354e99475b2b00a7bd15f59b3315043d`

Format: strict (json_object), 10 options

1. distinct
2. diverse
3. separate
4. varied
5. different
6. unique
7. various
8. distinctive
9. heterogeneous
10. distinctly different  — not judged, counts as 0 (fail: too_many_words)

## Output C

ref `o-b9a1f2cb87b0`, raw sha256 `fd1f334411fe74ad2eeada67a0a942cf377f082ee2cccd3cb45fe83a1eafeda0`

Format: strict (json_object), 10 options

1. extremely diverse  — not judged, counts as 0 (fail: too_many_words)
2. highly varied  — not judged, counts as 0 (fail: too_many_words)
3. widely different  — not judged, counts as 0 (fail: too_many_words)
4. distinct
5. numerous
6. varied
7. different
8. diverse
9. varied  — not judged, counts as 0 (fail: duplicate)
10. distinct  — not judged, counts as 0 (fail: duplicate)
