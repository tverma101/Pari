# ws2-full-p26-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Every Saturday for the past two years, I have volunteered at a food bank in my neighborhood. At first, I only went because I needed community service hours for school. But after a few weeks, I started to really care about the people who came in. Many of them were working parents who just did not have enough money at the end of the month. One woman told me that the food we gave her was the only reason her kids had dinner that week. Hearing that made me realize how many people in my own town are struggling. Now I want to study social work so I can help families like hers.

Selected: Hearing that made me [[realize]] how many people in my own town are struggling.

Instruction given to every model:

> Give 10 replacements for "realize" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "realize" without changing the rest of the sentence. Do not repeat "realize" itself. Put the best options first.

## Output A

ref `o-174691344ae7`, raw sha256 `892642ec6d7e451fe8b0bff766d7d1d013244e09cf8bdecbe3254f704d61a415`

Format: strict (json_object), 10 options

1. realized
2. knew
3. understood
4. saw
5. became aware
6. recognized
7. discovered
8. grasped
9. learned
10. took to heart

## Output B

ref `o-8a842a56f66b`, raw sha256 `c54a40b65bd71e31bb519c22d2f39e953ac629899e893f3b14b241d19c9e728f`

Format: lenient (json_object_then_text), 10 options

1. understand
2. acknowledge
3. appreciate
4. notice
5. realize  — not judged, counts as 0 (fail: echo)
6. realize  — not judged, counts as 0 (fail: duplicate, echo)
7. perceive
8. grasp
9. see
10. realize  — not judged, counts as 0 (fail: duplicate, echo)

## Output C

ref `o-9256af2cdfd1`, raw sha256 `5c988a36cbf42ce053774eb1f62814116a55805013c7a3e58170c6c8125042ce`

Format: strict (json_object), 10 options

1. Acknowledge
2. Understand
3. Appreciate
4. Comprehend
5. See
6. Notice
7. Grasp
8. Perceive
9. Recognize
10. Be aware of
