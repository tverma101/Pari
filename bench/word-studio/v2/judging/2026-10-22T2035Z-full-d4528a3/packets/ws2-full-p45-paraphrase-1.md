# ws2-full-p45-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Hamlet is a character who thinks too much and acts too little. After his father's ghost tells him that Claudius murdered him, Hamlet promises to get revenge. But instead of acting right away, he spends most of the play doubting himself and planning. In his famous speech, he asks, "To be, or not to be," as he wonders whether life is worth the pain. Even when he has a perfect chance to kill Claudius while he is praying, he decides to wait. His delay ends up causing the deaths of many people, including himself.

Selected: Even when he has a perfect chance to kill Claudius while he is praying, he decides to wait.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-50f983360bde`, raw sha256 `79b0ff650f1d3d6618be6e651a0178fba0cd49b21a8e440c60b03e2e45ade6b1`

Format: strict (json_object), 5 options

1. Even when he has a perfect chance to kill Claudius while he is praying, he chooses to wait.
2. Even when he has a perfect chance to kill Claudius while he is praying, he decides to pause.  — not judged, counts as 0 (fail: duplicate)
3. Even when he has a perfect chance to kill Claudius while he is praying, he opts to delay.  — not judged, counts as 0 (fail: duplicate)
4. Even when he has a perfect chance to kill Claudius while he is praying, he holds back.  — not judged, counts as 0 (fail: duplicate)
5. Even when he has a perfect chance to kill Claudius while he is praying, he waits instead.  — not judged, counts as 0 (fail: duplicate)
