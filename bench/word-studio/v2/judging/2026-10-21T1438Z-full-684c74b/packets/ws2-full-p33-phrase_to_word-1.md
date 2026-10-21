# ws2-full-p33-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen. I help him with his homework, make him dinner, and make sure he goes to bed on time. Some days it is stressful, especially when I have a big test the next morning. But taking care of him has made me more patient and responsible than most kids my age. I have learned how to manage my time and stay calm when things do not go as planned. My brother looks up to me, and that makes all the hard work worth it.

Selected: My brother [[looks up to]] me, and that makes all the hard work worth it.

Instruction given to every model:

> Give 10 single words that can replace "looks up to" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-eef1357a5802`, raw sha256 `bdcf9bfd0bd241df60cb36e2d943fe0f66b21174f7a3d493524b8f60eb05fd2f`

Format: strict (json_object), 10 options

1. admires
2. reveres
3. respects
4. is inspired by  — not judged, counts as 0 (fail: too_many_words)
5. looks up to  — not judged, counts as 0 (fail: echo, too_many_words)
6. deems admirable  — not judged, counts as 0 (fail: too_many_words)
7. holds in high regard  — not judged, counts as 0 (fail: too_many_words)
8. feels inspired by  — not judged, counts as 0 (fail: too_many_words)
9. values
10. views as an example  — not judged, counts as 0 (fail: too_many_words)

## Output B

ref `o-8b65d7d57f57`, raw sha256 `fe896cae00d3185e14e2c449c01790e6fc73c3f1756507205a60c156b8546cba`

Format: strict (json_object), 10 options

1. respects
2. admires
3. pays attention to  — not judged, counts as 0 (fail: too_many_words)
4. values
5. heeds
6. observes
7. takes cues from  — not judged, counts as 0 (fail: too_many_words)
8. finds inspiration in  — not judged, counts as 0 (fail: too_many_words)
9. sees as a role model  — not judged, counts as 0 (fail: too_many_words)
10. views as a mentor  — not judged, counts as 0 (fail: too_many_words)

## Output C

ref `o-6f2a5a2a9305`, raw sha256 `05d9c9b05f7f6bce0f014308f256e378f6831ef78c5a167474eb16d28c38e1bd`

Format: strict (json_object), 10 options

1. admires
2. respects
3. trusts
4. follows
5. values
6. cherishes
7. resembles
8. watches
9. observes
10. honors
