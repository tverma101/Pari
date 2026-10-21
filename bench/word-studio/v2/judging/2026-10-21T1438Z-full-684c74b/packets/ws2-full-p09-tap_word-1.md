# ws2-full-p09-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Some people think school uniforms are a bad idea, but I think they help students in many ways. First, uniforms make it harder for kids to judge each other based on how much their clothes cost. When everyone wears the same thing, students from poor families do not stand out as much. Second, uniforms save time in the morning because students do not have to pick out an outfit every day. Critics say that uniforms take away students' freedom to express themselves. However, students can still show who they are through their hobbies, their writing, and the way they treat others.

Selected: First, uniforms make it harder for kids to [[judge]] each other based on how much their clothes cost.

Instruction given to every model:

> Give 10 replacements for "judge" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "judge" without changing the rest of the sentence. Do not repeat "judge" itself. Put the best options first.

## Output A

ref `o-3c3d354e0c6c`, raw sha256 `77fc8b7ad3b6fe4cc6619f9be396d051514b66c97da6562712b3bb6d107bda8f`

Format: strict (json_object), 11 options

1. compare
2. evaluate
3. judge  — not judged, counts as 0 (fail: echo)
4. assess
5. decide
6. opinion
7. opinion on
8. opinion of
9. opinion regarding
10. opinion about
11. opinion on the matter  — not judged, counts as 0 (fail: beyond_requested, too_many_words)

## Output B

ref `o-485699fb51c9`, raw sha256 `a0922835ae0aac17c16909032403e9e590c9fd98b06871002def191c4a9cdc5f`

Format: lenient (json_object), 10 options

1. assess
2. evaluate
3. contemplate
4. appraise
5. measure
6. consider
7. evaluate  — not judged, counts as 0 (fail: duplicate)
8. gauge
9. estimate
10. judge  — not judged, counts as 0 (fail: echo)

## Output C

ref `o-769e8a52126d`, raw sha256 `2fefa8d18cbf98a72167b4838a8d4a7590715d0507503e959b025ae4b0ed8d04`

Format: strict (json_object), 10 options

1. evaluate
2. assess
3. evaluate based on
4. determine
5. rate
6. compare
7. differentiate
8. distinguish
9. evaluate each other
10. assess each other
