# ws2-full-p18-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Joining the robotics team in tenth grade was one of the best choices I ever made. Our first competition was a disaster because our robot stopped working in the middle of the match. I felt embarrassed, and I wanted to quit the team right then. Instead, our coach told us to figure out what went wrong and try again. We spent weeks testing every part until we found a loose wire in the motor. At our next competition, the robot worked perfectly and we made it to the finals. That experience taught me that failing is just part of getting better.

Selected: Our first competition was a disaster because our robot stopped working in the middle of the match.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-3b8ca717829f`, raw sha256 `7e34aa5933ebda011aab3556aa918b235494967cd21ffbe21ffc3a815e798dac`

Format: lenient (json_object_then_text), 5 options

1. Our robot malfunctioned mid-match during our first competition.
2. Our first competition ended in disaster when our robot failed.  — check: negation_changed
3. The first competition was a disaster as our robot broke.
4. Our robot failed mid-match, turning our first competition into a disaster.  — check: negation_changed
5. A disaster struck at our first competition when our robot stopped.

## Output B

ref `o-b9ad90f7e2bd`, raw sha256 `486552b3aef0960f4bb311a49c64b6af8b1b8ca52d23694dc183e32818f29adb`

Format: strict (json_object), 5 options

1. Our first match was a disaster; our robot malfunctioned in the middle.
2. Disaster struck our first competition; our robot failed mid-match.  — check: negation_changed
3. Our first competition disaster: robot stopped mid-match.
4. First competition disaster: robot malfunctioned mid-game.
5. Our first competition disaster: robot stopped mid-match.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-bf86c380420f`, raw sha256 `ac27aaf187290ad3df4070ea04c81522cc531c6f4b87e5021ce355702a9716e6`

Format: strict (json_object), 5 options

1. Our first competition ended in disaster as our robot malfunctioned mid-match.
2. The robot failed spectacularly during our first competition.  — check: negation_changed
3. Our first competition was a disaster due to our robot's failure mid-match.  — check: negation_changed
4. We experienced a major setback during our first competition when the robot stopped working.
5. Our first competition was a disaster because our robot stopped working halfway through the match.
