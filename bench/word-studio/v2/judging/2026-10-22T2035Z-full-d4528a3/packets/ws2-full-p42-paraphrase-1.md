# ws2-full-p42-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> In The Outsiders, Ponyboy learns that people are more alike than they seem. At the start of the novel, he believes that the Socs, the rich kids from the west side, have perfect lives with no problems. Then he meets Cherry Valance, a Soc girl who tells him that rich kids have troubles too. Later, Randy, another Soc, admits that he is tired of all the fighting between the two groups. These conversations make Ponyboy realize that the line between Greasers and Socs is not as clear as he thought. S. E. Hinton shows that judging people by their group keeps us from seeing who they really are.

Selected: Later, Randy, another Soc, admits that he is tired of all the fighting between the two groups.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-62aaaa2a15b0`, raw sha256 `191055ff2ced67c25e68d656b9dfa318934da6c2e9e4ff9ccb1699e543880b63`

Format: strict (json_object), 5 options

1. Later, Randy, a Soc, says he is weary of the fighting between the two groups.
2. Later, Randy, another Soc, admits he is done with all the fighting between the two groups.
3. Later, Randy, a Soc, confesses he is tired of the fighting between the two groups.  — not judged, counts as 0 (fail: duplicate)
4. Later, Randy, another Soc, admits he is exhausted by the fighting between the two groups.  — not judged, counts as 0 (fail: duplicate)
5. Later, Randy, a Soc, says he is sick of all the fighting between the two groups.  — not judged, counts as 0 (fail: duplicate)
