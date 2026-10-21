# ws2-full-p20-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Romeo and Juliet is often called a love story, but it is also a story about how acting too fast can lead to disaster. Romeo and Juliet meet, fall in love, and get married in less than a week. Neither of them stops to think about what their families will do when they find out. Friar Laurence even warns Romeo that "they stumble that run fast," but Romeo does not listen. When Romeo hears that Juliet is dead, he kills himself right away instead of waiting to learn the truth. If the two young lovers had slowed down, the play might have had a happy ending.

Selected: Romeo and Juliet is often called a love story, but it is also a story about how acting too [[fast]] can lead to disaster.

Instruction given to every model:

> Give 10 replacements for "fast" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "fast" without changing the rest of the sentence. Do not repeat "fast" itself. Put the best options first.

## Output A

ref `o-1ed0e94972fb`, raw sha256 `db56d5da99e160e02c8a3a222f09610ef0c277092bf30d05ca5fe882fcd4a68f`

Format: strict (json_object), 11 options

1. hastily
2. swiftly
3. quickly
4. immediately
5. without delay
6. without hesitation
7. in a hurry
8. with urgency
9. on the double
10. right away
11. without stopping  — not judged, counts as 0 (fail: beyond_requested)

## Output B

ref `o-f43a86cd831f`, raw sha256 `2bedf3d8e4a5cfb03f0104ff7a9f61bee73e6391ebbad1ba039ca3f66f2b363e`

Format: strict (json_object), 10 options

1. hasty
2. quick
3. rapid
4. swift
5. immediate
6. rushed
7. precipitous
8. impetuous
9. hurried
10. speedy

## Output C

ref `o-859957b5f7c3`, raw sha256 `4f6574c63991affd6088430935e530622b22bad93510f70d56bdfd9a80159aff`

Format: lenient (json_object), 10 options

1. rapidly
2. quickly
3. hastily
4. swiftly
5. sooner
6. expeditiously
7. immediately
8. promptly
9. with haste
10. with alacrity
