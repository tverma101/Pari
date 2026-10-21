# ws2-full-p27-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Plastic bags are cheap and easy to use, but they cause big problems for the environment. Most of them are only used once before they get thrown away. Because they are so light, they often blow out of trash cans and end up in rivers and oceans, where animals like sea turtles mistake them for food. A plastic bag can take hundreds of years to break down. Several states, such as California and New York, have already banned single-use plastic bags. I think every state should do the same and encourage people to bring reusable bags to the store.

Selected: Several states, such as California and New York, have already banned single-use plastic bags.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-83d044c95631`, raw sha256 `c789773ef3301273e9041522acaf63386059d2d9fa0d34ffa57d2ea7081d3cc9`

Format: lenient (json_object), 5 options

1. Several states, including California and New York, have implemented bans on single-use plastic bags.
2. California and New York have taken the initiative to outlaw single-use plastic bags.
3. In California and New York, single-use plastic bags have been prohibited.
4. Several states, such as California and New York, have decided to ban single-use plastic bags.
5. California and New York have successfully banned single-use plastic bags.

## Output B

ref `o-5464f55d6445`, raw sha256 `53b46709dec7d2a9e1240b59639619b6121fea6637cb21d92f55428fe79faf91`

Format: strict (json_object), 5 options

1. Several states, including California and New York, have already enacted bans on single-use plastic bags.
2. States like California and New York have already prohibited the use of single-use plastic bags.
3. Several states, such as California and New York, have already banned single-use plastic bags.  — not judged, counts as 0 (fail: echo)
4. States including California and New York have already implemented bans on single-use plastic bags.  — not judged, counts as 0 (fail: duplicate)
5. California and New York are among the states that have banned single-use plastic bags.

## Output C

ref `o-89053c788d8e`, raw sha256 `a7d67ffe9621cd5c5f6b24435567bd2009fd2528d2bb3c893fa04ef214491aaf`

Format: strict (json_object), 5 options

1. Several states, including California and New York, have already prohibited single-use plastic bags.
2. Multiple states, such as California and New York, have already banned single-use plastic bags.
3. States like California and New York have already enacted bans on single-use plastic bags.
4. Several states, for example California and New York, have already outlawed single-use plastic bags.
5. A number of states, including California and New York, have already banned single-use plastic bags.
