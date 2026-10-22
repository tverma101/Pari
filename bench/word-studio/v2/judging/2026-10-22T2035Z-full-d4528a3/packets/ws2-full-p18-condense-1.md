# ws2-full-p18-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Joining the robotics team in tenth grade was one of the best choices I ever made. Our first competition was a disaster because our robot stopped working in the middle of the match. I felt embarrassed, and I wanted to quit the team right then. Instead, our coach told us to figure out what went wrong and try again. We spent weeks testing every part until we found a loose wire in the motor. At our next competition, the robot worked perfectly and we made it to the finals. That experience taught me that failing is just part of getting better.

Selected: Our first competition was a disaster because our robot stopped working in the middle of the match.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-d54e5f21a2aa`, raw sha256 `80cbd4a3c8f5fe183b63ef85207c0c242788017707c78b999345f9622b95efc0`

Format: strict (json_object), 5 options

1. Our first competition was a disaster when the robot stopped mid-match.
2. Our first competition was a disaster because the robot failed mid-match.  — check: negation_changed
3. The robot stopped mid-match, making our first competition a disaster.
4. Our first competition was a disaster after the robot stopped mid-match.  — not judged, counts as 0 (fail: duplicate)
5. Our first competition was a disaster when the robot broke down mid-match.  — not judged, counts as 0 (fail: duplicate)
