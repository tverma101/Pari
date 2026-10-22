# ws2-full-p41-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Every year, millions of tons of plastic end up in the ocean. Over time, sunlight and waves break this plastic into tiny pieces called microplastics. These pieces are so small that fish and other sea animals eat them by accident. Scientists have even found microplastics in drinking water, salt, and human blood. We still do not fully understand how they affect our health, but some studies suggest they could cause inflammation. Reducing how much plastic we use is the most important step we can take to fix this problem.

Selected: These pieces are so small that fish and other sea animals eat them [[by accident]].

Instruction given to every model:

> Give 10 single words that can replace "by accident" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-093043a3cf8b`, raw sha256 `7738e8dd35fcfd3468d5b520c59f017af639da265a40a5af7c773ef48e2a0932`

Format: strict (json_object), 10 options

1. accidentally
2. unintentionally
3. unknowingly
4. mistakenly
5. inadvertently
6. unwittingly
7. unwillingly
8. unconsciously
9. unintentionally  — not judged, counts as 0 (fail: duplicate)
10. mistakenly  — not judged, counts as 0 (fail: duplicate)
