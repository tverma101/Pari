# ws2-screen-p05-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> When my family moved to the United States, I was eleven years old and I only knew a few words in English. The first few months at school were really hard because I could not understand what the teachers were saying. I felt alone most of the time, and I was too scared to talk in class. My English teacher, Ms. Alvarez, started staying after school to help me with reading and writing. She never made me feel stupid when I made mistakes. Little by little, I started to understand more and even make some friends. Now I am the one who helps new students when they first get here, because I know how it feels.

Selected: [[Little by little]], I started to understand more and even make some friends.

Instruction given to every model:

> Give 10 single words that can replace "Little by little" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-c8bdb97e3167`, raw sha256 `ffed8af7c3d3aad3d5f52634e8296a05cb6b692e35cec970412c22fb606979d2`

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

## Output B

ref `o-415c22a7d7d5`, raw sha256 `13f30262b5170bcd0c8e9185ad45cac64e42ec48310fbe1993fd0589697340ee`

Format: strict (json_object), 10 options

1. Gradually
2. Slowly
3. Incrementally
4. Progressively
5. Bit by bit  — not judged, counts as 0 (fail: too_many_words)
6. Step by step  — not judged, counts as 0 (fail: too_many_words)
7. Slowly  — not judged, counts as 0 (fail: duplicate)
8. Piece by piece  — not judged, counts as 0 (fail: too_many_words)
9. In small doses  — not judged, counts as 0 (fail: too_many_words)
10. Slowly  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-f5c81cf5ec98`, raw sha256 `172a04ba3c9b14738670318867b8e8738dabc68dc2a164ffbc6ee6b7617c4729`

Format: strict (json_object), 10 options

1. gradually
2. step by step  — not judged, counts as 0 (fail: too_many_words)
3. over time  — not judged, counts as 0 (fail: too_many_words)
4. with time  — not judged, counts as 0 (fail: too_many_words)
5. progressively
6. slowly
7. bit by bit  — not judged, counts as 0 (fail: too_many_words)
8. incrementally
9. over the course  — not judged, counts as 0 (fail: too_many_words)
10. steadily

## Output D

ref `o-c54198c949b2`, raw sha256 `020b14317eb209d9db4360b5b85e44fdbfdf665f1868863d9c4a24dd03ec1bc8`

Format: strict (json_object), 10 options

1. gradually
2. step by step  — not judged, counts as 0 (fail: too_many_words)
3. one by one  — not judged, counts as 0 (fail: too_many_words)
4. slowly
5. steadily
6. eventually
7. piece by piece  — not judged, counts as 0 (fail: too_many_words)
8. bit by bit  — not judged, counts as 0 (fail: too_many_words)
9. over time  — not judged, counts as 0 (fail: too_many_words)
10. consistently

## Output E

ref `o-21af090bbe32`, raw sha256 `e7064b454b56e50ec7f3b8d6002df88850a5fc2f1ae9b704318dcb8a12ae4598`

Format: strict (json_object), 10 options

1. Gradually
2. Slowly
3. Over time  — not judged, counts as 0 (fail: too_many_words)
4. Step by step  — not judged, counts as 0 (fail: too_many_words)
5. Bit by bit  — not judged, counts as 0 (fail: too_many_words)
6. In time  — not judged, counts as 0 (fail: too_many_words)
7. Progressively
8. Incrementally
9. A little at a time  — not judged, counts as 0 (fail: too_many_words)
10. Piece by piece  — not judged, counts as 0 (fail: too_many_words)
