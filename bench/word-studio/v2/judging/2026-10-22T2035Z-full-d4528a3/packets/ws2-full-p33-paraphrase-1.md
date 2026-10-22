# ws2-full-p33-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen. I help him with his homework, make him dinner, and make sure he goes to bed on time. Some days it is stressful, especially when I have a big test the next morning. But taking care of him has made me more patient and responsible than most kids my age. I have learned how to manage my time and stay calm when things do not go as planned. My brother looks up to me, and that makes all the hard work worth it.

Selected: I have learned how to manage my time and stay calm when things do not go as planned.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-4e362e84570b`, raw sha256 `7665762eaa2baddd85761446d3a18b1d2cd6e5c07b16065007c6d5c6c20d9afa`

Format: strict (json_object), 5 options

1. I have learned to organize my time and remain calm when things do not go as planned.
2. I have learned how to manage my schedule and stay calm when things do not go as planned.
3. I have learned to handle my time and stay calm when things do not go as planned.  — not judged, counts as 0 (fail: duplicate)
4. I have learned to organize my time and stay calm when things do not go as planned.  — not judged, counts as 0 (fail: duplicate)
5. I have learned how to handle my time and stay calm when things do not go as planned.  — not judged, counts as 0 (fail: duplicate)
