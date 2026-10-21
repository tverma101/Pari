# ws2-full-p47-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> I will be the first person in my family to go to college, and that comes with a lot of pressure. My parents did not have the chance to continue their education because they had to start working when they were teenagers. They have always told me that school is the key to a better life. Filling out applications was confusing because no one at home had done it before, so I had to ask my counselor for help with almost every step. Even though the process was hard, it made me more determined to succeed. I want to make my parents proud and show my younger cousins that college is possible for them too.

Selected: [[Filling out]] applications was confusing because no one at home had done it before, so I had to ask my counselor for help with almost every step.

Instruction given to every model:

> Give 10 single words that can replace "Filling out" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-90bfb30312c3`, raw sha256 `89b8fa692a2c45ea15fae2827f9e786d2ac4133cd8d77d05394dc53efcd187e0`

Format: strict (json_object), 10 options

1. submitting
2. completing
3. filling
4. issuing
5. generating
6. processing
7. issuing  — not judged, counts as 0 (fail: duplicate)
8. submitting  — not judged, counts as 0 (fail: duplicate)
9. filling  — not judged, counts as 0 (fail: duplicate)
10. completing  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-61151c1fe19f`, raw sha256 `18e8608fe0515fb875bab3454f089ec5a471185dce7d48b18476ecb98c845d8e`

Format: strict (json_object), 10 options

1. Completing
2. Submitting
3. Filling
4. Completing  — not judged, counts as 0 (fail: duplicate)
5. Filing  — not judged, counts as 0 (fail: duplicate)
6. Submitting  — not judged, counts as 0 (fail: duplicate)
7. Filling  — not judged, counts as 0 (fail: duplicate)
8. Filling  — not judged, counts as 0 (fail: duplicate)
9. Filling  — not judged, counts as 0 (fail: duplicate)
10. Filling  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-f43474671a23`, raw sha256 `30acb2f27d6aa0f3e012e4939b7014a9e1ac0d69f15320b8dd19d869e4023d5a`

Format: strict (json_object), 10 options

1. Submitting
2. Completing
3. Applying
4. Filling
5. Processing
6. Handling
7. Managing
8. Doing
9. Working
10. Trying
