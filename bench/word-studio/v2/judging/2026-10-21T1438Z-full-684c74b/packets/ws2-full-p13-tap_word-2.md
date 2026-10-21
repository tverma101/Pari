# ws2-full-p13-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> My grandmother is the person who has had the biggest impact on my life. She grew up on a farm in Mexico and never got the chance to finish school, but she is one of the smartest people I know. Every Sunday she cooks a huge meal for the whole family, and she makes everyone put their phones away so we can actually talk. She taught me that being kind is more important than being right. When I was having a hard time in middle school, she was the one who listened to me without judging. I want to be the kind of person who makes others feel welcome, just like she does.

Selected: Every Sunday she cooks a [[huge]] meal for the whole family, and she makes everyone put their phones away so we can actually talk.

Instruction given to every model:

> Give 10 replacements for "huge" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "huge" without changing the rest of the sentence. Do not repeat "huge" itself. Put the best options first.

## Output A

ref `o-0f9370524623`, raw sha256 `833524490732ae490400cbdf497e0eaa6b0cd62bebf5da697fdec19527404d6e`

Format: lenient (json_object), 10 options

1. massive
2. enormous
3. vast
4. immense
5. huge  — not judged, counts as 0 (fail: echo)
6. considerable
7. sizeable
8. considerable  — not judged, counts as 0 (fail: duplicate)
9. great
10. considerable  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-d2760feff327`, raw sha256 `9fb0bb42340447648e8873ad4daa565f1a127ff79a77dba4f7ce9b9301545cd7`

Format: strict (json_object), 10 options

1. immense
2. massive
3. large
4. extensive
5. bountiful
6. copious
7. vast
8. generous
9. substantial
10. considerable

## Output C

ref `o-82f42c9d70e8`, raw sha256 `127d1cb2593e12e42283f6c498f253204bf906c72029567ea4bd0137316a394a`

Format: strict (json_object), 10 options

1. massive
2. giant
3. large
4. vast
5. considerable
6. substantial
7. generous
8. abundant
9. imposing
10. grand
