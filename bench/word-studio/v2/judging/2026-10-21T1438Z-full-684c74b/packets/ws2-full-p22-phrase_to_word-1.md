# ws2-full-p22-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Coral reefs are some of the most beautiful places on Earth, but they are in serious trouble. When the ocean gets too warm, corals push out the tiny algae that live inside them and give them their color. This is called coral bleaching, and if the water stays hot for too long, the coral can die. Reefs are home to about a quarter of all ocean species, so losing them would hurt a lot of sea life. They also protect coastlines from big waves during storms. Cutting down on pollution and greenhouse gases is the best way to give reefs a chance to recover.

Selected: [[Cutting down on]] pollution and greenhouse gases is the best way to give reefs a chance to recover.

Instruction given to every model:

> Give 10 single words that can replace "Cutting down on" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-9406caaab47b`, raw sha256 `b195b80702f85800105328c6de38027e1fc38307de73bc93ae00cf11947ba127`

Format: strict (json_object), 10 options

1. Reducing
2. Decreasing
3. Minimizing
4. Lowering
5. Diminishing
6. Cutting
7. Cutting back  — not judged, counts as 0 (fail: too_many_words)
8. Lessening
9. Cutting down  — not judged, counts as 0 (fail: too_many_words)
10. Reducing emissions  — not judged, counts as 0 (fail: too_many_words)

## Output B

ref `o-2018947d5f95`, raw sha256 `4d4dc918c753b6f1042b837cf341d3e0bf3525761f1bcad4c1cfed1b18327f91`

Format: strict (json_object), 10 options

1. Reducing
2. Cutting
3. Lowering
4. Decreasing
5. Minimizing
6. Lessening
7. Diminishing
8. Tackling
9. Addressing
10. Stopping

## Output C

ref `o-1d959cd8e40b`, raw sha256 `db958dda3efd8c454823ff1aad74c860d7fd2858627826a6f43ec88c59f79847`

Format: strict (json_object), 10 options

1. Reduce
2. Minimize
3. Lower
4. Cut
5. Decrease
6. Limit
7. Cut back  — not judged, counts as 0 (fail: too_many_words)
8. Cut off  — not judged, counts as 0 (fail: too_many_words)
9. Lessen
10. Diminish
