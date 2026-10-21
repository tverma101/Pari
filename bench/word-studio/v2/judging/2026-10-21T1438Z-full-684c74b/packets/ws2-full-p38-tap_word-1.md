# ws2-full-p38-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> During my junior year, I tore a ligament in my knee during a soccer game and had to miss the rest of the season. Soccer had always been a big part of who I was, so not being able to play made me feel lost. For the first few weeks, I barely wanted to leave my room. Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats. Every small win gave me a little more confidence. When I finally stepped back onto the field the next fall, I was stronger, both physically and mentally.

Selected: Soccer had always been a big part of who I was, so not being able to play made me feel [[lost]].

Instruction given to every model:

> Give 10 replacements for "lost" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "lost" without changing the rest of the sentence. Do not repeat "lost" itself. Put the best options first.

## Output A

ref `o-ead3f90ee1c5`, raw sha256 `42222fe15ad72036e00162303e67e5a8b5c6869277058aa9ade240fa3817b768`

Format: strict (json_object), 10 options

1. bereft
2. empty
3. lonely
4. forlorn
5. dejected
6. dispirited
7. disenfranchised
8. depressed
9. wistful
10. disenheartened

## Output B

ref `o-b2dede931550`, raw sha256 `511bbc7e03152751113219981706e4b3a434655815230138464715d7b0e6f25f`

Format: strict (json_object), 10 options

1. disoriented
2. uncertain
3. adrift
4. confused
5. directionless
6. lost  — not judged, counts as 0 (fail: echo)
7. unsettled
8. aimless
9. disconnected
10. bewildered

## Output C

ref `o-64ddb114957a`, raw sha256 `1ea3f47356d3f0d3d26f4bc30edffacf9ab0980e4cf673779f76a0afed65b9fa`

Format: lenient (json_object), 10 options

1. unsettled
2. disoriented
3. disconnected
4. adrift
5. isolated
6. detached
7. disengaged
8. disengaged  — not judged, counts as 0 (fail: duplicate)
9. disconnected  — not judged, counts as 0 (fail: duplicate)
10. adrift  — not judged, counts as 0 (fail: duplicate)
