# ws2-full-p45-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Hamlet is a character who thinks too much and acts too little. After his father's ghost tells him that Claudius murdered him, Hamlet promises to get revenge. But instead of acting right away, he spends most of the play doubting himself and planning. In his famous speech, he asks, "To be, or not to be," as he wonders whether life is worth the pain. Even when he has a perfect chance to kill Claudius while he is praying, he decides to wait. His delay ends up causing the deaths of many people, including himself.

Selected: After his father's ghost tells him that Claudius murdered him, Hamlet promises to [[get revenge]].

Instruction given to every model:

> Give 10 single words that can replace "get revenge" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-880d32ed1b81`, raw sha256 `afef6bcc06390fd19cdf5ad9cad1573af0a367614ff790937728b1065e861583`

Format: strict (json_object), 10 options

1. avenge
2. revenge
3. retaliate
4. punish
5. repay
6. exact
7. settle
8. strike
9. strike back  — not judged, counts as 0 (fail: too_many_words)
10. take
