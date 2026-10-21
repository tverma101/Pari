# ws2-full-p32-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In The Crucible, Arthur Miller shows how fear can make a whole town turn against itself. When a group of girls in Salem start accusing people of witchcraft, the adults believe them without asking for proof. Anyone who disagrees with the court is in danger of being accused too. John Proctor knows the girls are lying, but at first he is afraid to speak up because he has his own secret. In the end, he chooses to die rather than sign a false confession. Miller wrote the play in the 1950s to criticize the way people were being accused of being communists without real evidence.

Selected: John Proctor knows the girls are lying, but at first he is [[afraid]] to speak up because he has his own secret.

Instruction given to every model:

> Give 10 replacements for "afraid" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "afraid" without changing the rest of the sentence. Do not repeat "afraid" itself. Put the best options first.

## Output A

ref `o-c6361117e08b`, raw sha256 `e4e348e2cbd7fac78619fc29ed16c36345fd5f8c7d1dae70ed7402d41c4990b4`

Format: strict (json_object), 11 options

1. cautious
2. fearful
3. timid
4. hesitant
5. reluctant
6. wary
7. nervous
8. fearful of repercussions
9. fearful for his reputation  — not judged, counts as 0 (fail: too_many_words)
10. fearful of consequences
11. fearful of being ostracized  — not judged, counts as 0 (fail: beyond_requested, too_many_words)

## Output B

ref `o-a4fea001acda`, raw sha256 `762c5038c671a670a9bca8c61e3eac41e313b4ea93c6ad4d0e479df8c0a6a796`

Format: lenient (json_object), 10 options

1. hesitant
2. cowardly
3. scared
4. timid
5. nervous
6. reluctant
7. fearful
8. dreadful
9. shy
10. worried

## Output C

ref `o-e66f01a1a361`, raw sha256 `711a830ed546a1cd57701c29752daf26457c1c607d0a76cc54523fe0d2444da6`

Format: strict (json_object), 10 options

1. terrified
2. intimidated
3. scared
4. hesitant
5. daring
6. reluctant
7. ashamed
8. concerned
9. fearful
10. timid
