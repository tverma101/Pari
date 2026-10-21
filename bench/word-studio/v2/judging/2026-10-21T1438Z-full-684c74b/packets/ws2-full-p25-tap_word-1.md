# ws2-full-p25-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The Dust Bowl was a period in the 1930s when huge dust storms hit the Great Plains. Farmers had plowed up the grass that held the soil in place, and then a long drought dried everything out. When strong winds came, they picked up the loose dirt and created clouds of dust so thick that people could not see the sun. Crops died, animals got sick, and many families lost their farms. Thousands of people packed up their belongings and moved west to California looking for work. The disaster taught the government that it needed to help farmers protect the land.

Selected: The Dust Bowl was a period in the 1930s when huge dust storms [[hit]] the Great Plains.

Instruction given to every model:

> Give 10 replacements for "hit" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "hit" without changing the rest of the sentence. Do not repeat "hit" itself. Put the best options first.

## Output A

ref `o-62bede844884`, raw sha256 `d077a760d585e21733ec3a0762224fb78f8ac69cff053469f51972d969c23d41`

Format: strict (json_object), 10 options

1. struck
2. affected
3. impacted
4. struck down
5. struck  — not judged, counts as 0 (fail: duplicate)
6. struck  — not judged, counts as 0 (fail: duplicate)
7. struck  — not judged, counts as 0 (fail: duplicate)
8. struck  — not judged, counts as 0 (fail: duplicate)
9. struck  — not judged, counts as 0 (fail: duplicate)
10. struck  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-66da2d60fc11`, raw sha256 `31bb1c3d42840e5a0157e2dc75fe4aafe7ed96e5c75a5c2e74508c1cf507929e`

Format: lenient (json_object_then_text), 10 options, hit the token limit

1. affect
2. affect  — not judged, counts as 0 (fail: duplicate)
3. affect  — not judged, counts as 0 (fail: duplicate)
4. affect  — not judged, counts as 0 (fail: duplicate)
5. affect  — not judged, counts as 0 (fail: duplicate)
6. affect  — not judged, counts as 0 (fail: duplicate)
7. affect  — not judged, counts as 0 (fail: duplicate)
8. affect  — not judged, counts as 0 (fail: duplicate)
9. affect  — not judged, counts as 0 (fail: duplicate)
10. affect  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-8f180205c7b6`, raw sha256 `6f976bf736ef47257e2b22a2e7b35afe59de9d2d0239fb071ba678ad1128359a`

Format: strict (json_object), 9 options

1. affected
2. struck
3. impacted
4. touched
5. landed on
6. brought to
7. reached
8. oversaw
9. occurred over
