# ws2-full-p38-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> During my junior year, I tore a ligament in my knee during a soccer game and had to miss the rest of the season. Soccer had always been a big part of who I was, so not being able to play made me feel lost. For the first few weeks, I barely wanted to leave my room. Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats. Every small win gave me a little more confidence. When I finally stepped back onto the field the next fall, I was stronger, both physically and mentally.

Selected: Every [[small win]] gave me a little more confidence.

Instruction given to every model:

> Give 10 single words that can replace "small win" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-ff9c9beddfc4`, raw sha256 `ae67a4aa2444de8b0f49300d1d878c08378dea157fccfea2357be603d3cbe83a`

Format: strict (json_object), 10 options

1. accomplishment
2. achievement
3. success
4. victory
5. progress
6. milestone
7. achievement  — not judged, counts as 0 (fail: duplicate)
8. progress  — not judged, counts as 0 (fail: duplicate)
9. success  — not judged, counts as 0 (fail: duplicate)
10. triumph

## Output B

ref `o-60b85dc8bf43`, raw sha256 `56e87f36fd454ee097aada43b9fe4cc310e4b63b77c94b6cbdd8839d00b89cdd`

Format: strict (json_object), 10 options

1. victory
2. success
3. triumph
4. achievement
5. progress
6. milestone
7. accomplishment
8. victory  — not judged, counts as 0 (fail: duplicate)
9. win
10. feat

## Output C

ref `o-91b80ff4cac8`, raw sha256 `429286987dc2984fe2d570a4d9fbe546955491f7b4604ff3868e54486c66ccd1`

Format: strict (json_object), 10 options

1. victory
2. achievement
3. success
4. progress
5. momentum
6. step
7. gains
8. advance
9. feat
10. accomplishment
