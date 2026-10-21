# ws2-full-p34-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> College athletes bring in millions of dollars for their schools, but for a long time they were not allowed to earn any of it. Big football and basketball programs sell tickets, jerseys, and TV rights, while the players who make it all possible get nothing except a scholarship. Many athletes spend more than forty hours a week on their sport, which makes it hard to keep a part-time job. In 2021, new rules finally let athletes make money from their name and image. I think this was a fair change, and schools should go even further by sharing some of their profits with players.

Selected: I think this was a [[fair]] change, and schools should go even further by sharing some of their profits with players.

Instruction given to every model:

> Give 10 replacements for "fair" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "fair" without changing the rest of the sentence. Do not repeat "fair" itself. Put the best options first.

## Output A

ref `o-0cae379fa4ce`, raw sha256 `2fc7d16ea3e5ba3c0160c9d649c69de9bf12d1449af24211e85710df321d413f`

Format: strict (json_object), 10 options

1. justifiable
2. equitable
3. reasonable
4. balanced
5. just
6. appropriate
7. sound
8. prudent
9. equitable  — not judged, counts as 0 (fail: duplicate)
10. deserved

## Output B

ref `o-f4187121504a`, raw sha256 `d8d685a64e2b79d654bf029fb2c296302f92944b90dfc05f15216707e513673f`

Format: strict (json_object), 10 options

1. equitable
2. just
3. equitable  — not judged, counts as 0 (fail: duplicate)
4. balanced
5. equitable  — not judged, counts as 0 (fail: duplicate)
6. appropriate
7. fair  — not judged, counts as 0 (fail: echo)
8. equal
9. fair  — not judged, counts as 0 (fail: duplicate, echo)
10. reasonable

## Output C

ref `o-5499825f8940`, raw sha256 `c4c684a7dd8eff4b878793655a2a81e626ecf14b71db92d603aeb9ee4f3443e9`

Format: strict (json_object), 10 options

1. right
2. just
3. reasonable
4. appropriate
5. acceptable
6. logical
7. just  — not judged, counts as 0 (fail: duplicate)
8. reasonable  — not judged, counts as 0 (fail: duplicate)
9. appropriate  — not judged, counts as 0 (fail: duplicate)
10. just  — not judged, counts as 0 (fail: duplicate)
