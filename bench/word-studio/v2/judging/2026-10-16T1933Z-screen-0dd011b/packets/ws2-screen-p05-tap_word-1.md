# ws2-screen-p05-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> When my family moved to the United States, I was eleven years old and I only knew a few words in English. The first few months at school were really hard because I could not understand what the teachers were saying. I felt alone most of the time, and I was too scared to talk in class. My English teacher, Ms. Alvarez, started staying after school to help me with reading and writing. She never made me feel stupid when I made mistakes. Little by little, I started to understand more and even make some friends. Now I am the one who helps new students when they first get here, because I know how it feels.

Selected: The first few months at school were really [[hard]] because I could not understand what the teachers were saying.

Instruction given to every model:

> Give 10 replacements for "hard" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "hard" without changing the rest of the sentence. Do not repeat "hard" itself. Put the best options first.

## Output A

ref `o-5142a1b2f582`, raw sha256 `2d10e8a681d748e9b32e3776752205e033cd14198154a83e9a8d71fd49e1e962`

Format: strict (json_object), 10 options

1. difficult
2. challenging
3. tough
4. frustrating
5. difficult  — not judged, counts as 0 (fail: duplicate)
6. challenging  — not judged, counts as 0 (fail: duplicate)
7. tough  — not judged, counts as 0 (fail: duplicate)
8. frustrating  — not judged, counts as 0 (fail: duplicate)
9. hardship
10. hardship  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-4b834358783c`, raw sha256 `d7398abe18a8571e0ff1c8678f5afc51be6aee6276fbef486bf7eed919e2d51c`

Format: strict (json_object), 10 options

1. challenging
2. difficult
3. difficult to navigate
4. tough
5. straining
6. exhausting
7. frustrating
8. strenuous
9. trying
10. demanding

## Output C

ref `o-63a04594a154`, raw sha256 `d800176dd74c2d57f4e6e8a164a918dc789416ebfd702b5bdc8ab6659ee61197`

Format: strict (json_object), 10 options

1. difficult
2. challenging
3. tough
4. tricky
5. struggling
6. painful
7. intense
8. trying
9. stressful
10. frustrating

## Output D

ref `o-b6eb8be8055b`, raw sha256 `8277d5155ea159988eb82a9cc9ba50eaa5f7cdf16286c0d3fbc86728bec2452d`

Format: strict (json_object), 10 options

1. difficult
2. struggling
3. challenging
4. uncomfortable
5. tiring
6. exhausting
7. painful
8. boring
9. tedious
10. confusing

## Output E

ref `o-1d61bc094147`, raw sha256 `1ffc4534a841e60b370d9e719d0a3402cc3769976cd29c33256ae0d6f5117f90`

Format: strict (json_object), 10 options

1. difficult
2. challenging
3. strenuous
4. tough
5. demanding
6. difficulties
7. arduous
8. trying
9. difficult  — not judged, counts as 0 (fail: duplicate)
10. severe difficulties
