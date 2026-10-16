# ws2-screen-p03-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> The printing press was one of the most important inventions in history. Before Johannes Gutenberg built his press around 1440, books had to be copied by hand, which took a really long time. Because of this, books were very expensive and only rich people and churches could have them. After the press was invented, books could be made much faster and for a lot less money. More people started learning how to read, and new ideas spread across Europe quickly. Some historians say that the press helped cause big changes like the Reformation and the Scientific Revolution. Without it, the world we live in today would probably be very different.

Selected: After the press was invented, books could be made much faster and for a lot less money.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-3d24c307aa7c`, raw sha256 `d42c4be8fa6845871226a83362147f1b66f48bc7026202f4821276925ab85f18`

Format: strict (json_object), 5 options

1. Once Gutenberg created his press, books became much quicker to produce and far cheaper to make.
2. With Gutenberg's invention, books were no longer heavy or costly; they could now be produced rapidly.  — check: negation_changed
3. After Gutenberg built his press, copying books was done much faster and for a fraction of the usual price.
4. When Gutenberg invented his press, the speed and cost of making books improved significantly.
5. Gutenberg's press allowed books to be made much faster and at a much lower cost than before.

## Output B

ref `o-c8bd5c3178ab`, raw sha256 `96b041d095b71557a6ccaf118052786afa4f123c171abcc17d3175651f278500`

Format: strict (json_object), 5 options

1. Once the press was created, books could be produced much more quickly and at a significantly lower cost.
2. Following the invention of the press, books became much faster to make and far cheaper.
3. After the press was built, it allowed books to be manufactured much faster and for much less money.
4. With the invention of the press, books could be made at a much greater speed and for a lot less money.
5. Once the press came into existence, books could be produced much more rapidly and at a much lower price.

## Output C

ref `o-5bd460a96877`, raw sha256 `ad34184af91f12399634740847608308d9c8e09872d3b5c8219fe65068988c20`

Format: strict (json_object), 5 options

1. After the press was invented, books could be made much faster and for a lot less money.  — not judged, counts as 0 (fail: echo)
2. With the press, books could be made much faster and for a lot less money.  — not judged, counts as 0 (fail: duplicate)
3. The press allowed books to be made much faster and for a lot less money.  — not judged, counts as 0 (fail: duplicate)
4. Once the press was invented, books could be made much faster and for a lot less money.  — not judged, counts as 0 (fail: duplicate)
5. After the press was invented, books could be made much faster and for a lot less money.  — not judged, counts as 0 (fail: duplicate, echo)

## Output D

ref `o-e796500f5e8d`, raw sha256 `9c94408e197c074313ffca401d399622a9fa9f41acfaf7954219fe683501d056`

Format: lenient (json_object_then_text), 5 options

1. Books could be produced more quickly and at a lower cost after the invention of the press.
2. With the press, books could be made faster and cheaper than ever before.
3. After Gutenberg's press was introduced, the production of books became significantly quicker and less expensive.
4. The invention of the press led to books being made more quickly and at a lower cost.
5. The press allowed for books to be made faster and more cheaply than before.

## Output E

ref `o-704d06d0c1a8`, raw sha256 `84cb4a4cc737e1a382c09491ab93b4a9aac285fda06a4b02145a22be67460373`

Format: strict (json_object), 5 options

1. Once the printing press was created, book production became significantly quicker and more affordable.
2. With the advent of the printing press, books could be produced rapidly and at a reduced cost.
3. The invention of the printing press led to faster and cheaper book manufacturing.
4. Post-invention, the printing press enabled the mass production of books at a lower price.
5. Following the development of the printing press, books could be printed more swiftly and inexpensively.
