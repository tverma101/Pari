# ws2-screen-p03-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> The printing press was one of the most important inventions in history. Before Johannes Gutenberg built his press around 1440, books had to be copied by hand, which took a really long time. Because of this, books were very expensive and only rich people and churches could have them. After the press was invented, books could be made much faster and for a lot less money. More people started learning how to read, and new ideas spread across Europe quickly. Some historians say that the press helped cause big changes like the Reformation and the Scientific Revolution. Without it, the world we live in today would probably be very different.

Selected: Before Johannes Gutenberg built his press around 1440, books had to be copied by hand, which took a really long time.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-cb854404583c`, raw sha256 `6c5ada001bfdc74f18055c343aac2151aa5ffcf7a2e5a19567de0cfc33d2fc2d`

Format: strict (json_object), 5 options

1. Before Gutenberg built his press around 1440, hand-copying books took a long time.  — check: name_dropped
2. Before Gutenberg's press around 1440, hand-copying books was very slow.  — check: name_dropped
3. Before Gutenberg built his press around 1440, copying books by hand took a long time.  — not judged, counts as 0 (fail: duplicate)
4. Before Gutenberg's press around 1440, books had to be copied by hand slowly.  — check: name_dropped
5. Before Gutenberg built his press around 1440, books took a long time to copy by hand.  — check: name_dropped
