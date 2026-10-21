# ws2-full-p44-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Artificial intelligence tools like chatbots are becoming common in schools, and teachers are not sure how to handle them. Some teachers worry that students will use AI to write their essays and never learn how to think for themselves. Others believe AI can be a useful tutor that explains hard ideas in a simple way. In my experience, AI is most helpful when I use it to check my understanding, not to do the work for me. Schools should teach students how to use these tools honestly instead of banning them completely.

Selected: Artificial intelligence tools like chatbots are becoming common in schools, and teachers are not sure how to [[handle]] them.

Instruction given to every model:

> Give 10 replacements for "handle" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "handle" without changing the rest of the sentence. Do not repeat "handle" itself. Put the best options first.

## Output A

ref `o-4f0e6a438c05`, raw sha256 `b28e64392d09c9bfd8f833de9f1a9c4949c0cdfe6b504b2e451b39412912da07`

Format: lenient (json_object), 10 options

1. manage
2. deal with
3. cope with
4. tackle
5. address
6. navigate
7. manage  — not judged, counts as 0 (fail: duplicate)
8. work with
9. deal with  — not judged, counts as 0 (fail: duplicate)
10. cope with  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-8ce4047bd931`, raw sha256 `840e8770b95e03b8e3725f0e167cff4cf26f2ea21bc3dfaa2e42d5a80ac29ecb`

Format: lenient (json_object_then_text), 10 options

1. deal with
2. manage
3. use
4. work with
5. interact with
6. utilize
7. handle  — not judged, counts as 0 (fail: echo)
8. tackle
9. work with  — not judged, counts as 0 (fail: duplicate)
10. work alongside

## Output C

ref `o-41bde1c2e4e8`, raw sha256 `79fa22f5bc2e64fdd156bf7fde95daee4f8fbe9bd3a5f8d83efd34f896ce082c`

Format: strict (json_object), 10 options

1. manage
2. deal with
3. address
4. cope with
5. deal with  — not judged, counts as 0 (fail: duplicate)
6. manage  — not judged, counts as 0 (fail: duplicate)
7. tackle
8. address  — not judged, counts as 0 (fail: duplicate)
9. cope with  — not judged, counts as 0 (fail: duplicate)
10. deal with  — not judged, counts as 0 (fail: duplicate)
