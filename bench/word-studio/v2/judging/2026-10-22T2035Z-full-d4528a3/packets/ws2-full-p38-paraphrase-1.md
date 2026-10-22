# ws2-full-p38-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> During my junior year, I tore a ligament in my knee during a soccer game and had to miss the rest of the season. Soccer had always been a big part of who I was, so not being able to play made me feel lost. For the first few weeks, I barely wanted to leave my room. Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats. Every small win gave me a little more confidence. When I finally stepped back onto the field the next fall, I was stronger, both physically and mentally.

Selected: Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-3387f4bb3b44`, raw sha256 `ee516804eccbc218a60c26e23511be32db27a51aa51cbbe328d59ef9800794d9`

Format: strict (json_object), 5 options

1. Then my physical therapist encouraged me to set small goals, such as walking without crutches or doing ten squats.
2. Next, my physical therapist urged me to set small goals, like walking without crutches or doing ten squats.
3. Later, my physical therapist pushed me to set small goals, such as walking without crutches or doing ten squats.  — not judged, counts as 0 (fail: duplicate)
4. Then my physical therapist challenged me to set small goals, like walking without crutches or doing ten squats.  — not judged, counts as 0 (fail: duplicate)
5. After that, my physical therapist pushed me to set small goals, such as walking without crutches or doing ten squats.  — not judged, counts as 0 (fail: duplicate)
