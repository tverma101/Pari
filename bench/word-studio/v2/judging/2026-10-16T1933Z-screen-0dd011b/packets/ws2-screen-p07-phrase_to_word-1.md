# ws2-screen-p07-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> In Macbeth, Shakespeare shows how wanting power too much can destroy a person. At the start of the play, Macbeth is a loyal soldier who fights bravely for King Duncan. After the witches tell him he will be king, he cannot stop thinking about it. Lady Macbeth pushes him to kill Duncan, and he finally agrees even though he feels guilty. Once he becomes king, he keeps killing people because he is afraid of losing what he has. By the end, Macbeth says that life is "a tale told by an idiot," which shows how empty he feels. His story is a warning about what happens when ambition gets out of control.

Selected: In Macbeth, Shakespeare shows how [[wanting power too much]] can destroy a person.

Instruction given to every model:

> Give 10 single words that can replace "wanting power too much" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-47f5c2550571`, raw sha256 `4e3e91b3d5f29b74eaeb1159bab88f6d1e71168f0b788c372a3134c8fcf8234f`

Format: strict (json_object), 10 options

1. craving
2. coveting
3. desiring
4. seeking
5. hunting
6. chasing
7. yearning
8. longing
9. craving  — not judged, counts as 0 (fail: duplicate)
10. coveting  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-1504fd8d73de`, raw sha256 `f1506cfbe75e6d0ff43a5f53059def47ea6db07016fc975ebab4eb9f25305adb`

Format: strict (json_object), 10 options

1. greed
2. lust
3. desire
4. ambition
5. greediness
6. lustiness
7. dread
8. foolishness
9. obsession
10. excess

## Output C

ref `o-9a2280773eca`, raw sha256 `f9ad8c41f5d09372025c5ab5ed2d3c7675d041862be13fa1427cab9aa2d2a944`

Format: lenient (json_object), 10 options

1. covetousness
2. greed
3. ambition
4. desire
5. covet
6. lust
7. craving
8. yearning
9. covetous
10. greediness

## Output D

ref `o-1678b3acdc43`, raw sha256 `df4c4a3f7efcb2be573fbcb43428d881d47486051ee22824d4280497979ba427`

Format: strict (json_object), 10 options

1. ambition
2. greed
3. arrogance
4. desire
5. passion
6. will
7. drive
8. hubris
9. avarice
10. lust

## Output E

ref `o-110231e47fbe`, raw sha256 `f0977d8488a7013b45463ed56fd5b987b28f8f468e3c6ddbfb8e88ff474d0151`

Format: strict (json_object), 10 options

1. ambition
2. greed
3. lust for power  — not judged, counts as 0 (fail: too_many_words)
4. desire for dominance  — not judged, counts as 0 (fail: too_many_words)
5. craving for control  — not judged, counts as 0 (fail: too_many_words)
6. yearning for authority  — not judged, counts as 0 (fail: too_many_words)
7. ambitious
8. power hungry  — not judged, counts as 0 (fail: too_many_words)
9. lust for power  — not judged, counts as 0 (fail: duplicate, too_many_words)
10. desire for supremacy  — not judged, counts as 0 (fail: too_many_words)
