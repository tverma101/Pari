# ws2-full-p21-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The Black Death was a plague that spread across Europe starting in 1347. It was carried by fleas that lived on rats, and it moved quickly along trade routes and through crowded cities. Within just a few years, it killed somewhere between a third and half of Europe's population. Because so many workers died, the people who survived could ask for higher pay, which made the old feudal system weaker. The plague also made a lot of people question the church, since prayers did not seem to stop the disease.

Selected: It was carried by fleas that lived on rats, and it moved quickly along trade routes and through [[crowded]] cities.

Instruction given to every model:

> Give 10 replacements for "crowded" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "crowded" without changing the rest of the sentence. Do not repeat "crowded" itself. Put the best options first.

## Output A

ref `o-62b0a46c0c82`, raw sha256 `0c97258337463fb198c07a0a260ea12bfb351082805a89a665a5ed1224f1297f`

Format: lenient (json_object), 10 options

1. packed
2. overpopulated
3. densely populated
4. excessively populated
5. highly populated
6. crowded  — not judged, counts as 0 (fail: echo)
7. massively populated
8. densely inhabited
9. overfull
10. swarming

## Output B

ref `o-0defb2f7d4ba`, raw sha256 `1a77bb3878f0e40e104f9918500049108b8e0946b1986080a4796cbc58a21af3`

Format: lenient (json_object), 9 options

1. dense
2. overcrowded
3. congested
4. heavily populated
5. crowded  — not judged, counts as 0 (fail: echo)
6. bustling
7. tightly packed
8. overcrowded  — not judged, counts as 0 (fail: duplicate)
9. dense  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-6bc501bd0f97`, raw sha256 `c29c36e5bd3aa7360cf237a377427716d34623e1433d38d79f092f5530c55968`

Format: strict (json_object), 11 options

1. densely populated
2. overpopulated
3. packed
4. thronged
5. overcrowded
6. heavily populated
7. teeming
8. bursting at the seams  — not judged, counts as 0 (fail: too_many_words)
9. jam-packed
10. overflowing
11. swarming  — not judged, counts as 0 (fail: beyond_requested)
