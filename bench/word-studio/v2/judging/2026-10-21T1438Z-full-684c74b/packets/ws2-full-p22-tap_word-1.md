# ws2-full-p22-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Coral reefs are some of the most beautiful places on Earth, but they are in serious trouble. When the ocean gets too warm, corals push out the tiny algae that live inside them and give them their color. This is called coral bleaching, and if the water stays hot for too long, the coral can die. Reefs are home to about a quarter of all ocean species, so losing them would hurt a lot of sea life. They also protect coastlines from big waves during storms. Cutting down on pollution and greenhouse gases is the best way to give reefs a chance to recover.

Selected: Coral reefs are some of the most beautiful places on Earth, but they are in [[serious]] trouble.

Instruction given to every model:

> Give 10 replacements for "serious" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "serious" without changing the rest of the sentence. Do not repeat "serious" itself. Put the best options first.

## Output A

ref `o-531511ea11af`, raw sha256 `533c1b8e52aba181937ba8190caca5aa0010b878d6c1b765c484f54b520b1872`

Format: strict (json_object), 10 options

1. dire
2. critical
3. grave
4. urgent
5. imminent
6. severe
7. direst
8. horrific
9. crucial
10. vital

## Output B

ref `o-3f674df62cd0`, raw sha256 `82cf9c16ee8ae818f573af750ad3c3500aff6b4b0246aa6365960b757beb731f`

Format: strict (json_object), 10 options

1. grave
2. critical
3. severe
4. serious  — not judged, counts as 0 (fail: echo)
5. critical  — not judged, counts as 0 (fail: duplicate)
6. complicated
7. serious  — not judged, counts as 0 (fail: duplicate, echo)
8. urgent
9. serious  — not judged, counts as 0 (fail: duplicate, echo)
10. significant

## Output C

ref `o-f54c5cb43580`, raw sha256 `b4d6688499abe84d0f0cd934897c229cf79a08ed33956d7d79483bbcc10c7a19`

Format: strict (json_object), 10 options

1. critical
2. severe
3. grave
4. widespread
5. widespread  — not judged, counts as 0 (fail: duplicate)
6. urgent
7. deep
8. deep  — not judged, counts as 0 (fail: duplicate)
9. profound
10. profound  — not judged, counts as 0 (fail: duplicate)
