# ws2-full-p45-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Hamlet is a character who thinks too much and acts too little. After his father's ghost tells him that Claudius murdered him, Hamlet promises to get revenge. But instead of acting right away, he spends most of the play doubting himself and planning. In his famous speech, he asks, "To be, or not to be," as he wonders whether life is worth the pain. Even when he has a perfect chance to kill Claudius while he is praying, he decides to wait. His delay ends up causing the deaths of many people, including himself.

Selected: But instead of acting right away, he spends most of the play [[doubting]] himself and planning.

Instruction given to every model:

> Give 10 replacements for "doubting" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "doubting" without changing the rest of the sentence. Do not repeat "doubting" itself. Put the best options first.

## Output A

ref `o-66156cd85e6e`, raw sha256 `93dfd4470a38ec795ad7ae2dcf907108ea9556663e2cc7317c6079f11e1bd46f`

Format: strict (json_object), 10 options

1. questioning
2. hesitant
3. unsure
4. uncertain
5. wary
6. skeptical
7. insecure
8. self-doubtful
9. cynical
10. distrustful

## Output B

ref `o-ae3962f2f1ef`, raw sha256 `7bc590decf8d794d32acff8cd0e93eef108f2c053ecddca4914c0c1e2e6bd2a6`

Format: strict (json_object), 10 options

1. questioning
2. hesitating
3. second-guessing
4. wondering
5. vacillating
6. worrying
7. struggling
8. hesitating  — not judged, counts as 0 (fail: duplicate)
9. wondering  — not judged, counts as 0 (fail: duplicate)
10. uncertain
