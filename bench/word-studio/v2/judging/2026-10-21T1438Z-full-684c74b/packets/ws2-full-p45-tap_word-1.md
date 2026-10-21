# ws2-full-p45-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Hamlet is a character who thinks too much and acts too little. After his father's ghost tells him that Claudius murdered him, Hamlet promises to get revenge. But instead of acting right away, he spends most of the play doubting himself and planning. In his famous speech, he asks, "To be, or not to be," as he wonders whether life is worth the pain. Even when he has a perfect chance to kill Claudius while he is praying, he decides to wait. His delay ends up causing the deaths of many people, including himself.

Selected: But instead of acting right away, he spends most of the play [[doubting]] himself and planning.

Instruction given to every model:

> Give 10 replacements for "doubting" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "doubting" without changing the rest of the sentence. Do not repeat "doubting" itself. Put the best options first.

## Output A

ref `o-ce19ff84b662`, raw sha256 `93dfd4470a38ec795ad7ae2dcf907108ea9556663e2cc7317c6079f11e1bd46f`

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

ref `o-c1dfe0a9ec87`, raw sha256 `2f70717a9fb13a4f1ca48fff07147127d4c51aee0d2e3ed3572c89e673bb0490`

Format: strict (json_object), 10 options

1. hesitating
2. uncertain
3. distrustful
4. perplexed
5. bewildered
6. uncertain  — not judged, counts as 0 (fail: duplicate)
7. hesitant
8. uncertain  — not judged, counts as 0 (fail: duplicate)
9. hesitant  — not judged, counts as 0 (fail: duplicate)
10. uncertain  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-ad47570a927a`, raw sha256 `5e05a0cbbe427049fcd840f98365966f0744b08cfdb63a428c479deb427441ed`

Format: strict (json_object), 10 options

1. questioning
2. questioning himself
3. second-guessing
4. second-guessing himself
5. hesitating
6. hesitating himself
7. worrying
8. worrying himself
9. uncertain
10. uncertain about himself
