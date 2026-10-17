# ws2-screen-p05-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> When my family moved to the United States, I was eleven years old and I only knew a few words in English. The first few months at school were really hard because I could not understand what the teachers were saying. I felt alone most of the time, and I was too scared to talk in class. My English teacher, Ms. Alvarez, started staying after school to help me with reading and writing. She never made me feel stupid when I made mistakes. Little by little, I started to understand more and even make some friends. Now I am the one who helps new students when they first get here, because I know how it feels.

Selected: She never made me feel stupid when I made mistakes.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-9832d39c6dcf`, raw sha256 `bfa72d28e82ce92b17ed142c5ee5e43c40a0d1de525dd39f96f8938aa84c84d6`

Format: strict (json_object), 5 options

1. She never made me feel foolish when I made mistakes.
2. She never made me feel inadequate when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
3. She never made me feel dumb when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
4. She never made me feel silly when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
5. She never made me feel ashamed when I made mistakes.  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-727a086d9e54`, raw sha256 `867d26a941bee662d784d97a2ea90fc6d1f4266a5c80c9ef78a848df6f129bd7`

Format: strict (json_object), 5 options

1. She never made me feel inadequate when I made mistakes.
2. She never made me feel like I was failing when I made mistakes.
3. She never made me feel discouraged when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
4. She never made me feel embarrassed when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
5. She never made me feel like I was a burden when I made mistakes.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-35770027e376`, raw sha256 `8bf2937bc37c631bb2f6561ab36b6dd45abbd036ad2c1611a5ee13ad0f9bbe4e`

Format: strict (json_object), 5 options

1. Ms. Alvarez always encouraged me despite my errors.  — check: negation_changed
2. Mistakes didn't make me feel foolish with Ms. Alvarez's help.
3. Ms. Alvarez's support never made me feel inadequate.
4. Ms. Alvarez always supported me, even when I made mistakes.  — check: negation_changed
5. Ms. Alvarez never made me feel inferior when I erred.

## Output D

ref `o-3be891c7345b`, raw sha256 `9b6624802897a82e71949b5d3608cceb03c366636d2bb4293beed31b28ce685e`

Format: strict (json_object), 5 options

1. Ms. Alvarez always treated me kindly, so I never felt stupid when I made mistakes.
2. Ms. Alvarez stayed late to help me, and she never let me feel foolish for my errors.
3. Ms. Alvarez was always nice to me, so I never felt stupid when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
4. Ms. Alvarez stayed after school to help me, and she never made me feel foolish for my mistakes.  — check: length_off
5. Ms. Alvarez stayed late to help me with my schoolwork, and she never let me feel stupid for my mistakes.  — check: length_off

## Output E

ref `o-44128cac4904`, raw sha256 `789208e5e8a3e04f5941285890c5469d6ffe5b8c94eae0a8eec166fedfebb8fa`

Format: strict (json_object), 5 options

1. She never made me feel stupid when I made mistakes.  — not judged, counts as 0 (fail: echo)
2. She never made me feel stupid when I made mistakes.  — not judged, counts as 0 (fail: duplicate, echo)
3. She never made me feel stupid when I made mistakes.  — not judged, counts as 0 (fail: duplicate, echo)
4. She never made me feel stupid when I made mistakes.  — not judged, counts as 0 (fail: duplicate, echo)
5. She never made me feel stupid when I made mistakes.  — not judged, counts as 0 (fail: duplicate, echo)
