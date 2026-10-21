# ws2-full-p15-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Of Mice and Men, George and Lennie share a dream of owning a small farm together. For George, the dream gives him a reason to keep working hard even though his life is lonely. For Lennie, it is mostly about getting to take care of rabbits. Most of the other workers on the ranch have no one, so they are surprised that the two men travel together. Steinbeck uses their friendship to show how important it is to have someone who cares about you. When the dream falls apart at the end, it shows how hard it was for poor workers to change their lives during the Great Depression.

Selected: When the dream falls apart at the end, it shows how [[hard]] it was for poor workers to change their lives during the Great Depression.

Instruction given to every model:

> Give 10 replacements for "hard" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "hard" without changing the rest of the sentence. Do not repeat "hard" itself. Put the best options first.

## Output A

ref `o-60d9a5a9e194`, raw sha256 `fcf02a39949f7799ea10aef1d0d1ce276560d57853eabb2d8b74b20a5510aa58`

Format: strict (json_object), 10 options

1. difficult
2. challenging
3. impossible
4. tough
5. arduous
6. bleak
7. grueling
8. daunting
9. rigorous
10. demanding

## Output B

ref `o-8ec812247cc9`, raw sha256 `6be01e190b3b2c031c34604bf080d9f87669708f79fe5d7e4002ee684976215f`

Format: strict (json_object), 10 options

1. difficult
2. challenging
3. strenuous
4. arduous
5. tough
6. demanding
7. difficult  — not judged, counts as 0 (fail: duplicate)
8. grueling
9. difficult  — not judged, counts as 0 (fail: duplicate)
10. stringent

## Output C

ref `o-44bbf96f3e84`, raw sha256 `d1235f6f253a0eab5dfd597a40e1fee8d4466418c48d29409b76aee8d72c4c0e`

Format: strict (json_object), 10 options

1. difficult
2. challenging
3. arduous
4. painstaking
5. tough
6. hard-fought
7. demanding
8. ardent
9. strenuous
10. exigent
