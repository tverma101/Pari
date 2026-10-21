# ws2-full-p41-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Every year, millions of tons of plastic end up in the ocean. Over time, sunlight and waves break this plastic into tiny pieces called microplastics. These pieces are so small that fish and other sea animals eat them by accident. Scientists have even found microplastics in drinking water, salt, and human blood. We still do not fully understand how they affect our health, but some studies suggest they could cause inflammation. Reducing how much plastic we use is the most important step we can take to fix this problem.

Selected: These pieces are so small that fish and other sea animals eat them [[by accident]].

Instruction given to every model:

> Give 10 single words that can replace "by accident" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-7f4dffb1aa1e`, raw sha256 `8e72fd2f359487b5a81e8640fea2a4f192f990dd92a984732cfb89bfe3691c1f`

Format: strict (json_object), 10 options

1. accidentally
2. unintentionally
3. mistakenly
4. inadvertently
5. unwittingly
6. erroneously
7. involuntarily
8. unintentionally  — not judged, counts as 0 (fail: duplicate)
9. unconsciously
10. unintentionally  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-f707614fcc25`, raw sha256 `6b98f3b71715cb39b76173b774c5678eb3778280b3312dd3d785a28c8eaa0579`

Format: strict (json_object), 10 options

1. accidentally
2. mistakenly
3. unintentionally
4. unwittingly
5. incidentally
6. casually
7. blunderingly
8. carelessly
9. unintended
10. serendipitously

## Output C

ref `o-26ee9eddfd27`, raw sha256 `afa40f7b15fa3e68eb7dbb7e60b226cbfe14977016f901d81ce8fa4974557215`

Format: strict (json_object), 10 options

1. accidentally
2. mistakenly
3. by mistake  — not judged, counts as 0 (fail: too_many_words)
4. unknowingly
5. carelessly
6. unintentionally
7. by error  — not judged, counts as 0 (fail: too_many_words)
8. by oversight  — not judged, counts as 0 (fail: too_many_words)
9. by mistake  — not judged, counts as 0 (fail: duplicate, too_many_words)
10. unintentionally  — not judged, counts as 0 (fail: duplicate)
