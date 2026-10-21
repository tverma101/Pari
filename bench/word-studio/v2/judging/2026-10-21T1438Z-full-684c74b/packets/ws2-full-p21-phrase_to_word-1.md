# ws2-full-p21-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> The Black Death was a plague that spread across Europe starting in 1347. It was carried by fleas that lived on rats, and it moved quickly along trade routes and through crowded cities. Within just a few years, it killed somewhere between a third and half of Europe's population. Because so many workers died, the people who survived could ask for higher pay, which made the old feudal system weaker. The plague also made a lot of people question the church, since prayers did not seem to stop the disease.

Selected: Because so many workers died, the people who survived could [[ask for]] higher pay, which made the old feudal system weaker.

Instruction given to every model:

> Give 10 single words that can replace "ask for" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-d7665cfde578`, raw sha256 `bb3511dab9abe504dbd1b1e070106305b5402197c39b73d61f8ae4e1d1296625`

Format: strict (json_object), 10 options

1. demand
2. seek
3. request
4. plead
5. beg
6. claim
7. entreat
8. petition
9. call
10. urge

## Output B

ref `o-f1c28ebf1362`, raw sha256 `08f71892f826415d13ba6af4c3e807c2ff5d2a7fb3c886aa16e9fb838ecbaf72`

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

## Output C

ref `o-e28341f6a02d`, raw sha256 `6bc156fa71588ece92c53ca7b6afe31f81c3f91cfe4a79a3d8771c05646ac588`

Format: strict (json_object), 10 options

1. demand
2. request
3. claim
4. argue for  — not judged, counts as 0 (fail: too_many_words)
5. insist on  — not judged, counts as 0 (fail: too_many_words)
6. ask for  — not judged, counts as 0 (fail: echo, too_many_words)
7. press for  — not judged, counts as 0 (fail: too_many_words)
8. propose
9. plead for  — not judged, counts as 0 (fail: too_many_words)
10. assert
