# ws2-screen-p02-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> In To Kill a Mockingbird, Atticus Finch shows that doing the right thing is not always easy. He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him. Atticus is someone who never gives up on what he believes, even when his own children get bullied at school because of it. He tells Scout that you never really understand a person until you look at things from their point of view. This shows that he wants his kids to be fair to everyone, not just people who are like them. Atticus is a good example of a person who stays brave when it would be easier to stay quiet.

Selected: This shows that he wants his kids to be fair to everyone, not just people who are like them.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-244385166d26`, raw sha256 `52e8491bd9c5c2e437801adda81a5b38942a251f185e6838bea9955130f5c73b`

Format: lenient (json_object_then_text), 5 options

1. He desires that his children be fair to all individuals, not only those who resemble them.
2. He believes that his children should treat everyone with equality, regardless of their similarities.  — check: negation_changed
3. Atticus wants his children to treat others justly, irrespective of whether they are like them.  — check: negation_changed
4. He wishes for his kids to be impartial and fair to everyone, not just those who share their background.
5. Atticus aims to teach his children to respect and treat everyone equally, without regard to their similarities.

## Output B

ref `o-863b8f06bfc8`, raw sha256 `c8453be38e775d03dc3aa5f64acd4266ae44a63e499dad4298545452e69e074c`

Format: strict (json_object), 5 options

1. This shows that he wants his kids to be fair to everyone, not just people who are like them.  — not judged, counts as 0 (fail: echo)
2. This shows that he wants his kids to be fair to everyone, not just those who are like them.  — not judged, counts as 0 (fail: duplicate)
3. This shows that he wants his kids to be fair to everyone, not just people who are similar to them.  — not judged, counts as 0 (fail: duplicate)
4. This shows that he wants his kids to be fair to everyone, not just those who are alike.  — not judged, counts as 0 (fail: duplicate)
5. This shows that he wants his kids to be fair to everyone, not just people who are the same.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-c5bad16486de`, raw sha256 `f986bd79a6d61556ea37e85566a9544821f9705625c406e0bc0ff3408f5994c2`

Format: strict (json_object), 5 options

1. This demonstrates his desire for his children to treat everyone with fairness, regardless of whether they are similar to themselves.  — check: negation_changed
2. This illustrates that he wishes his kids to be equitable toward all people, not merely those who resemble them.
3. This reveals that he expects his children to be just to everyone, rather than only to those like them.  — check: negation_changed
4. This indicates that he wants his children to be fair to every person, not just those who are like them.
5. This proves that he hopes his children will be just to everyone, not just to those who are similar to them.

## Output D

ref `o-25f3e33d61f0`, raw sha256 `de10e3cf8aacc399a83f9fb13ad59bf617eee3c154cac88ab91dc5a3f29b92b9`

Format: strict (json_object), 5 options

1. He desires his children to treat all individuals with fairness, not just those who resemble them.
2. He hopes his kids will judge everyone equally, irrespective of similarities.  — check: negation_changed
3. His aspiration is for his children to be impartial, extending fairness to all, not just their peers.
4. He wishes his offspring would be equitable in their judgment, not just towards people like them.
5. He wants his children to show fairness to everyone, rather than favoring those who are similar.  — check: negation_changed

## Output E

ref `o-d81e2837b3b2`, raw sha256 `6cd60db058dec84bac164b9468ef356fd3293c785911c8fcf133eed0c7c34176`

Format: lenient (json_object_then_text), 5 options

1. Atticus is a model of integrity, even when facing the wrath of his community.  — check: negation_changed
2. He remains steadfast in his convictions, refusing to yield to the mob mentality.  — check: negation_changed
3. Atticus demonstrates that moral courage often requires personal sacrifice.  — check: negation_changed, length_off
4. His unwavering belief means he will not compromise his principles for the sake of popularity.
5. He insists that justice must be pursued regardless of the opposition or consequences.  — check: negation_changed
