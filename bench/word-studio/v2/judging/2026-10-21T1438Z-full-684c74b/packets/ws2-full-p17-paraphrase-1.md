# ws2-full-p17-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Bees are very important for the food we eat. When a bee goes from flower to flower to collect nectar, it carries pollen that helps plants make fruits and seeds. About one third of the food crops in the world depend on bees and other pollinators. In the past few decades, bee populations have gone down a lot because of pesticides, disease, and the loss of wild flowers. If bees keep disappearing, foods like apples, almonds, and blueberries could become much harder to grow. People can help by planting flowers and avoiding chemicals in their gardens.

Selected: About one third of the food crops in the world depend on bees and other pollinators.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-fb77666f3b65`, raw sha256 `5394bfc6cbbde9b9f198a1c71cfdb43ca0f4516591c38601d079f3540b3b6f4e`

Format: strict (json_object), 5 options

1. Approximately one third of global food crops rely on bees and other pollinators.
2. One third of the world's food crops depend on bees and other pollinators.
3. About one third of food crops worldwide rely on bees and other pollinators.
4. Approximately one third of the world's food crops depend on bees and other pollinators.  — not judged, counts as 0 (fail: duplicate)
5. One third of food crops globally depend on bees and other pollinators.  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-bf4a75ab7df5`, raw sha256 `4189a17405548027b2a4556cbe64b155bf67849685ef33188bb7de30e95094c5`

Format: strict (json_object), 5 options

1. One third of the world's food crops rely on bees and other pollinators.
2. Around one third of food crops globally depend on bees and pollinators.
3. Approximately one third of our food crops are dependent on bees and pollinators.
4. One third of the food crops worldwide are reliant on bees and other pollinators.
5. A third of the food crops in the world are supported by bees and pollinators.

## Output C

ref `o-cf5deb9171a6`, raw sha256 `d894b5255fcbd832582993539696ea481da855e80b38d8d172250ce4d0a3db31`

Format: strict (json_object), 5 options

1. One-third of global food crops rely on bees and other pollinators.
2. A significant portion of the world's food crops depend on bees and pollinators.
3. Approximately one-third of the world's food crops are dependent on bees and pollinators.
4. One-third of the world's food crops are supported by bees and other pollinators.
5. Bees and other pollinators are crucial for one-third of the world's food crops.
