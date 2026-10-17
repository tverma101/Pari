# ws2-screen-p03-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> The printing press was one of the most important inventions in history. Before Johannes Gutenberg built his press around 1440, books had to be copied by hand, which took a really long time. Because of this, books were very expensive and only rich people and churches could have them. After the press was invented, books could be made much faster and for a lot less money. More people started learning how to read, and new ideas spread across Europe quickly. Some historians say that the press helped cause big changes like the Reformation and the Scientific Revolution. Without it, the world we live in today would probably be very different.

Selected: Before Johannes Gutenberg built his press around 1440, books had to be copied by hand, which took a really long time.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-3850a897f0b8`, raw sha256 `440a00ca68183a37e7a7292b4060a9d42141a050dd188c1f35932988173448e9`

Format: strict (json_object), 5 options

1. Books were copied by hand before Gutenberg's press, taking a long time.  — check: number_changed, name_dropped
2. Before Gutenberg's press, books required manual copying, a time-consuming process.  — check: number_changed, name_dropped
3. Prior to Gutenberg's invention, books were manually copied, a laborious task.  — check: number_changed, name_dropped
4. Before Gutenberg's press, books were copied by hand, a lengthy process.  — check: number_changed, name_dropped
5. Prior to the invention of Gutenberg's press, books were copied by hand, which was a time-consuming endeavor.  — check: number_changed, name_dropped

## Output B

ref `o-297c861f0c45`, raw sha256 `82b762eac5bd8b392619efa783494f264b7d8cd2112f0c6fc609e3c893748dfe`

Format: strict (json_object), 5 options

1. Before Gutenberg's press, hand-copying books was slow.  — check: number_changed, name_dropped
2. Hand-copying books pre-Gutenberg was time-consuming.  — check: number_changed, name_dropped
3. Before 1440, books took long to copy by hand.  — check: name_dropped
4. Books before Gutenberg's press were slow to produce.  — check: number_changed, name_dropped
5. Hand-copied books before 1440 took time.  — check: name_dropped

## Output C

ref `o-64c8a8a9a21b`, raw sha256 `3378aedf87b7c1abb429ee04c18eb1faf308cc7db096461a91b2476fb84b1a28`

Format: strict (json_object), 5 options

1. Before Gutenberg built his press in 1440, books were copied by hand and took a long time.  — check: name_dropped
2. Before Gutenberg's 1440 press, books were copied by hand and took a long time.  — check: name_dropped
3. Before Gutenberg built his press around 1440, books required hand copying, which took a long time.  — check: name_dropped
4. Before Gutenberg's press around 1440, books were copied by hand and took a long time.  — not judged, counts as 0 (fail: duplicate)
5. Before Gutenberg's 1440 press, books were copied by hand and took a long time.  — not judged, counts as 0 (fail: duplicate)

## Output D

ref `o-52c6d0df567d`, raw sha256 `94dfe37b7380ff2f5169fe5660254a0dac6b48e8f039e246352b9de54690d754`

Format: strict (json_object), 5 options

1. The press was made around 1440 by Johannes Gutenberg. Before this, books were copied by hand and took a very long time.  — not judged, counts as 0 (fail: not_shorter)
2. Johannes Gutenberg built his press around 1440. Before this, books were copied by hand and took a very long time.
3. Around 1440, Johannes Gutenberg built his press. Before this, books were copied by hand and took a very long time.  — not judged, counts as 0 (fail: duplicate)
4. Johannes Gutenberg built his press around 1440. Before this, books were copied by hand and took a very long time.  — not judged, counts as 0 (fail: duplicate)
5. Around 1440, Johannes Gutenberg built his press. Before this, books were copied by hand and took a very long time.  — not judged, counts as 0 (fail: duplicate)

## Output E

ref `o-5268aef8c36b`, raw sha256 `06e80a02ce2c6b68c8370209f4a6766fb2981c588b639b4715fa232bc3d31683`

Format: strict (json_object), 5 options

1. Before 1440, books were copied by hand.  — check: name_dropped
2. Before Gutenberg's press, copying books was slow.  — check: number_changed, name_dropped
3. Copying books by hand was slow before 1440.  — check: name_dropped
4. Hand-copying books was slow before 1440.  — check: name_dropped
5. Before 1440, copying books by hand was slow.  — check: name_dropped
