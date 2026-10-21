# ws2-full-p45-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Hamlet is a character who thinks too much and acts too little. After his father's ghost tells him that Claudius murdered him, Hamlet promises to get revenge. But instead of acting right away, he spends most of the play doubting himself and planning. In his famous speech, he asks, "To be, or not to be," as he wonders whether life is worth the pain. Even when he has a perfect chance to kill Claudius while he is praying, he decides to wait. His delay ends up causing the deaths of many people, including himself.

Selected: After his father's ghost tells him that Claudius murdered him, Hamlet promises to [[get revenge]].

Instruction given to every model:

> Give 10 single words that can replace "get revenge" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-d44d6d3bdfad`, raw sha256 `5b5bccdca7902a6993eeb0d5db7a11faa98286bdada3e30d40bcb5ebb39e48aa`

Format: strict (json_object), 10 options

1. retaliate
2. repay
3. avenge
4. retaliate  — not judged, counts as 0 (fail: duplicate)
5. revenge
6. retribution
7. avenge  — not judged, counts as 0 (fail: duplicate)
8. retaliate  — not judged, counts as 0 (fail: duplicate)
9. revenge  — not judged, counts as 0 (fail: duplicate)
10. retribution  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-6a822159dc82`, raw sha256 `ea482d7a1b037e3b48be2950c040a79960ae604ac86edb5a67724d567777baf7`

Format: strict (json_object), 10 options

1. seek retribution  — not judged, counts as 0 (fail: too_many_words)
2. vengeance
3. seek justice  — not judged, counts as 0 (fail: too_many_words)
4. assault
5. retaliate
6. revenge
7. avenging
8. punish
9. strike back  — not judged, counts as 0 (fail: too_many_words)
10. retaliation

## Output C

ref `o-d6d1dbe4f09b`, raw sha256 `66e1b80b6a2b70e0a92643bb2c622ad6aad62f99f25132ef89421e5aa43cd7ff`

Format: strict (json_object), 10 options

1. avenge
2. take revenge  — not judged, counts as 0 (fail: too_many_words)
3. seek retribution  — not judged, counts as 0 (fail: too_many_words)
4. exact justice  — not judged, counts as 0 (fail: too_many_words)
5. obtain vengeance  — not judged, counts as 0 (fail: too_many_words)
6. fulfill a vow  — not judged, counts as 0 (fail: too_many_words)
7. exact payment  — not judged, counts as 0 (fail: too_many_words)
8. fulfill an oath  — not judged, counts as 0 (fail: too_many_words)
9. repay a debt  — not judged, counts as 0 (fail: too_many_words)
10. fulfill a promise  — not judged, counts as 0 (fail: too_many_words)
