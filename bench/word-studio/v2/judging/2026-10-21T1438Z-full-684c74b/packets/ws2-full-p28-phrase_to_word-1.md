# ws2-full-p28-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> In Lord of the Flies, a group of boys stranded on an island slowly lose their sense of right and wrong. At first, they choose Ralph as their leader and try to follow rules, like only speaking when they hold the conch shell. As time goes on, Jack becomes more interested in hunting than in keeping the signal fire going. More and more boys join Jack's tribe because it seems more fun than doing chores. By the end, the boys have turned violent, and two of them are dead. Golding uses the story to suggest that people can quickly become savage when there are no rules to control them.

Selected: In Lord of the Flies, a group of boys stranded on an island slowly lose their [[sense of right and wrong]].

Instruction given to every model:

> Give 10 single words that can replace "sense of right and wrong" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-09c46d087666`, raw sha256 `c2c2102910a285cc16314723d9a96c0b66fc04c15def1f5579922a88f700a9cd`

Format: strict (json_object), 10 options

1. moral compass  — not judged, counts as 0 (fail: too_many_words)
2. ethical guidelines  — not judged, counts as 0 (fail: too_many_words)
3. principles of justice  — not judged, counts as 0 (fail: too_many_words)
4. code of conduct  — not judged, counts as 0 (fail: too_many_words)
5. norms of behavior  — not judged, counts as 0 (fail: too_many_words)
6. code of ethics  — not judged, counts as 0 (fail: too_many_words)
7. moral standards  — not judged, counts as 0 (fail: too_many_words)
8. rules of decency  — not judged, counts as 0 (fail: too_many_words)
9. ethical norms  — not judged, counts as 0 (fail: too_many_words)
10. principled behavior  — not judged, counts as 0 (fail: too_many_words)

## Output B

ref `o-b8377e685c30`, raw sha256 `6a41fdc43b2a4d60d79d3e1d60df6b42b718768ef02f2be317e2c6503b4844d0`

Format: strict (json_object), 10 options

1. morality
2. ethics
3. judgment
4. virtue
5. principles
6. integrity
7. conduct
8. behavior
9. morals
10. code

## Output C

ref `o-b049838b600f`, raw sha256 `c1f19c6ba688c5d755b6b6c8059d12288ec79bcaea7f4b8ee418f35e0949b79b`

Format: strict (json_object), 10 options

1. moral compass  — not judged, counts as 0 (fail: too_many_words)
2. ethics
3. principles
4. values
5. conscience
6. righteousness
7. virtue
8. morality
9. judgment
10. code
