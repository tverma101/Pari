# ws2-full-p34-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> College athletes bring in millions of dollars for their schools, but for a long time they were not allowed to earn any of it. Big football and basketball programs sell tickets, jerseys, and TV rights, while the players who make it all possible get nothing except a scholarship. Many athletes spend more than forty hours a week on their sport, which makes it hard to keep a part-time job. In 2021, new rules finally let athletes make money from their name and image. I think this was a fair change, and schools should go even further by sharing some of their profits with players.

Selected: College athletes [[bring in]] millions of dollars for their schools, but for a long time they were not allowed to earn any of it.

Instruction given to every model:

> Give 10 single words that can replace "bring in" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-8f58591c5657`, raw sha256 `fc2fbc3a478e6c06cda81180e1e76a9b7ca39fbb1d79963ca127acaec78d6aff`

Format: strict (json_object), 10 options

1. generate
2. produce
3. earn
4. make
5. create
6. amass
7. accumulate
8. procure
9. obtain
10. secure

## Output B

ref `o-28fce8343ce7`, raw sha256 `422f27a0954df43e964413be9be6f9b492016badd3081a4a72e2dc8fb1ee4ce0`

Format: strict (json_object), 10 options

1. generate
2. collect
3. secure
4. gather
5. raise
6. produce
7. earn
8. fetch
9. secure  — not judged, counts as 0 (fail: duplicate)
10. procure

## Output C

ref `o-afc0fd901868`, raw sha256 `8a8349db4de2dcaade17eeb33da11a43b7fa41c7d35478b62b0f5f1caae74cbb`

Format: strict (json_object), 10 options

1. generate
2. amass
3. produce
4. create
5. accumulate
6. derive
7. reap
8. yield
9. harvest
10. produce  — not judged, counts as 0 (fail: duplicate)
