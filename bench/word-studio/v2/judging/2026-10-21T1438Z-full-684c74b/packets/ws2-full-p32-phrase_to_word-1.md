# ws2-full-p32-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> In The Crucible, Arthur Miller shows how fear can make a whole town turn against itself. When a group of girls in Salem start accusing people of witchcraft, the adults believe them without asking for proof. Anyone who disagrees with the court is in danger of being accused too. John Proctor knows the girls are lying, but at first he is afraid to speak up because he has his own secret. In the end, he chooses to die rather than sign a false confession. Miller wrote the play in the 1950s to criticize the way people were being accused of being communists without real evidence.

Selected: John Proctor knows the girls are lying, but at first he is afraid to [[speak up]] because he has his own secret.

Instruction given to every model:

> Give 10 single words that can replace "speak up" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-dcb91482c8a8`, raw sha256 `ba478180bd9841be48a7b54556d1adc6138009421da28ddc2271a17622a9ee14`

Format: strict (json_object), 10 options

1. speak
2. voice
3. speak out  — not judged, counts as 0 (fail: too_many_words)
4. protest
5. object
6. resist
7. refuse
8. denounce
9. challenge
10. confront

## Output B

ref `o-c5e010af9d78`, raw sha256 `12be24da2e89ff43f17c4e52aaa11725a7c2b778a161c998dd0e3fd7f466fa10`

Format: strict (json_object), 10 options

1. express
2. voice
3. advocate
4. declare
5. articulate
6. respond
7. explain
8. state
9. protest
10. opine

## Output C

ref `o-a5163e83a037`, raw sha256 `3c4ad0a4c2a30b9b3ad6dfd632590454b8d153c4be9caade8914feb231698429`

Format: strict (json_object), 10 options

1. speak
2. say
3. blurt
4. declare
5. advocate
6. assert
7. pronounce
8. declare  — not judged, counts as 0 (fail: duplicate)
9. out
10. announce
