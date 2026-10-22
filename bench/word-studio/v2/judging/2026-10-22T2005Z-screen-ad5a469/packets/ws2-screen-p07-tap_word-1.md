# ws2-screen-p07-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Macbeth, Shakespeare shows how wanting power too much can destroy a person. At the start of the play, Macbeth is a loyal soldier who fights bravely for King Duncan. After the witches tell him he will be king, he cannot stop thinking about it. Lady Macbeth pushes him to kill Duncan, and he finally agrees even though he feels guilty. Once he becomes king, he keeps killing people because he is afraid of losing what he has. By the end, Macbeth says that life is "a tale told by an idiot," which shows how empty he feels. His story is a warning about what happens when ambition gets out of control.

Selected: Lady Macbeth [[pushes]] him to kill Duncan, and he finally agrees even though he feels guilty.

Instruction given to every model:

> Give 10 replacements for "pushes" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "pushes" without changing the rest of the sentence. Do not repeat "pushes" itself. Put the best options first.

## Output A

ref `o-5fde726854b8`, raw sha256 `cf524e08935c4a7c55eacc444f7bded364620ce8bc801aafb762735a4ebfb5db`

Format: strict (json_object), 10 options

1. urges
2. presses
3. goads
4. prods
5. compels
6. encourages
7. drives
8. insists he
9. pushes him
10. urges him

## Output B

ref `o-1510a93c14f7`, raw sha256 `b4e08ec870850c8e2352a69ade65f00f9180846a2e27d61707b36a1693336e59`

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
