# ws2-full-p22-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Coral reefs are some of the most beautiful places on Earth, but they are in serious trouble. When the ocean gets too warm, corals push out the tiny algae that live inside them and give them their color. This is called coral bleaching, and if the water stays hot for too long, the coral can die. Reefs are home to about a quarter of all ocean species, so losing them would hurt a lot of sea life. They also protect coastlines from big waves during storms. Cutting down on pollution and greenhouse gases is the best way to give reefs a chance to recover.

Selected: Reefs are home to about a quarter of all ocean species, so losing them would hurt a lot of sea life.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-d83c58dcec06`, raw sha256 `cd85576a105a0669a4426b60a94e7ac19f898eeb5f615e96dac758a153c85d79`

Format: lenient (json_object), 5 options

1. Reefs support a quarter of all ocean species, so their loss would have a significant impact on marine life.
2. Home to a quarter of ocean species, reef loss would severely affect many sea creatures.
3. About a quarter of ocean species live on reefs, so their loss would have a profound effect on marine life.
4. Reefs are inhabited by a quarter of all ocean species, so their disappearance would harm numerous sea animals.
5. Reefs host a quarter of ocean species, so their loss would be detrimental to a large number of sea life.

## Output B

ref `o-bef00a80a062`, raw sha256 `1f19f7bd04785764960893a61ed0454ff1da25a1efcc6b8054af1731a61c4042`

Format: strict (json_object), 5 options

1. Reefs are a habitat for roughly a quarter of oceanic species, so their loss would severely impact marine life.
2. Coral reefs house about a quarter of all ocean species; their disappearance would cause significant harm to sea creatures.
3. Reefs, which shelter about 25% of ocean species, would greatly suffer if they were to vanish.  — check: invented_number
4. Coral reefs are home to approximately one-quarter of ocean species, and their loss would devastate marine life.
5. With reefs being a home to a quarter of all ocean species, their destruction would greatly affect marine ecosystems.

## Output C

ref `o-20356dcb2e17`, raw sha256 `2cb2ef80e5df67db67d8251765e1452743b8cde36a1e828b69f585550336df25`

Format: strict (json_object), 5 options

1. These habitats support roughly one-quarter of every marine creature, meaning their loss would severely impact ocean life.
2. About 25% of all sea species call these reefs home, so their destruction would devastate marine ecosystems.  — check: invented_number
3. Since reefs shelter approximately a quarter of ocean life, losing them would cause significant harm to marine creatures.
4. These structures are the residence of around 25% of all ocean species, and their loss would greatly hurt marine life.  — check: invented_number
5. Reefs provide homes for about a quarter of every ocean species, so losing them would severely damage marine biodiversity.
