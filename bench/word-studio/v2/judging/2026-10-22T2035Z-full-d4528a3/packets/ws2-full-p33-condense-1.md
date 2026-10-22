# ws2-full-p33-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen. I help him with his homework, make him dinner, and make sure he goes to bed on time. Some days it is stressful, especially when I have a big test the next morning. But taking care of him has made me more patient and responsible than most kids my age. I have learned how to manage my time and stay calm when things do not go as planned. My brother looks up to me, and that makes all the hard work worth it.

Selected: Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-82cc1d5ce2d4`, raw sha256 `9b8c17c60bd26e078eba8de65ee063aa10911fb5bdb8af6e8c4adf39b73c1f11`

Format: strict (json_object), 5 options

1. Since my mom works night shifts at the hospital, I have cared for my little brother since I was thirteen.
2. My mom works night shifts at the hospital, so I have cared for my little brother since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
3. I have cared for my little brother since I was thirteen because my mom works night shifts at the hospital.
4. Since my mom works night shifts at the hospital, I have looked after my little brother since I was thirteen.  — not judged, counts as 0 (fail: duplicate)
5. My mom works night shifts at the hospital; since I was thirteen, I have looked after my little brother.
