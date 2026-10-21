# ws2-full-p25-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The Dust Bowl was a period in the 1930s when huge dust storms hit the Great Plains. Farmers had plowed up the grass that held the soil in place, and then a long drought dried everything out. When strong winds came, they picked up the loose dirt and created clouds of dust so thick that people could not see the sun. Crops died, animals got sick, and many families lost their farms. Thousands of people packed up their belongings and moved west to California looking for work. The disaster taught the government that it needed to help farmers protect the land.

Selected: When strong winds came, they picked up the loose dirt and created clouds of dust so [[thick]] that people could not see the sun.

Instruction given to every model:

> Give 10 replacements for "thick" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "thick" without changing the rest of the sentence. Do not repeat "thick" itself. Put the best options first.

## Output A

ref `o-dcd50d268e78`, raw sha256 `e614f8ff5586140747278f18f2adac2955582eefe910be01d0abab5897f646bd`

Format: unparseable (unparseable), 0 options

No options to judge.


## Output B

ref `o-aba4d33f9566`, raw sha256 `4531d5afdecf543217aa30fdc74b6a11925385907922a72eb2166d224c08970a`

Format: lenient (json_object_then_text), 10 options, hit the token limit

1. dense
2. thick  — not judged, counts as 0 (fail: echo)
3. dense  — not judged, counts as 0 (fail: duplicate)
4. dense  — not judged, counts as 0 (fail: duplicate)
5. heavy
6. thick  — not judged, counts as 0 (fail: duplicate, echo)
7. thick  — not judged, counts as 0 (fail: duplicate, echo)
8. dense  — not judged, counts as 0 (fail: duplicate)
9. dense  — not judged, counts as 0 (fail: duplicate)
10. thick  — not judged, counts as 0 (fail: duplicate, echo)

## Output C

ref `o-ae068c7f0d79`, raw sha256 `2812778cf6be2a28cc8be400a9b0a24d23ce3c55d7343fef96a7d8b3e26b697b`

Format: strict (json_object), 11 options

1. dense
2. heavy
3. dense  — not judged, counts as 0 (fail: duplicate)
4. hefty
5. murky
6. cloudy
7. cloudy  — not judged, counts as 0 (fail: duplicate)
8. thick  — not judged, counts as 0 (fail: echo)
9. thick  — not judged, counts as 0 (fail: duplicate, echo)
10. dense  — not judged, counts as 0 (fail: duplicate)
11. dense  — not judged, counts as 0 (fail: beyond_requested, duplicate)
