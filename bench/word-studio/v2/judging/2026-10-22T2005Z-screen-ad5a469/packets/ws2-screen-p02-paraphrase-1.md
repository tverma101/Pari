# ws2-screen-p02-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> In To Kill a Mockingbird, Atticus Finch shows that doing the right thing is not always easy. He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him. Atticus is someone who never gives up on what he believes, even when his own children get bullied at school because of it. He tells Scout that you never really understand a person until you look at things from their point of view. This shows that he wants his kids to be fair to everyone, not just people who are like them. Atticus is a good example of a person who stays brave when it would be easier to stay quiet.

Selected: This shows that he wants his kids to be fair to everyone, not just people who are like them.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-ca8f5e64610e`, raw sha256 `b620fce049baa1b18850646a02b09815ce6fccee3a660cce191a249813a0b037`

Format: strict (json_object), 5 options

1. This shows he wants his children to be fair to everyone, not just people like them.
2. This shows he wants his kids to treat everyone fairly, not only those similar to them.
3. This shows he wants his children to be fair to all, not just those like them.  — not judged, counts as 0 (fail: duplicate)
4. This shows he wants his kids to be fair to everyone, not just people who are like them.  — not judged, counts as 0 (fail: duplicate)
5. This shows he wants his children to be fair to everyone, not just those like themselves.  — not judged, counts as 0 (fail: duplicate)
