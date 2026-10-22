# ws2-full-p17-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Bees are very important for the food we eat. When a bee goes from flower to flower to collect nectar, it carries pollen that helps plants make fruits and seeds. About one third of the food crops in the world depend on bees and other pollinators. In the past few decades, bee populations have gone down a lot because of pesticides, disease, and the loss of wild flowers. If bees keep disappearing, foods like apples, almonds, and blueberries could become much harder to grow. People can help by planting flowers and avoiding chemicals in their gardens.

Selected: Bees are very [[important]] for the food we eat.

Instruction given to every model:

> Give 10 replacements for "important" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "important" without changing the rest of the sentence. Do not repeat "important" itself. Put the best options first.

## Output A

ref `o-6a87b00b755b`, raw sha256 `b339f21024ec122e1736c8cd0ff26510aff170b44fee39c114a3777bed2bffb9`

Format: strict (json_object), 10 options

1. crucial
2. essential
3. vital
4. key
5. fundamental
6. critical
7. indispensable
8. necessary
9. central
10. primary

## Output B

ref `o-24fa5feb3f3e`, raw sha256 `ca7ce8f42cb1321c8f4371dd91c0949132af774bc24face7ab7fe45d67343e18`

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
