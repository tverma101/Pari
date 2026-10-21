# ws2-full-p17-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Bees are very important for the food we eat. When a bee goes from flower to flower to collect nectar, it carries pollen that helps plants make fruits and seeds. About one third of the food crops in the world depend on bees and other pollinators. In the past few decades, bee populations have gone down a lot because of pesticides, disease, and the loss of wild flowers. If bees keep disappearing, foods like apples, almonds, and blueberries could become much harder to grow. People can help by planting flowers and avoiding chemicals in their gardens.

Selected: If bees keep [[disappearing]], foods like apples, almonds, and blueberries could become much harder to grow.

Instruction given to every model:

> Give 10 replacements for "disappearing" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "disappearing" without changing the rest of the sentence. Do not repeat "disappearing" itself. Put the best options first.

## Output A

ref `o-8b0012df5ead`, raw sha256 `3290ce75cef5873b316f4429dfd9d3c9948a31a2e32311510fc675953c5a693d`

Format: strict (json_object), 10 options

1. vanishing
2. fading
3. going extinct
4. declining
5. disintegrating
6. lost
7. wearing away
8. fading out
9. becoming scarce
10. fading into nothing

## Output B

ref `o-32dc2f46417f`, raw sha256 `127881e398fa4ccc7b45946645a1537c0393fed6b0878e384619f273faa61bee`

Format: lenient (json_object), 10 options

1. vanishing
2. declining
3. diminishing
4. fading
5. shrinking
6. dropping
7. withdrawing
8. disappearing rapidly
9. disappearing steadily
10. disappearing significantly

## Output C

ref `o-dd8374cfa4c2`, raw sha256 `9fe38eee336e09f319500211c9c6a5c7aa1526d1cbf1a4631972646223ba6784`

Format: lenient (json_object_then_text), 10 options

1. dwindling
2. declining
3. fading
4. vanishing
5. withering
6. shrinking
7. disappearing  — not judged, counts as 0 (fail: echo)
8. disappearing  — not judged, counts as 0 (fail: duplicate, echo)
9. dying out
10. experiencing a decline
