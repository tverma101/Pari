# ws2-full-p32-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> In The Crucible, Arthur Miller shows how fear can make a whole town turn against itself. When a group of girls in Salem start accusing people of witchcraft, the adults believe them without asking for proof. Anyone who disagrees with the court is in danger of being accused too. John Proctor knows the girls are lying, but at first he is afraid to speak up because he has his own secret. In the end, he chooses to die rather than sign a false confession. Miller wrote the play in the 1950s to criticize the way people were being accused of being communists without real evidence.

Selected: When a group of girls in Salem start accusing people of witchcraft, the adults believe them without asking for proof.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-f6f8e40fbcdd`, raw sha256 `2b9f67af9a31ca75163d2df7a044d9e5b6e5dc2148ac36517832f0d0b76ac4ac`

Format: strict (json_object), 5 options

1. The Salem girls falsely accused people of witchcraft, and the adults believed them without proof.
2. The Salem girls accused others of witchcraft, and the adults accepted their claims without questioning.
3. Salem's girls accused people of witchcraft, and the adults didn't demand proof.
4. In Salem, girls falsely accused people of witchcraft, and the adults believed them without evidence.  — not judged, counts as 0 (fail: duplicate)
5. The Salem girls accused people of witchcraft, and the adults believed them without verifying their claims.

## Output B

ref `o-7e3e11c516ba`, raw sha256 `201e5cca78c1db1ab5de39374aa1c6d2c5df128df596c5bb0efbcf469cec102d`

Format: strict (json_object), 5 options

1. Salem girls accuse others of witchcraft, and adults accept their claims without proof.
2. When Salem girls accuse people of witchcraft, adults believe them without proof.
3. Salem girls begin accusing others of witchcraft; adults believe them without asking for proof.
4. Salem girls accuse people of witchcraft, and adults believe them without proof.  — not judged, counts as 0 (fail: duplicate)
5. Salem girls start accusing others of witchcraft, and adults believe them without proof.

## Output C

ref `o-7f2ddc973fc9`, raw sha256 `dd5faf729548fbc1789c8edd47784091324385c58216b7e905118725614226ed`

Format: lenient (json_object), 5 options

1. Salem's adults believe Salem's girls without proof.
2. Adults in Salem trust girls' witchcraft claims without evidence.
3. Salem's adults accept girls' accusations without seeking proof.
4. In Salem, adults believe girls' witchcraft accusations without proof.
5. Salem adults believe girls' witchcraft claims without evidence.
