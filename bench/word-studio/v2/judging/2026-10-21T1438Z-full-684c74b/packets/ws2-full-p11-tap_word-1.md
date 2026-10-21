# ws2-full-p11-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> During the Industrial Revolution, a lot of children worked in factories and mines instead of going to school. Some of them were only six or seven years old, and they often worked twelve hours a day. The conditions were very dangerous, and many children got hurt by the machines or became sick from breathing in dust. Factory owners liked hiring kids because they could pay them less money than adults. Over time, reformers wrote articles and gave speeches about how bad the situation was. In Britain, the Factory Act of 1833 finally set limits on how many hours children could work.

Selected: The conditions were very [[dangerous]], and many children got hurt by the machines or became sick from breathing in dust.

Instruction given to every model:

> Give 10 replacements for "dangerous" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "dangerous" without changing the rest of the sentence. Do not repeat "dangerous" itself. Put the best options first.

## Output A

ref `o-03b3757be04f`, raw sha256 `c5f252969fd7822866fb56bd7b92c2eb5463e298fc8644b894264282e93bf29c`

Format: lenient (json_object), 10 options

1. harsh
2. risky
3. unsafe
4. unhealthy
5. hazardous
6. perilous
7. threatening
8. toxic
9. unpleasant
10. dangerous  — not judged, counts as 0 (fail: echo)

## Output B

ref `o-c3f1f7362ecc`, raw sha256 `751d82efe61361fe5ad66f8aa3fd6e9e36786956e508e9fea7012a209608168e`

Format: strict (json_object), 10 options

1. hazardous
2. perilous
3. unsafe
4. risky
5. threatening
6. hostile
7. unfavorable
8. threatening conditions
9. high risk
10. potentially harmful

## Output C

ref `o-a1efdf0c0c74`, raw sha256 `3c25bb17993873f2a7094fbf54bf9c5c9098ba19ec4f45e916a6408fc232eb13`

Format: strict (json_object), 10 options

1. unsafe
2. hazardous
3. risky
4. perilous
5. treacherous
6. dreadful
7. harmful
8. hazard-filled
9. inherently unsafe
10. extremely perilous
