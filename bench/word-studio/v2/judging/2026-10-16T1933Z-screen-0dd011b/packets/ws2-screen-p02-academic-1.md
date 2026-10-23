# ws2-screen-p02-academic-1

Kind: `academic`, asks for 5 options.

Paragraph:

> In To Kill a Mockingbird, Atticus Finch shows that doing the right thing is not always easy. He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him. Atticus is someone who never gives up on what he believes, even when his own children get bullied at school because of it. He tells Scout that you never really understand a person until you look at things from their point of view. This shows that he wants his kids to be fair to everyone, not just people who are like them. Atticus is a good example of a person who stays brave when it would be easier to stay quiet.

Selected: He agrees to defend Tom Robinson even though he knows that most people in Maycomb will be angry at him.

Instruction given to every model:

> Give 5 different rewrites of the selected text in a more academic register suitable for a school or college essay. Keep the same meaning and the same level of certainty. Do not add evidence, statistics, names, citations or new ideas. Put the best options first.

## Output A

ref `o-e222c96424c6`, raw sha256 `05e741a1abcaa3a811f980583c22600ff04eb1cbcb8cbdd261ab1a74896a4ed3`

Format: strict (json_object), 5 options

1. He consents to represent Tom Robinson, fully aware of the potential backlash from the majority of Maycomb's residents.
2. He accepts the responsibility of defending Tom Robinson, cognizant of the probable disapproval from the local populace.  — check: name_dropped
3. He volunteers to defend Tom Robinson, fully understanding the likelihood of widespread anger from the townspeople of Maycomb.
4. He agrees to advocate for Tom Robinson, recognizing the probable animosity from the majority of Maycomb's citizens.
5. He undertakes the role of Tom Robinson's defense attorney, fully aware of the anticipated hostility from the townspeople of Maycomb.

## Output B

ref `o-1502c5e85375`, raw sha256 `8421480556c6c37c6711e64dda9285bf7df4afc87c24c8bf568925f9fa506f35`

Format: strict (json_object), 5 options

1. He willingly accepts the defense of Tom Robinson despite anticipating widespread public disapproval in Maycomb.
2. Despite the anticipated negative reaction of most Maycomb residents, Atticus Finch volunteers to defend Tom Robinson.
3. Atticus Finch's decision to defend Tom Robinson is made even in the face of likely public censure in Maycomb.
4. Atticus Finch, anticipating a negative reaction from the majority of Maycomb's population, accepts the defense of Tom Robinson.
5. Atticus Finch, recognizing the potential for public backlash, agrees to defend Tom Robinson in Maycomb.

## Output C

ref `o-bf3c974608e2`, raw sha256 `ff9117d798519df6f0c5d3408667e90286ec136b93ed133ce4c9bdfa1109bbb5`

Format: strict (json_object), 5 options

1. Atticus Finch is prepared to defend Tom Robinson despite the anticipated anger of the community.  — check: name_dropped
2. He consents to representing Tom Robinson even though he anticipates hostility from the local population.  — check: name_dropped
3. Atticus is willing to support Tom Robinson despite the expectation that Maycomb residents would be upset.
4. He agrees to defend Tom Robinson despite knowing that the majority of the town would likely oppose his position.  — check: name_dropped
5. Atticus Finch is prepared to act on behalf of Tom Robinson, even though he is aware that many in Maycomb would be angry about it.

## Output D

ref `o-9363798bd702`, raw sha256 `e2c49f2cb2f721d94dea6d52c96c7e5d242b7b0afd7939fe17cb919357907430`

Format: strict (json_object), 5 options

1. He agrees to defend Tom Robinson despite the likely anger of many in Maycomb.
2. He agrees to defend Tom Robinson even though he knows that most people in Maycomb would be angry at him.
3. He agrees to defend Tom Robinson despite the fact that most people in Maycomb would be angry at him.
4. He agrees to defend Tom Robinson even though he knows that most people in Maycomb would be angry at him.  — not judged, counts as 0 (fail: duplicate)
5. He agrees to defend Tom Robinson despite the widespread anger of most people in Maycomb.

## Output E

ref `o-dcf9c7c03c46`, raw sha256 `a64e747b99589fe74dd41b5cb839611cbb6db3c4094704e8cec4535764f07c32`

Format: strict (json_object), 5 options

1. He accepts the defense of Tom Robinson despite being aware that the majority of Maycomb's residents will resent him.
2. He consents to represent Tom Robinson even though he recognizes that most individuals in Maycomb will harbor anger toward him.
3. He agrees to defend Tom Robinson with full knowledge that the majority of the population in Maycomb will be hostile toward him.
4. He accepts the responsibility of defending Tom Robinson despite anticipating that most people in Maycomb will feel resentment toward him.
5. He agrees to take the case of Tom Robinson while knowing that the majority of Maycomb's inhabitants will be angry at him.
