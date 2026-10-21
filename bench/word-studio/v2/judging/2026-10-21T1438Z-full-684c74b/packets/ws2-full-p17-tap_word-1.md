# ws2-full-p17-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Bees are very important for the food we eat. When a bee goes from flower to flower to collect nectar, it carries pollen that helps plants make fruits and seeds. About one third of the food crops in the world depend on bees and other pollinators. In the past few decades, bee populations have gone down a lot because of pesticides, disease, and the loss of wild flowers. If bees keep disappearing, foods like apples, almonds, and blueberries could become much harder to grow. People can help by planting flowers and avoiding chemicals in their gardens.

Selected: Bees are very [[important]] for the food we eat.

Instruction given to every model:

> Give 10 replacements for "important" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "important" without changing the rest of the sentence. Do not repeat "important" itself. Put the best options first.

## Output A

ref `o-15bd902da014`, raw sha256 `63c223e052374932416324d1f0a00a8446fbbdd296aec3429aa91c74327d567c`

Format: strict (json_object), 10 options

1. crucial
2. essential
3. vital
4. critical
5. significant
6. key
7. indispensable
8. fundamental
9. central
10. necessary

## Output B

ref `o-13cd3f7044c8`, raw sha256 `6c0b2f7e5ac15808242588208c974ca3469963db78772246327def36ec335724`

Format: strict (json_object), 10 options

1. crucial
2. vital
3. essential
4. key
5. fundamental
6. critical
7. necessary
8. significant
9. central
10. key  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-d3304f5d5b9b`, raw sha256 `ca7ce8f42cb1321c8f4371dd91c0949132af774bc24face7ab7fe45d67343e18`

Format: lenient (json_object), 10 options

1. crucial
2. vital
3. essential
4. critical
5. significant
6. indispensable
7. key
8. vitality
9. significant  — not judged, counts as 0 (fail: duplicate)
10. cruciality
