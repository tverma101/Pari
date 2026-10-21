# ws2-full-p46-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Most people know that exercise is good for the body, but it is also good for the brain. When we exercise, our hearts pump more blood to the brain, which brings it extra oxygen. Studies have shown that regular exercise can improve memory and help people focus. It can also lower stress and make people feel happier because the body releases chemicals called endorphins. Even a short walk of twenty minutes can make a difference. For students, this means that taking breaks to move around might actually help them study better.

Selected: Most people know that exercise is good for the body, but it is also [[good]] for the brain.

Instruction given to every model:

> Give 10 replacements for "good" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "good" without changing the rest of the sentence. Do not repeat "good" itself. Put the best options first.

## Output A

ref `o-c31d4a9a89af`, raw sha256 `2c44253fadc787898e67bc0d8e36a869d0ee41c451e77560bafe288f812f7eb6`

Format: strict (json_object), 10 options

1. beneficial
2. advantageous
3. positive
4. healthy
5. helpful
6. useful
7. advantageous  — not judged, counts as 0 (fail: duplicate)
8. favorable
9. beneficial  — not judged, counts as 0 (fail: duplicate)
10. positive  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-81fa9cf39303`, raw sha256 `d77d9d6d39bc9412780a7fdab41527dd481ad59fdf8b487d24c0c2682af20ae3`

Format: lenient (json_object_then_text), 10 options

1. beneficial
2. advantageous
3. helpful
4. benefits
5. benefits  — not judged, counts as 0 (fail: duplicate)
6. positive
7. advantageous  — not judged, counts as 0 (fail: duplicate)
8. helpful  — not judged, counts as 0 (fail: duplicate)
9. beneficial  — not judged, counts as 0 (fail: duplicate)
10. beneficial  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-fc6c53556995`, raw sha256 `338fec01147aa7235a9cf17dfa4cbfec74cc16da182741c408d661eb4a782961`

Format: lenient (json_object), 10 options

1. beneficial
2. advantageous
3. helpful
4. positive
5. favorable
6. proven
7. beneficial  — not judged, counts as 0 (fail: duplicate)
8. useful
9. productive
10. rewarding
