# ws2-full-p31-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Many students say they have too much homework, and I agree that it can sometimes do more harm than good. After a full day of classes, students still have to spend three or four hours on assignments every night. This leaves them with very little time for sports, family, or sleep. Some homework is helpful because it lets students practice what they learned in class. But when teachers give busywork just to fill time, students get tired and stop caring about learning. Schools should set limits on homework so that it is useful and not overwhelming.

Selected: Some homework is [[helpful]] because it lets students practice what they learned in class.

Instruction given to every model:

> Give 10 replacements for "helpful" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "helpful" without changing the rest of the sentence. Do not repeat "helpful" itself. Put the best options first.

## Output A

ref `o-e71f313238bb`, raw sha256 `2d84e9b06c9c3aa44ba50d20d53f2bed06408984da2d6797cd6289a616831f24`

Format: strict (json_object), 10 options

1. beneficial
2. educational
3. valuable
4. useful
5. productive
6. advantageous
7. benefiting
8. advantageous  — not judged, counts as 0 (fail: duplicate)
9. beneficial  — not judged, counts as 0 (fail: duplicate)
10. enriching

## Output B

ref `o-759e2d751d15`, raw sha256 `9fdc85c25de6cc8df62c1c5dc973888964c259a5a74e87033fa25f1ce06007ae`

Format: lenient (json_object), 10 options

1. beneficial
2. educational
3. constructive
4. advantageous
5. practical
6. useful
7. progressive
8. valuable
9. productive
10. effective

## Output C

ref `o-85e1300157e4`, raw sha256 `390e9e6c907aba960b3f5d52a7887eee814a05b0c5b375acdbac48956176f6e2`

Format: strict (json_object), 10 options

1. beneficial
2. useful
3. advantageous
4. constructive
5. profitable
6. valuable
7. productive
8. advantageous  — not judged, counts as 0 (fail: duplicate)
9. beneficial  — not judged, counts as 0 (fail: duplicate)
10. helpful  — not judged, counts as 0 (fail: echo)
