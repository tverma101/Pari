# ws2-full-p11-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> During the Industrial Revolution, a lot of children worked in factories and mines instead of going to school. Some of them were only six or seven years old, and they often worked twelve hours a day. The conditions were very dangerous, and many children got hurt by the machines or became sick from breathing in dust. Factory owners liked hiring kids because they could pay them less money than adults. Over time, reformers wrote articles and gave speeches about how bad the situation was. In Britain, the Factory Act of 1833 finally set limits on how many hours children could work.

Selected: In Britain, the Factory Act of 1833 finally [[set limits on]] how many hours children could work.

Instruction given to every model:

> Give 10 single words that can replace "set limits on" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-e6d85bb0bec9`, raw sha256 `0400fe2883f4e99a0a6da7b9cc32c1ed3a3fbff8c957465cc20c16cc1d88d929`

Format: strict (json_object), 10 options

1. established
2. imposed
3. dictated
4. determined
5. ensured
6. fixed
7. established  — not judged, counts as 0 (fail: duplicate)
8. required
9. stipulated
10. fixed  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-54ece74bdb64`, raw sha256 `f15e2bcc9c57def9848fafb59053af68cba6ecb151ccebcbfe71fd6a9edbaea5`

Format: strict (json_object), 10 options

1. capped
2. restricted
3. limited
4. bound
5. curbed
6. constrained
7. regulated
8. governed
9. controlled
10. restricted  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-edbe01557706`, raw sha256 `9be37943d110b97d91b91dfca410a8442668d8b16de08a4f87fcb8b8bea33de2`

Format: strict (json_object), 10 options

1. impose
2. establish
3. implement
4. dictate
5. prescribe
6. regulate
7. stipulate
8. limit
9. define
10. enforce
