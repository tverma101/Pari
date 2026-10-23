# ws2-screen-p08-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Last summer I got my first job working at a small pizza restaurant near my house. At first I thought it would be easy, but I quickly found out that it was a lot of work. On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.

Selected: On busy nights we had to make dozens of pizzas in just a few hours, and customers got [[upset]] if their food was late.

Instruction given to every model:

> Give 10 replacements for "upset" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "upset" without changing the rest of the sentence. Do not repeat "upset" itself. Put the best options first.

## Output A

ref `o-7c502d291503`, raw sha256 `95ab13d623095b5f2ed4826c4f4677554be01a7065bcadd2af1239094c027452`

Format: strict (json_object), 10 options

1. angry
2. frustrated
3. annoyed
4. mad
5. stressed
6. irritated
7. furious
8. exasperated
9. annoyed  — not judged, counts as 0 (fail: duplicate)
10. stressed  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-fbe6a01a51e1`, raw sha256 `5bdb4bead1a791099cd68ea4fc507d73c9802f6f3a8afe11b5d503fa29a82b49`

Format: strict (json_object), 10 options

1. angry
2. annoyed
3. frustrated
4. disappointed
5. displeased
6. irritated
7. disgruntled
8. dissatisfied
9. discomfited
10. disappointed  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-dcd0aea18328`, raw sha256 `95d55b67178a631b8f17479f9523cc705de7835a156bf34fbe6f80efa3bb0a82`

Format: strict (json_object), 10 options

1. irritated
2. displeased
3. annoyed
4. frustrated
5. disgruntled
6. discontented
7. unhappy
8. dissatisfied
9. irritated  — not judged, counts as 0 (fail: duplicate)
10. irritated and annoyed

## Output D

ref `o-3a43acb8a657`, raw sha256 `7daa8d3dfdc6558b497b6f68a1da3f8af1c1623d90911461e5691c5ce690fd0e`

Format: strict (json_object), 10 options

1. annoyed
2. frustrated
3. angry
4. disappointed
5. irritated
6. worried
7. saddened
8. confused
9. unhappy
10. bothered

## Output E

ref `o-2baa4b9d5e61`, raw sha256 `da024cb4fa6e8ba02d61b87dd68d6a85128b20be1532b00a657e7983d34cc077`

Format: strict (json_object), 10 options

1. frustrated
2. annoyed
3. irritated
4. disappointed
5. annoyed  — not judged, counts as 0 (fail: duplicate)
6. upset  — not judged, counts as 0 (fail: echo)
7. frustrated  — not judged, counts as 0 (fail: duplicate)
8. annoyed  — not judged, counts as 0 (fail: duplicate)
9. irritated  — not judged, counts as 0 (fail: duplicate)
10. disappointed  — not judged, counts as 0 (fail: duplicate)
