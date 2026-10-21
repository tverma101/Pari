# ws2-full-p33-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen. I help him with his homework, make him dinner, and make sure he goes to bed on time. Some days it is stressful, especially when I have a big test the next morning. But taking care of him has made me more patient and responsible than most kids my age. I have learned how to manage my time and stay calm when things do not go as planned. My brother looks up to me, and that makes all the hard work worth it.

Selected: Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-6f685c7ccfca`, raw sha256 `7ce91e4522f0973e946c4ddb23deaea8cdd08b826490677870703a09d6cc589c`

Format: strict (json_object), 5 options

1. I look after my brother after school since my mom's hospital shifts.
2. Since mom works nights, I've cared for my younger sibling post-school since age thirteen.
3. Mom's hospital shifts mean I've been responsible for my brother after school since I was thirteen.
4. Since mom's at work nights, I've looked after my brother after school since thirteen.
5. I take care of my little brother after school because mom works night shifts at the hospital.

## Output B

ref `o-77e39a386730`, raw sha256 `90f2b469ea32390fd98e36c0c133e9b36568c06ab119cc63f53f5b672138b9a8`

Format: lenient (json_object), 5 options

1. My mom works nights at the hospital, so I've been taking care of my brother after school since I was thirteen.
2. Since my mom works night shifts at the hospital, I've been taking care of my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
3. As my mom works nights at the hospital, I've been caring for my little brother after school since I was thirteen.
4. Because my mom works night shifts at the hospital, I've been taking care of my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
5. My mom works nights at the hospital, so I've been taking care of my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-dc243751988e`, raw sha256 `7c0f13e5b408b823cbd3fedd7d61029ffb5388426ac08399b8d638c91de444cf`

Format: strict (json_object), 5 options

1. Since my mother works night shifts at the hospital, I have cared for my little brother after school since I was thirteen.
2. With my mother working night shifts at the hospital, I have taken care of my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
3. My mother works night shifts at the hospital, so I have cared for my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
4. Since my mother works night shifts at the hospital, I have been responsible for my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
5. My mother works night shifts at the hospital, meaning I have cared for my little brother after school since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
