# ws2-full-p18-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Joining the robotics team in tenth grade was one of the best choices I ever made. Our first competition was a disaster because our robot stopped working in the middle of the match. I felt embarrassed, and I wanted to quit the team right then. Instead, our coach told us to figure out what went wrong and try again. We spent weeks testing every part until we found a loose wire in the motor. At our next competition, the robot worked perfectly and we made it to the finals. That experience taught me that failing is just part of getting better.

Selected: Instead, our coach told us to [[figure out]] what went wrong and try again.

Instruction given to every model:

> Give 10 single words that can replace "figure out" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-f272207a164f`, raw sha256 `ef734c87199002d8fa2aabb6f3160916f8c6ca7b96cde90566962ea92e355783`

Format: strict (json_object), 10 options

1. determine
2. discover
3. identify
4. solve
5. find
6. pinpoint
7. track down  — not judged, counts as 0 (fail: too_many_words)
8. uncover
9. diagnose
10. work out  — not judged, counts as 0 (fail: too_many_words)
