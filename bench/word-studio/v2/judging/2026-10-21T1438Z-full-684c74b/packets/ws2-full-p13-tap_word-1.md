# ws2-full-p13-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> My grandmother is the person who has had the biggest impact on my life. She grew up on a farm in Mexico and never got the chance to finish school, but she is one of the smartest people I know. Every Sunday she cooks a huge meal for the whole family, and she makes everyone put their phones away so we can actually talk. She taught me that being kind is more important than being right. When I was having a hard time in middle school, she was the one who listened to me without judging. I want to be the kind of person who makes others feel welcome, just like she does.

Selected: She grew up on a farm in Mexico and never got the chance to finish school, but she is one of the [[smartest]] people I know.

Instruction given to every model:

> Give 10 replacements for "smartest" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "smartest" without changing the rest of the sentence. Do not repeat "smartest" itself. Put the best options first.

## Output A

ref `o-cead60787cfd`, raw sha256 `e968a10c0a2ac483cd47d0b7c8a537e4922f0107033c451b3e97e9bf63cd4ad0`

Format: strict (json_object), 10 options

1. the most intelligent
2. the brightest
3. the most knowledgeable
4. the most clever
5. the most insightful
6. the most brilliant
7. the most learned
8. the most astute
9. the most sharp
10. the most wise

## Output B

ref `o-cb651bc994d5`, raw sha256 `0b8cfa48846adc1705a9727ca8ecd6abbe8a053ae8d9c6e9c602d662372ec726`

Format: strict (json_object), 10 options

1. intelligent
2. wise
3. clever
4. brilliant
5. knowledgeable
6. shrewd
7. sophisticated
8. experienced
9. exemplary
10. accomplished

## Output C

ref `o-8c3ceb96f579`, raw sha256 `57fb3f13806a01c1ef330febd20d60f5285d96cc3f07cd2f1e5c26e4268cf9f2`

Format: strict (json_object), 10 options

1. most intelligent
2. most knowledgeable
3. most brilliant
4. most astute
5. most erudite
6. most sagacious
7. most perceptive
8. most insightful
9. most astute  — not judged, counts as 0 (fail: duplicate)
10. most clever
