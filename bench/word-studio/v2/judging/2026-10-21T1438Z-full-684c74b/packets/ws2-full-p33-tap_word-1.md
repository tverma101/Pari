# ws2-full-p33-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen. I help him with his homework, make him dinner, and make sure he goes to bed on time. Some days it is stressful, especially when I have a big test the next morning. But taking care of him has made me more patient and responsible than most kids my age. I have learned how to manage my time and stay calm when things do not go as planned. My brother looks up to me, and that makes all the hard work worth it.

Selected: Some days it is [[stressful]], especially when I have a big test the next morning.

Instruction given to every model:

> Give 10 replacements for "stressful" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "stressful" without changing the rest of the sentence. Do not repeat "stressful" itself. Put the best options first.

## Output A

ref `o-5d944867376b`, raw sha256 `2a25ecee8c772526b2df98fda1020ab1bf84d59e5c990399984857ab77d226ca`

Format: strict (json_object), 10 options

1. challenging
2. tough
3. difficult
4. anxious
5. aggravating
6. annoying
7. frustrating
8. overwhelming
9. exhausting
10. daunting

## Output B

ref `o-2036877d5bf4`, raw sha256 `561db8649aed352a40ba89ef4a8435974f4820da624ddc97dee2111c78556bb7`

Format: lenient (json_object), 10 options

1. challenging
2. demanding
3. arduous
4. burdensome
5. trying
6. difficult
7. strenuous
8. tough
9. hard
10. trying  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-28dc1a989e7b`, raw sha256 `9af947830fee7ae540d21ead92a0ffc91c0ad0c32dde2543e3ab8db51ecbfe8f`

Format: strict (json_object), 10 options

1. intense
2. tense
3. challenging
4. demanding
5. difficult
6. overwhelming
7. trying
8. hard
9. frustrating
10. pressing
