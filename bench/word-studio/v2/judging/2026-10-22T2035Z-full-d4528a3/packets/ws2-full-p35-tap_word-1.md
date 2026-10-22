# ws2-full-p35-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> On July 20, 1969, Neil Armstrong became the first person to walk on the moon. The Apollo 11 mission was the result of years of hard work by thousands of scientists, engineers, and astronauts. The United States wanted to beat the Soviet Union in the space race, which was part of the larger Cold War. Millions of people around the world watched the landing live on television. The mission showed what humans can do when they work together toward a big goal. It also led to new technologies that we still use today.

Selected: The United States wanted to [[beat]] the Soviet Union in the space race, which was part of the larger Cold War.

Instruction given to every model:

> Give 10 replacements for "beat" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "beat" without changing the rest of the sentence. Do not repeat "beat" itself. Put the best options first.

## Output A

ref `o-b2799ee46dfb`, raw sha256 `fd2b1930981a8ef119523428ef2c6a97d4bdfadc45b228cf59d3517c797916ac`

Format: strict (json_object), 10 options

1. defeat
2. surpass
3. outdo
4. beat  — not judged, counts as 0 (fail: echo)
5. top
6. surpass  — not judged, counts as 0 (fail: duplicate)
7. trump
8. outstrip
9. edge out
10. beat  — not judged, counts as 0 (fail: duplicate, echo)
