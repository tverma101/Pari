# ws2-full-p41-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Every year, millions of tons of plastic end up in the ocean. Over time, sunlight and waves break this plastic into tiny pieces called microplastics. These pieces are so small that fish and other sea animals eat them by accident. Scientists have even found microplastics in drinking water, salt, and human blood. We still do not fully understand how they affect our health, but some studies suggest they could cause inflammation. Reducing how much plastic we use is the most important step we can take to fix this problem.

Selected: Over time, sunlight and waves break this plastic into [[tiny]] pieces called microplastics.

Instruction given to every model:

> Give 10 replacements for "tiny" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "tiny" without changing the rest of the sentence. Do not repeat "tiny" itself. Put the best options first.

## Output A

ref `o-7eb09f4f08a9`, raw sha256 `bbeebb93ad7c7ab57b52b47bfe3f7ca43d9cb31236fe6951644aa98ac4579c51`

Format: unparseable (unparseable), 0 options

No options to judge.


## Output B

ref `o-a0a24f8b75c4`, raw sha256 `3167fbd4388014c4d5cb28ef3462818b59420b2464aa0c63acc0bf973bf3b0f8`

Format: strict (json_object), 10 options

1. small
2. minute
3. minuscule
4. miniscule
5. little
6. insignificant
7. infinitesimal
8. negligible
9. inconsequential
10. insignificant  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-8c72bdec7f50`, raw sha256 `46b0ba37d1a0f31f0388e4a97b4b4a4e270f9f49e47cfc1875268fde01ba6407`

Format: strict (json_object), 10 options

1. minute
2. small
3. minute fragments
4. minuscule
5. microscopic
6. microscopic pieces
7. micro-sized
8. microlight
9. microscopic fragments
10. minute fragments  — not judged, counts as 0 (fail: duplicate)
