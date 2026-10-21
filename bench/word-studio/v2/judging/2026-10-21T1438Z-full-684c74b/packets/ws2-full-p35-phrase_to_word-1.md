# ws2-full-p35-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> On July 20, 1969, Neil Armstrong became the first person to walk on the moon. The Apollo 11 mission was the result of years of hard work by thousands of scientists, engineers, and astronauts. The United States wanted to beat the Soviet Union in the space race, which was part of the larger Cold War. Millions of people around the world watched the landing live on television. The mission showed what humans can do when they work together toward a big goal. It also led to new technologies that we still use today.

Selected: The mission showed what humans can do when they [[work together]] toward a big goal.

Instruction given to every model:

> Give 10 single words that can replace "work together" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-15f0e8455681`, raw sha256 `c62e0627341df65e26b01c46159dba81b09792d6a42b0af056c70bff4993c3d2`

Format: strict (json_object), 10 options

1. collaborate
2. unite
3. join forces  — not judged, counts as 0 (fail: too_many_words)
4. cooperate
5. team up  — not judged, counts as 0 (fail: too_many_words)
6. band together  — not judged, counts as 0 (fail: too_many_words)
7. come together  — not judged, counts as 0 (fail: too_many_words)
8. work in concert  — not judged, counts as 0 (fail: too_many_words)
9. lodge in harmony  — not judged, counts as 0 (fail: too_many_words)
10. come together  — not judged, counts as 0 (fail: duplicate, too_many_words)

## Output B

ref `o-098148d43e2f`, raw sha256 `ac2e67720e7b153713293abe793580a824ee904efe8cf5a977d64aac0f430216`

Format: strict (json_object), 10 options

1. collaborate
2. cooperate
3. unite
4. team
5. bond
6. collude
7. join
8. align
9. convene
10. merge

## Output C

ref `o-c02d03e984b5`, raw sha256 `13cfae23474ad54567c0a62a2986f2032f96ac62376fca6742637509d19fe30b`

Format: strict (json_object), 10 options

1. collaborate
2. unite
3. join forces  — not judged, counts as 0 (fail: too_many_words)
4. coordinate
5. team up  — not judged, counts as 0 (fail: too_many_words)
6. join
7. participate
8. contribute
9. cooperate
10. combine
