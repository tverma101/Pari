# ws2-screen-p02-academic-1

Kind: `academic`, asks for 5 options.

Paragraph:

> In To Kill a Mockingbird, Atticus Finch shows that doing the right thing is not always easy. He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him. Atticus is someone who never gives up on what he believes, even when his own children get bullied at school because of it. He tells Scout that you never really understand a person until you look at things from their point of view. This shows that he wants his kids to be fair to everyone, not just people who are like them. Atticus is a good example of a person who stays brave when it would be easier to stay quiet.

Selected: He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him.

Instruction given to every model:

> Give 5 different rewrites of the selected text in a more academic register suitable for a school or college essay. Keep the same meaning and the same level of certainty. Do not add evidence, statistics, names, citations or new ideas. Put the best options first.

## Output A

ref `o-e38721ace419`, raw sha256 `dccd63da66eeca0fe33a3e401a561ccfe2d22fb8eefacb912670b68bfeb0b382`

Format: strict (json_object), 5 options

1. He agrees to defend Tom Robinson despite knowing that most people in Maycomb will be angry with him.
2. He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him.  — not judged, counts as 0 (fail: echo)
3. He agrees to defend Tom Robinson although he knows that most people in Maycomb will be angry with him.  — not judged, counts as 0 (fail: duplicate)
4. He agrees to defend Tom Robinson despite knowing that most people in Maycomb will be angry toward him.  — not judged, counts as 0 (fail: duplicate)
5. He agrees to defend Tom Robinson although he knows that most people in Maycomb will be angry at him.  — not judged, counts as 0 (fail: duplicate)
