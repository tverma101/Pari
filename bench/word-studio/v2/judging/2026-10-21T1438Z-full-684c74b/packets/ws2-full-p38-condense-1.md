# ws2-full-p38-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> During my junior year, I tore a ligament in my knee during a soccer game and had to miss the rest of the season. Soccer had always been a big part of who I was, so not being able to play made me feel lost. For the first few weeks, I barely wanted to leave my room. Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats. Every small win gave me a little more confidence. When I finally stepped back onto the field the next fall, I was stronger, both physically and mentally.

Selected: During my junior year, I tore a ligament in my knee during a soccer game and had to miss the rest of the season.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-d27eaa23ddb6`, raw sha256 `ea309650c8c39de3dd19a10c06f7a8841f2744cb4235909aa3fb9f4b6d48536f`

Format: strict (json_object), 5 options

1. In my junior year, I tore a knee ligament during a soccer game, forcing me to miss the rest of the season.
2. During my junior year, a soccer game caused me to tear my knee ligament, leading to the rest of the season being missed.
3. I tore a ligament in my knee during a soccer game in my junior year, missing the rest of the season.
4. My knee ligament tore during a soccer game in my junior year, causing me to miss the rest of the season.
5. Tearing a knee ligament in a soccer game during my junior year resulted in missing the rest of the season.

## Output B

ref `o-2b740260765c`, raw sha256 `b564232e6cefeabf0f4225d103ee5a0eacbdce76e68ebb0d4b294d3f55d7b901`

Format: strict (json_object), 5 options

1. During my junior year, I tore a knee ligament in a soccer game and missed the rest of the season.
2. In my junior year, a soccer game caused me to tear a knee ligament, forcing me to miss the season.
3. During my junior year, I tore a knee ligament playing soccer and had to skip the remainder of the season.
4. My junior year saw me tear a knee ligament in soccer, leaving me to miss the rest of the season.
5. During my junior year, a soccer injury tore my knee ligament, resulting in missing the rest of the season.

## Output C

ref `o-bb9f507f715f`, raw sha256 `dffb6c950a622cbc276eec1f3308a73c3c9d4824033860885610fd264a16ff94`

Format: strict (json_object), 5 options

1. I tore a ligament in my knee during a soccer game in my junior year and missed the rest of the season.
2. During my junior year, I injured my knee playing soccer and had to sit out the season.
3. In my junior year, a soccer game resulted in me tearing a ligament and missing the rest of the season.
4. I missed the rest of the soccer season after tearing a ligament in my knee during a junior year game.
5. During my junior year, a soccer injury led to me tearing a ligament and missing the rest of the season.  — not judged, counts as 0 (fail: duplicate)
