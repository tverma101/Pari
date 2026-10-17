# ws2-screen-p07-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Macbeth, Shakespeare shows how wanting power too much can destroy a person. At the start of the play, Macbeth is a loyal soldier who fights bravely for King Duncan. After the witches tell him he will be king, he cannot stop thinking about it. Lady Macbeth pushes him to kill Duncan, and he finally agrees even though he feels guilty. Once he becomes king, he keeps killing people because he is afraid of losing what he has. By the end, Macbeth says that life is "a tale told by an idiot," which shows how empty he feels. His story is a warning about what happens when ambition gets out of control.

Selected: By the end, Macbeth says that life is "a tale told by an idiot," which shows how [[empty]] he feels.

Instruction given to every model:

> Give 10 replacements for "empty" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "empty" without changing the rest of the sentence. Do not repeat "empty" itself. Put the best options first.

## Output A

ref `o-d49ae48b5651`, raw sha256 `d0808f8b17454a3c6e7192ff75a2b6baba1b900a484d352de610449349db91fe`

Format: strict (json_object), 11 options

1. meaningless
2. void
3. lifeless
4. barren
5. devoid
6. painless
7. insignificant
8. void of purpose
9. lifelessness
10. void of substance
11. meaningless existence  — not judged, counts as 0 (fail: beyond_requested)

## Output B

ref `o-5472cd37acd7`, raw sha256 `665b857787cee3be92feae141934a338944af51bc9e9a20c4c8da54b52df1b98`

Format: strict (json_object), 10 options

1. vacant
2. dim
3. hopeless
4. certain
5. worthless
6. naked
7. faded
8. desolate
9. untrue
10. perishable

## Output C

ref `o-d0ed84a48074`, raw sha256 `ae6630ae1f64650f6a5d8b9bb2758394e13df39b948a06e0e8a59e2c4a9db637`

Format: strict (json_object), 10 options

1. void
2. empty  — not judged, counts as 0 (fail: echo)
3. void  — not judged, counts as 0 (fail: duplicate)
4. empty  — not judged, counts as 0 (fail: duplicate, echo)
5. void  — not judged, counts as 0 (fail: duplicate)
6. empty  — not judged, counts as 0 (fail: duplicate, echo)
7. void  — not judged, counts as 0 (fail: duplicate)
8. empty  — not judged, counts as 0 (fail: duplicate, echo)
9. void  — not judged, counts as 0 (fail: duplicate)
10. empty  — not judged, counts as 0 (fail: duplicate, echo)

## Output D

ref `o-fac40f05bec4`, raw sha256 `3fddfa38c4be7ed6bda1bb94ba53fa7d8312e47483df8bdf21bf9f649cc9f44d`

Format: lenient (json_object_then_text), 10 options

1. vacant
2. meaningless
3. empty  — not judged, counts as 0 (fail: echo)
4. useless
5. unfulfilling
6. unreal
7. meaningless  — not judged, counts as 0 (fail: duplicate)
8. unimportant
9. devoid
10. insignificant

## Output E

ref `o-67acd0c5a1d7`, raw sha256 `23e93308f25cd59e8526bf405129a821350f72a0b9176c000b449048ea2942ac`

Format: strict (json_object), 10 options

1. hollow
2. meaningless
3. void
4. vacuous
5. worthless
6. pointless
7. insignificant
8. devoid
9. fruitless
10. void of purpose
