# ws2-full-p42-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> In The Outsiders, Ponyboy learns that people are more alike than they seem. At the start of the novel, he believes that the Socs, the rich kids from the west side, have perfect lives with no problems. Then he meets Cherry Valance, a Soc girl who tells him that rich kids have troubles too. Later, Randy, another Soc, admits that he is tired of all the fighting between the two groups. These conversations make Ponyboy realize that the line between Greasers and Socs is not as clear as he thought. S. E. Hinton shows that judging people by their group keeps us from seeing who they really are.

Selected: Later, Randy, another Soc, admits that he is tired of all the fighting between the two groups.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-a9576619e013`, raw sha256 `e0fad450ec4b4089dec2eeb41fef38c2a9dd30cd2d5ff0c73a3a662e6dc9e076`

Format: strict (json_object), 5 options

1. Later, Randy, another Soc, admits that he is weary of all the fighting between the two groups.
2. Later, Randy, another Soc, confesses that he is fed up with all the fighting between the two groups.
3. Later, Randy, another Soc, acknowledges that he is tired of all the fighting between the two groups.  — not judged, counts as 0 (fail: duplicate)
4. Later, Randy, another Soc, admits that he is done with all the fighting between the two groups.  — not judged, counts as 0 (fail: duplicate)
5. Later, Randy, another Soc, admits that he is sick of all the fighting between the two groups.  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-530aa68d1dad`, raw sha256 `34afbb6caf44d769a4df23764e6646a53d0e14cc132d8d6114f7f53499821326`

Format: strict (json_object), 5 options

1. Subsequently, Randy, a member of the Socs, expresses his exhaustion over the constant conflict between the two factions.
2. Later, Randy, who belongs to the Socs, reveals his weariness with the ongoing disputes between the groups.
3. Randy, a Soc, later voices his frustration with the perpetual strife between the Socs and Greasers.
4. Sometime later, Randy, a Soc, confides his tiredness of the endless battles between the Socs and Greasers.
5. Eventually, Randy, a Soc, confesses his boredom with the ceaseless confrontations between the Socs and Greasers.

## Output C

ref `o-5151c37e1a5b`, raw sha256 `867c88f4212229785a8076c2bcae5b18f5651a566078b281f5365aca3e1dfdcd`

Format: lenient (json_object), 5 options

1. Later, Randy, a Soc, confesses his frustration with the ongoing conflict between the two groups.
2. Randy, a Soc, reveals that he is sick of the constant fighting between Greasers and Socs.
3. Randy, a member of the Socs, admits to feeling tired of the rivalry.
4. Randy, a Soc, confesses his weariness with the persistent battles between the two groups.
5. Randy, a Soc, admits to being exhausted by the ongoing rivalry between the two groups.
