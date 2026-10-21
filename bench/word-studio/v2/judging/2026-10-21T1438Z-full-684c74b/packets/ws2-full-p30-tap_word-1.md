# ws2-full-p30-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Vaccines work by teaching the immune system how to fight a disease before a person ever gets sick. They contain a weak or harmless piece of a germ, which the body learns to recognize. If the real germ shows up later, the immune system can attack it quickly. Thanks to vaccines, diseases like smallpox have been wiped out, and polio is almost gone. When enough people in a community are vaccinated, it also protects those who cannot get the shot, like newborn babies. This is called herd immunity.

Selected: They contain a [[weak]] or harmless piece of a germ, which the body learns to recognize.

Instruction given to every model:

> Give 10 replacements for "weak" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "weak" without changing the rest of the sentence. Do not repeat "weak" itself. Put the best options first.

## Output A

ref `o-488bd36a0348`, raw sha256 `9b7c78c32876d7b48d98f97e3975cde6e0441910d3ab3ce91fad45819546edff`

Format: strict (json_object), 10 options

1. mild
2. gentle
3. weak  — not judged, counts as 0 (fail: echo)
4. light
5. infantile
6. moderate
7. feeble
8. soft
9. fragile
10. inoffensive

## Output B

ref `o-1a9dba0f2935`, raw sha256 `ddb769b2ad42cd769d6107173b98732570900f11c32bde3cd96c5b5d2ae3a705`

Format: strict (json_object), 10 options

1. frail
2. insubstantial
3. mild
4. diminished
5. subdued
6. scant
7. modest
8. vulnerable
9. inconsequential
10. minor

## Output C

ref `o-da8c70d28ece`, raw sha256 `ded39c2042e62895710b098b00f35de28dc3707290cf7eceaf8ad4778c3439c8`

Format: strict (json_object), 10 options

1. minimal
2. mild
3. gentle
4. slight
5. inert
6. non-threatening
7. benign
8. dormant
9. tame
10. harmless
