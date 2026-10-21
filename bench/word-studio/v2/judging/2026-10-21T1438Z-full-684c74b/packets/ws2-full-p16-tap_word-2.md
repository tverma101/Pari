# ws2-full-p16-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The Montgomery Bus Boycott was a key event in the civil rights movement. It started in December 1955 when Rosa Parks was arrested for refusing to give up her seat to a white passenger. In response, Black residents of Montgomery stopped riding the city buses for more than a year. Many people walked miles to work every day or set up carpools so that they would not have to use the buses. The boycott hurt the bus company because it lost most of its riders. In 1956, the Supreme Court ruled that segregation on buses was unconstitutional, and the boycott ended in victory.

Selected: The boycott [[hurt]] the bus company because it lost most of its riders.

Instruction given to every model:

> Give 10 replacements for "hurt" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "hurt" without changing the rest of the sentence. Do not repeat "hurt" itself. Put the best options first.

## Output A

ref `o-be0be57aa1b3`, raw sha256 `e578c06d2c7fc2d6e656907e6a8a9b2646d9cbfa3fb6692ad3533390b72a83e4`

Format: strict (json_object), 10 options

1. damaged
2. affected
3. impacted
4. weakened
5. struck
6. disadvantaged
7. injured
8. disrupted
9. hindered
10. hampered

## Output B

ref `o-0c8bf7d13958`, raw sha256 `f5a67707bd6b953852588ed7e1cce8906755c13a747d7ab09a4a9db45b01c794`

Format: strict (json_object), 10 options

1. damaged
2. harmed
3. disrupted
4. weakened
5. affected
6. struck
7. impacted
8. disadvantaged
9. negatively influenced
10. caused trouble

## Output C

ref `o-177b31e77769`, raw sha256 `8366270d2445cc2a1391af225d602659b789d27ef0227ecb92c0d8a390a968ab`

Format: strict (json_object), 10 options

1. damaged
2. impacted
3. struck
4. suffered
5. affected
6. struck a blow
7. caused distress
8. led to financial loss  — not judged, counts as 0 (fail: too_many_words)
9. led to financial losses  — not judged, counts as 0 (fail: duplicate, too_many_words)
10. wreaked havoc
