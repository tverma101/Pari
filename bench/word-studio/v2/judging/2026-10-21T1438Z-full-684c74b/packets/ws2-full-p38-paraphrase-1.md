# ws2-full-p38-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> During my junior year, I tore a ligament in my knee during a soccer game and had to miss the rest of the season. Soccer had always been a big part of who I was, so not being able to play made me feel lost. For the first few weeks, I barely wanted to leave my room. Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats. Every small win gave me a little more confidence. When I finally stepped back onto the field the next fall, I was stronger, both physically and mentally.

Selected: Then my physical therapist pushed me to set small goals, like walking without crutches or doing ten squats.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-6efcb6ba063d`, raw sha256 `eb5e2611e1518f8a99866193f3322e5c0d7d138aa5a0397254ca6450f2554432`

Format: strict (json_object), 5 options

1. Subsequently, my physical therapist encouraged me to establish modest objectives, such as ambulating without crutches or completing ten push-ups.
2. Afterward, my physical therapist urged me to define attainable targets, for instance, walking unaided or performing ten squats.  — check: negation_changed
3. Following that, my physical therapist motivated me to set achievable aims, like walking without crutches or doing ten lunges.
4. Subsequently, my physical therapist inspired me to set realistic goals, such as walking unaided or doing ten sit-ups.  — check: negation_changed
5. Subsequently, my physical therapist encouraged me to set attainable objectives, like walking without crutches or doing ten leg raises.

## Output B

ref `o-0eae3b064a7c`, raw sha256 `ee5c64ce90093ddf94917b98a0dd4c44ffe6ab439a8665543bc67cb96f0a3f2b`

Format: strict (json_object), 5 options

1. My physical therapist encouraged me to set tiny objectives, such as walking without crutches or performing ten squats.
2. My therapist motivated me to establish manageable goals, like walking without crutches or completing ten squats.
3. My physical therapist advised me to set small targets, including walking without crutches or doing ten squats.
4. My therapist urged me to set manageable goals, such as walking without crutches or performing ten squats.
5. My physical therapist persuaded me to set achievable targets, like walking without crutches or doing ten squats.

## Output C

ref `o-b9c5bafbd905`, raw sha256 `e55e795baf94305d5cf188291a22d598a3d990aa6e9b7f7098af18003e0a1cb6`

Format: strict (json_object), 5 options

1. Then my physical therapist encouraged me to establish small goals, such as walking without crutches or performing ten squats.
2. Next, my physical therapist urged me to set small goals, like walking without crutches or completing ten squats.
3. Subsequently, my physical therapist guided me to set small goals, including walking without crutches or doing ten squats.
4. After that, my physical therapist prompted me to set small goals, such as walking without crutches or executing ten squats.
5. Then, my physical therapist motivated me to set small goals, like walking without crutches or performing ten squats.
