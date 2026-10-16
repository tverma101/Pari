# ws2-screen-p07-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Macbeth, Shakespeare shows how wanting power too much can destroy a person. At the start of the play, Macbeth is a loyal soldier who fights bravely for King Duncan. After the witches tell him he will be king, he cannot stop thinking about it. Lady Macbeth pushes him to kill Duncan, and he finally agrees even though he feels guilty. Once he becomes king, he keeps killing people because he is afraid of losing what he has. By the end, Macbeth says that life is "a tale told by an idiot," which shows how empty he feels. His story is a warning about what happens when ambition gets out of control.

Selected: Lady Macbeth [[pushes]] him to kill Duncan, and he finally agrees even though he feels guilty.

Instruction given to every model:

> Give 10 replacements for "pushes" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "pushes" without changing the rest of the sentence. Do not repeat "pushes" itself. Put the best options first.

## Output A

ref `o-7841319b694a`, raw sha256 `b4e08ec870850c8e2352a69ade65f00f9180846a2e27d61707b36a1693336e59`

Format: strict (json_object), 10 options

1. urges
2. forces
3. demands
4. inspires
5. drives
6. pressures
7. urges  — not judged, counts as 0 (fail: duplicate)
8. forces  — not judged, counts as 0 (fail: duplicate)
9. demands  — not judged, counts as 0 (fail: duplicate)
10. inspires  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-231f159cc2dd`, raw sha256 `7eea7dca834dc8c95733a3b53950a578c17e75041fd78f93a3eab2d24d98dddc`

Format: strict (json_object), 10 options

1. persuades
2. insists
3. coaxes
4. encourages
5. urges
6. drives
7. compels
8. dissuades
9. coaxes him
10. presses upon

## Output C

ref `o-460d91b9fb07`, raw sha256 `8edfddc642006a6d40b1ba489f0a9733d22c17ebb3ceb0df6fe667876fa223bb`

Format: strict (json_object), 10 options

1. encourages
2. urges
3. presses
4. drives
5. compels
6. presses  — not judged, counts as 0 (fail: duplicate)
7. compels  — not judged, counts as 0 (fail: duplicate)
8. urges  — not judged, counts as 0 (fail: duplicate)
9. drives  — not judged, counts as 0 (fail: duplicate)
10. pushes  — not judged, counts as 0 (fail: echo)

## Output D

ref `o-f8a6fc756d64`, raw sha256 `8e740134b416a847696f9ddbfddadeef1647ccd2df88995ee4f1a96232b18230`

Format: strict (json_object), 10 options

1. urges
2. presses
3. instigates
4. drives
5. compels
6. encourages
7. prods
8. motives
9. stimulates
10. pushes forward

## Output E

ref `o-ebbbf06a6f3b`, raw sha256 `f8b1e127b2c147021b4482676fdfca8fca68f137a442653ff339891846a9059c`

Format: strict (json_object), 10 options

1. urges
2. encourages
3. persuades
4. nagging
5. coaxes
6. prods
7. urges  — not judged, counts as 0 (fail: duplicate)
8. stimulates
9. incentivizes
10. goads
