# ws2-full-p29-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The fight for women's right to vote in the United States lasted for more than seventy years. It officially began at the Seneca Falls Convention in 1848, where activists like Elizabeth Cady Stanton demanded equal rights for women. For decades, suffragists gave speeches, marched in parades, and even went to jail for their cause. Many people at the time thought that women were too emotional to make decisions about politics. Finally, in 1920, the 19th Amendment was passed, which gave women the right to vote. This victory showed that ordinary people can change the law if they keep pushing for it.

Selected: This victory showed that [[ordinary]] people can change the law if they keep pushing for it.

Instruction given to every model:

> Give 10 replacements for "ordinary" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "ordinary" without changing the rest of the sentence. Do not repeat "ordinary" itself. Put the best options first.

## Output A

ref `o-6e83762b8c6c`, raw sha256 `a664f37e4239b83471583222d00da7f52e4313a1c19724158e90ad2412da26aa`

Format: strict (json_object), 14 options

1. common
2. regular
3. typical
4. average
5. normal
6. general
7. standard
8. unremarkable
9. usual
10. non-extraordinary
11. mundane  — not judged, counts as 0 (fail: beyond_requested)
12. commonplace  — not judged, counts as 0 (fail: beyond_requested)
13. everyday  — not judged, counts as 0 (fail: beyond_requested)
14. normal citizens  — not judged, counts as 0 (fail: beyond_requested)

## Output B

ref `o-ef55a0c01be7`, raw sha256 `41607180fcad68e1cd92c254b3dcfc976c7d72d14136ace3c89a452d21430589`

Format: lenient (json_object_then_text), 10 options

1. regular
2. typical
3. common
4. ordinary  — not judged, counts as 0 (fail: echo)
5. normal
6. typical  — not judged, counts as 0 (fail: duplicate)
7. run-of-the-mill
8. average
9. conventional
10. everyday

## Output C

ref `o-a3abd8ca8013`, raw sha256 `028996b67254589add24b91b78e4f779d472d5d69e3a8326d2790402c64717e6`

Format: strict (json_object), 10 options

1. common
2. regular
3. everyday
4. typical
5. average
6. commonplace
7. non-elite
8. every
9. day-to-day
10. regular citizens
