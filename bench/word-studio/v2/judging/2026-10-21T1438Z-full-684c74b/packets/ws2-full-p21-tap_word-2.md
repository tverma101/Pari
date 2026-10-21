# ws2-full-p21-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The Black Death was a plague that spread across Europe starting in 1347. It was carried by fleas that lived on rats, and it moved quickly along trade routes and through crowded cities. Within just a few years, it killed somewhere between a third and half of Europe's population. Because so many workers died, the people who survived could ask for higher pay, which made the old feudal system weaker. The plague also made a lot of people question the church, since prayers did not seem to stop the disease.

Selected: Because so many workers died, the people who survived could ask for higher pay, which made the old feudal system [[weaker]].

Instruction given to every model:

> Give 10 replacements for "weaker" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "weaker" without changing the rest of the sentence. Do not repeat "weaker" itself. Put the best options first.

## Output A

ref `o-2a259913b29c`, raw sha256 `8d1d845a111c5829725388b7c5609f139096053a211eba2fc761b5756880faf4`

Format: strict (json_object), 10 options

1. less robust
2. more vulnerable
3. diminished influence
4. less stable
5. reduced power
6. less resilient
7. decreased strength
8. lessened effectiveness
9. weakened structure
10. diluted dominance

## Output B

ref `o-d0eefe5c2baa`, raw sha256 `e5ad2329541fb24f142dff471855727b37ab1b8c12c6c7818d33784036504a77`

Format: strict (json_object), 10 options

1. weakened
2. compromised
3. weakened  — not judged, counts as 0 (fail: duplicate)
4. diminished
5. eroded
6. lessened
7. weakened  — not judged, counts as 0 (fail: duplicate)
8. weakened  — not judged, counts as 0 (fail: duplicate)
9. weakened  — not judged, counts as 0 (fail: duplicate)
10. weakened  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-f95d0548a1ce`, raw sha256 `d2896faddec86c4c55d10f4d143d5fe160eb5f9a484dd5610d6125a5c1f563e7`

Format: strict (json_object), 10 options

1. more fragile
2. less stable
3. more vulnerable
4. more easily disrupted
5. less rigid
6. more susceptible to change  — not judged, counts as 0 (fail: too_many_words)
7. more prone to collapse  — not judged, counts as 0 (fail: too_many_words)
8. less effective
9. more unstable
10. more easily undermined
