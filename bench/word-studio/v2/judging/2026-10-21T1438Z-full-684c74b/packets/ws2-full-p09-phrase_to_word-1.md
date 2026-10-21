# ws2-full-p09-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Some people think school uniforms are a bad idea, but I think they help students in many ways. First, uniforms make it harder for kids to judge each other based on how much their clothes cost. When everyone wears the same thing, students from poor families do not stand out as much. Second, uniforms save time in the morning because students do not have to pick out an outfit every day. Critics say that uniforms take away students' freedom to express themselves. However, students can still show who they are through their hobbies, their writing, and the way they treat others.

Selected: Second, uniforms save time in the morning because students do not have to [[pick out]] an outfit every day.

Instruction given to every model:

> Give 10 single words that can replace "pick out" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-8689936d9724`, raw sha256 `a62b1a9df11ff76498d03acc63f80490d8836dba702750b542820f25dace3f3e`

Format: strict (json_object), 10 options

1. choose
2. select
3. pick
4. determine
5. pick  — not judged, counts as 0 (fail: duplicate)
6. choose  — not judged, counts as 0 (fail: duplicate)
7. select  — not judged, counts as 0 (fail: duplicate)
8. determine  — not judged, counts as 0 (fail: duplicate)
9. choose  — not judged, counts as 0 (fail: duplicate)
10. pick  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-833be38befe7`, raw sha256 `5fbb818ff2ac34aa5efe52ef2e64457cea6f60ee1ff1f1a92cd05c8106157f84`

Format: strict (json_object), 10 options

1. select
2. choose
3. decide
4. determine
5. opt
6. pick
7. pick out  — not judged, counts as 0 (fail: echo, too_many_words)
8. choose out  — not judged, counts as 0 (fail: too_many_words)
9. select out  — not judged, counts as 0 (fail: too_many_words)
10. decide out  — not judged, counts as 0 (fail: too_many_words)

## Output C

ref `o-86b9c7578c4a`, raw sha256 `fce56c0a2925061bab3460b908c39065ac28a3d6d333b00634f44c9e82ff7835`

Format: strict (json_object), 10 options

1. select
2. choose
3. find
4. decide
5. wear
6. buy
7. select  — not judged, counts as 0 (fail: duplicate)
8. opt
9. find  — not judged, counts as 0 (fail: duplicate)
10. choose  — not judged, counts as 0 (fail: duplicate)
