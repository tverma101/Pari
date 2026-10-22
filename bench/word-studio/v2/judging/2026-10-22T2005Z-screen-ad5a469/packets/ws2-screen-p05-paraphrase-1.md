# ws2-screen-p05-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> When my family moved to the United States, I was eleven years old and I only knew a few words in English. The first few months at school were really hard because I could not understand what the teachers were saying. I felt alone most of the time, and I was too scared to talk in class. My English teacher, Ms. Alvarez, started staying after school to help me with reading and writing. She never made me feel stupid when I made mistakes. Little by little, I started to understand more and even make some friends. Now I am the one who helps new students when they first get here, because I know how it feels.

Selected: She never made me feel stupid when I made mistakes.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-68e78e565225`, raw sha256 `854e31edb0244fdab3efa43ddd3e727c9137856bc695bff30557ffdfd5fa5831`

Format: strict (json_object), 5 options

1. She never made me feel foolish when I made mistakes.
2. She never made me feel stupid whenever I made errors.
3. She never made me feel dumb when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
4. She never made me feel silly when I made mistakes.  — not judged, counts as 0 (fail: duplicate)
5. She never made me feel stupid whenever I made errors.  — not judged, counts as 0 (fail: duplicate)
