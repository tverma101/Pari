# ws2-screen-p05-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> When my family moved to the United States, I was eleven years old and I only knew a few words in English. The first few months at school were really hard because I could not understand what the teachers were saying. I felt alone most of the time, and I was too scared to talk in class. My English teacher, Ms. Alvarez, started staying after school to help me with reading and writing. She never made me feel stupid when I made mistakes. Little by little, I started to understand more and even make some friends. Now I am the one who helps new students when they first get here, because I know how it feels.

Selected: [[Little by little]], I started to understand more and even make some friends.

Instruction given to every model:

> Give 10 single words that can replace "Little by little" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-f40d04f7c276`, raw sha256 `a93f283de86885999d059172ef0b344dceb4800bd1744a52b02f3236e467c3fe`

Format: strict (json_object), 10 options

1. Gradually
2. Slowly
3. Eventually
4. Progressively
5. Steadily
6. Incrementally
7. Continuously
8. Constantly
9. Persistently
10. Step by step  — not judged, counts as 0 (fail: too_many_words)

## Output B

ref `o-fc835e004f0e`, raw sha256 `ffed8af7c3d3aad3d5f52634e8296a05cb6b692e35cec970412c22fb606979d2`

Format: strict (json_object), 10 options

1. Slowly
2. Gradually
3. Step by step  — not judged, counts as 0 (fail: too_many_words)
4. Slowly  — not judged, counts as 0 (fail: duplicate)
5. Gradually  — not judged, counts as 0 (fail: duplicate)
6. Step by step  — not judged, counts as 0 (fail: duplicate, too_many_words)
7. Slowly  — not judged, counts as 0 (fail: duplicate)
8. Gradually  — not judged, counts as 0 (fail: duplicate)
9. Step by step  — not judged, counts as 0 (fail: duplicate, too_many_words)
10. Slowly  — not judged, counts as 0 (fail: duplicate)
