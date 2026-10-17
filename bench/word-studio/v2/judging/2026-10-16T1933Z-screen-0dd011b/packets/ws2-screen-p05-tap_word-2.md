# ws2-screen-p05-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> When my family moved to the United States, I was eleven years old and I only knew a few words in English. The first few months at school were really hard because I could not understand what the teachers were saying. I felt alone most of the time, and I was too scared to talk in class. My English teacher, Ms. Alvarez, started staying after school to help me with reading and writing. She never made me feel stupid when I made mistakes. Little by little, I started to understand more and even make some friends. Now I am the one who helps new students when they first get here, because I know how it feels.

Selected: I felt alone most of the time, and I was too [[scared]] to talk in class.

Instruction given to every model:

> Give 10 replacements for "scared" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "scared" without changing the rest of the sentence. Do not repeat "scared" itself. Put the best options first.

## Output A

ref `o-b0fb4fe994b5`, raw sha256 `a3794b0c02588e85e66a7fea94d2fd0301f9c44a04376fc014de81063a0251f2`

Format: strict (json_object), 10 options

1. afraid
2. frightened
3. worried
4. anxious
5. scared  — not judged, counts as 0 (fail: echo)
6. fearful
7. nervous
8. apprehensive
9. timid
10. frightened  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-8984ae43f857`, raw sha256 `21fcf68efb0b632d75280deeaacc7ab2712ab092e9137c54801e5948ce557b78`

Format: strict (json_object), 10 options

1. afraid
2. nervous
3. alarmed
4. shy
5. anxious
6. tense
7. worried
8. humbly
9. fearful
10. caught

## Output C

ref `o-b3aa199ca60d`, raw sha256 `af15e115b2a2585cf8173b0e4df639d62938da1b8335037c2fe420586ccacabb`

Format: strict (json_object), 10 options

1. afraid
2. anxious
3. intimidated
4. nervous
5. frightened
6. uncomfortable
7. hesitant
8. timid
9. insecure
10. apprehensive

## Output D

ref `o-4b984cc7210d`, raw sha256 `4bb466297b69ea4a7dac42d3501148991ae1d649916714008f50ed435a07604a`

Format: strict (json_object), 10 options

1. frightened
2. anxious
3. nervous
4. terrified
5. apprehensive
6. wary
7. uneasy
8. distrustful
9. hesitant
10. reluctant

## Output E

ref `o-f0ad8b8aaf4d`, raw sha256 `26c3ac6637ce9fcc3da7092a261bc786c22a0f489b5043a1b913e3e5f7b383ec`

Format: strict (json_object), 10 options

1. afraid
2. anxious
3. nervous
4. terrified
5. dreadful
6. frightened
7. panic-stricken
8. worried
9. apprehensive
10. uneasy
