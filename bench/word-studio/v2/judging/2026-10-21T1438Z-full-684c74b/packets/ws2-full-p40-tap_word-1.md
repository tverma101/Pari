# ws2-full-p40-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> The Silk Road was not one single road but a network of trade routes that connected China to the Middle East and Europe. Merchants traveled these routes for more than a thousand years, carrying goods like silk, spices, and paper. But the Silk Road did more than move products from one place to another. It also helped spread religions, languages, and inventions between very different cultures. For example, Buddhism traveled from India to China along these routes. In many ways, the Silk Road was an early example of how the world is connected.

Selected: In many ways, the Silk Road was an early example of how the world is [[connected]].

Instruction given to every model:

> Give 10 replacements for "connected" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "connected" without changing the rest of the sentence. Do not repeat "connected" itself. Put the best options first.

## Output A

ref `o-cc80df8375a5`, raw sha256 `da8967cd9b35cce173a681e74036eeff02b9a8f51ff5f6cc8364aea65a047d5b`

Format: strict (json_object), 10 options

1. interlinked
2. interwoven
3. interconnected
4. interdependent
5. interrelated
6. interfused
7. interlaced
8. intertangled
9. interconnected  — not judged, counts as 0 (fail: duplicate)
10. intertwined

## Output B

ref `o-0f7b342b73ef`, raw sha256 `9cc745826dd6d3590931eee4f330cdaa6c4dc8c3d702a155696778e62ead4fad`

Format: lenient (json_object_then_text), 10 options

1. linked
2. connected  — not judged, counts as 0 (fail: echo)
3. linked  — not judged, counts as 0 (fail: duplicate)
4. linked  — not judged, counts as 0 (fail: duplicate)
5. connected  — not judged, counts as 0 (fail: duplicate, echo)
6. linked  — not judged, counts as 0 (fail: duplicate)
7. linked  — not judged, counts as 0 (fail: duplicate)
8. connected  — not judged, counts as 0 (fail: duplicate, echo)
9. linked  — not judged, counts as 0 (fail: duplicate)
10. linked  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-831e39f37142`, raw sha256 `0faa7422b84a010b5f8d6083f7cae9f842862798bd29717e858be5482cf4d76c`

Format: strict (json_object), 10 options

1. interlinked
2. bound together
3. united
4. linked
5. intertwined
6. joined
7. united as one
8. tied together
9. interwoven
10. bound
