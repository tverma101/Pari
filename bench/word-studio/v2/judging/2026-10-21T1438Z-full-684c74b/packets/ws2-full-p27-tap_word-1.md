# ws2-full-p27-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Plastic bags are cheap and easy to use, but they cause big problems for the environment. Most of them are only used once before they get thrown away. Because they are so light, they often blow out of trash cans and end up in rivers and oceans, where animals like sea turtles mistake them for food. A plastic bag can take hundreds of years to break down. Several states, such as California and New York, have already banned single-use plastic bags. I think every state should do the same and encourage people to bring reusable bags to the store.

Selected: Plastic bags are [[cheap]] and easy to use, but they cause big problems for the environment.

Instruction given to every model:

> Give 10 replacements for "cheap" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "cheap" without changing the rest of the sentence. Do not repeat "cheap" itself. Put the best options first.

## Output A

ref `o-fad8068b210a`, raw sha256 `fdddaa7e3d3a7d5c4079b0feff15fdb4d0cf79c4b41aeb0b94e772cd520e979a`

Format: lenient (json_object_then_text), 10 options, hit the token limit

1. inexpensive
2. low-cost
3. affordable
4. cheerful
5. budget-friendly
6. low-priced
7. affordable  — not judged, counts as 0 (fail: duplicate)
8. cost-effective
9. cheap  — not judged, counts as 0 (fail: echo)
10. low-cost  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-b1e91eb823ed`, raw sha256 `24d7d6ea979cdc2bb442ae9add644badcf5db44857bfb8ce56610a8a5283ab73`

Format: lenient (json_object), 10 options

1. affordable
2. inexpensive
3. low-cost
4. budget-friendly
5. cost-effective
6. economical
7. low-priced
8. frugal
9. economical choice
10. affordable option

## Output C

ref `o-fc1c36fd6f1e`, raw sha256 `e0d31b2f8347246db62fa8ece7cdb8b04930f33219ddaeafe1a32cd9b647b6c8`

Format: strict (json_object), 10 options

1. inexpensive
2. affordable
3. low cost
4. cost-effective
5. budget-friendly
6. economical
7. affordable  — not judged, counts as 0 (fail: duplicate)
8. low-priced
9. inexpensive  — not judged, counts as 0 (fail: duplicate)
10. cost-efficient
