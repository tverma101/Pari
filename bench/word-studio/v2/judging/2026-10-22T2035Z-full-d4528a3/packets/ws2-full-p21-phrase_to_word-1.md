# ws2-full-p21-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> The Black Death was a plague that spread across Europe starting in 1347. It was carried by fleas that lived on rats, and it moved quickly along trade routes and through crowded cities. Within just a few years, it killed somewhere between a third and half of Europe's population. Because so many workers died, the people who survived could ask for higher pay, which made the old feudal system weaker. The plague also made a lot of people question the church, since prayers did not seem to stop the disease.

Selected: Because so many workers died, the people who survived could [[ask for]] higher pay, which made the old feudal system weaker.

Instruction given to every model:

> Give 10 single words that can replace "ask for" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-398335579df6`, raw sha256 `08f71892f826415d13ba6af4c3e807c2ff5d2a7fb3c886aa16e9fb838ecbaf72`

Format: strict (json_object), 10 options

1. demand
2. request
3. seeking
4. pleading
5. sought
6. beg
7. cried
8. pleaded
9. solicited
10. pleading  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-5481ef29fc8c`, raw sha256 `e838c15b23ce23239484851c4cae05c34513a77f85dd9f963318b45435d0b8be`

Format: strict (json_object), 10 options

1. demand
2. demand  — not judged, counts as 0 (fail: duplicate)
3. seek
4. request
5. claim
6. insist
7. urge
8. press
9. press  — not judged, counts as 0 (fail: duplicate)
10. petition
