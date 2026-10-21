# ws2-full-p17-word_sentences-1

Kind: `word_sentences`, asks for 5 options.

Paragraph:

> Bees are very important for the food we eat. When a bee goes from flower to flower to collect nectar, it carries pollen that helps plants make fruits and seeds. About one third of the food crops in the world depend on bees and other pollinators. In the past few decades, bee populations have gone down a lot because of pesticides, disease, and the loss of wild flowers. If bees keep disappearing, foods like apples, almonds, and blueberries could become much harder to grow. People can help by planting flowers and avoiding chemicals in their gardens.

Word: **indispensable** (suggested)

Instruction given to every model:

> Write 5 different sentences that use "indispensable" naturally and could fit into this paragraph, on its topic and in its argument. Each sentence must contain "indispensable" (another form of the word, such as a plural or past tense, is fine). Use only ideas the paragraph already contains; do not invent statistics, names or quotations. Put the best sentences first.

## Output A

ref `o-f3563b63a3cd`, raw sha256 `645ea9b2f91a6308e812687d947c9821043b6291c7acc07e2e0fc2e88130a33d`

Format: lenient (json_object), 5 options

1. Bees are indispensable for the food we eat.
2. Without bees, the process of making fruits and seeds would be incredibly difficult.  — not judged, counts as 0 (fail: missing_word)
3. The loss of bee populations makes it clear how indispensable they are to our food supply.
4. Bees play an indispensable role in the production of many of our favorite foods.
5. The decline in bee populations highlights the indispensable nature of these pollinators.

## Output B

ref `o-95e279a2b718`, raw sha256 `d5e8618d4708eb7cf4ba7fa3689b8eb46928ced7b232fa69ab094aab5e70e690`

Format: lenient (json_object), 5 options

1. Bees are indispensable for the food we eat.
2. Without bees, the food crops that depend on them would become impossible to grow.  — not judged, counts as 0 (fail: missing_word)
3. Indispensable to the pollination process, bees help plants make fruits and seeds.
4. If bees disappear, the indispensable role they play in agriculture would be lost.
5. The pollination services provided by bees are indispensable for the survival of many food crops.

## Output C

ref `o-1c6e0135c32b`, raw sha256 `154babcea480c60e9c2833298dfa9b4b19008d8820647441e3690bba24dc8bdb`

Format: strict (json_object), 5 options

1. Bees are indispensable for the food we eat.
2. The role of bees in creating fruits and seeds is indispensable.
3. Without bees, the growth of crops like apples and blueberries would become impossible.  — not judged, counts as 0 (fail: missing_word)
4. Planting flowers helps protect the indispensable role bees play in agriculture.
5. Avoiding chemicals in gardens ensures that the indispensable contribution of bees continues.
