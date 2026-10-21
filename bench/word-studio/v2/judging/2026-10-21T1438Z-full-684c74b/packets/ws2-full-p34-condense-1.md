# ws2-full-p34-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> College athletes bring in millions of dollars for their schools, but for a long time they were not allowed to earn any of it. Big football and basketball programs sell tickets, jerseys, and TV rights, while the players who make it all possible get nothing except a scholarship. Many athletes spend more than forty hours a week on their sport, which makes it hard to keep a part-time job. In 2021, new rules finally let athletes make money from their name and image. I think this was a fair change, and schools should go even further by sharing some of their profits with players.

Selected: Big football and basketball programs sell tickets, jerseys, and TV rights, while the players who make it all possible get nothing except a scholarship.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-7f1bd5d5dea6`, raw sha256 `7d80935e2ca5345d3d880bf6097d432dcff4c049d65eacccab73e4e23ec8678e`

Format: strict (json_object), 5 options

1. Big football and basketball programs sell tickets, jerseys, and TV rights, while players earn only a scholarship.  — check: negation_changed
2. Football and basketball programs sell tickets, jerseys, and TV rights, but players get only a scholarship.  — not judged, counts as 0 (fail: duplicate)
3. Big programs sell tickets, jerseys, and TV rights; players receive only a scholarship.  — check: negation_changed
4. Football and basketball programs sell tickets, jerseys, and TV rights, leaving players with just a scholarship.  — check: negation_changed
5. Big football and basketball programs sell tickets, jerseys, and TV rights, yet players are left with only a scholarship.  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-c6bdcfe29942`, raw sha256 `b552de07e63afcfcce5223ad3ee1d86732ae0b96dc597049637b3101a39d680a`

Format: strict (json_object), 5 options

1. Football and basketball programs profit, yet players earn only scholarships.  — check: negation_changed
2. Players in big football and basketball programs receive no direct earnings, just scholarships.
3. Big football and basketball programs sell tickets, jerseys, and TV rights, while players earn nothing but scholarships.
4. Players make schools millions, but earn only scholarships from big football and basketball programs.  — check: negation_changed
5. Football and basketball players, who generate millions, are limited to scholarships.  — check: negation_changed

## Output C

ref `o-9b76092e6f0b`, raw sha256 `d703bdd96327780112936db2a8081b3a9bf2018a74c762fee69e573cafd8172a`

Format: strict (json_object), 5 options

1. Big football and basketball programs generate millions through tickets, jerseys, and TV rights, but players receive only scholarships.  — check: negation_changed
2. Football and basketball teams bring in revenue through tickets, jerseys, and TV rights, yet players are offered only scholarships.  — check: negation_changed
3. Big programs in football and basketball earn revenue via tickets, jerseys, and TV rights, while players receive nothing but scholarships.
4. Football and basketball teams sell tickets, jerseys, and TV rights, but players receive only scholarships.  — check: negation_changed
5. Big programs in football and basketball make money through tickets, jerseys, and TV rights, but players get nothing but scholarships.
