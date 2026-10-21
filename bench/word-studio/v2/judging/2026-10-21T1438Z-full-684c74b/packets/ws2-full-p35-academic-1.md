# ws2-full-p35-academic-1

Kind: `academic`, asks for 5 options.

Paragraph:

> On July 20, 1969, Neil Armstrong became the first person to walk on the moon. The Apollo 11 mission was the result of years of hard work by thousands of scientists, engineers, and astronauts. The United States wanted to beat the Soviet Union in the space race, which was part of the larger Cold War. Millions of people around the world watched the landing live on television. The mission showed what humans can do when they work together toward a big goal. It also led to new technologies that we still use today.

Selected: On July 20, 1969, Neil Armstrong became the first person to walk on the moon.

Instruction given to every model:

> Give 5 different rewrites of the selected text in a more academic register suitable for a school or college essay. Keep the same meaning and the same level of certainty. Do not add evidence, statistics, names, citations or new ideas. Put the best options first.

## Output A

ref `o-2a1cdb9fb605`, raw sha256 `1b5f0752cd934e6f6e7c5bf8f09b048644576a374f2ae29156e4f1e31fa5fc4a`

Format: lenient (json_object_then_text), 5 options

1. On July 20, 1969, Neil Armstrong achieved the historic milestone of becoming the first human to set foot on the lunar surface.
2. The Apollo 11 mission, culminating in Neil Armstrong's historic lunar landing, represented a significant achievement in space exploration.  — check: number_changed, name_dropped
3. On July 20, 1969, Armstrong marked a pivotal moment in human history as he became the first person to walk on the moon.  — check: name_dropped
4. Neil Armstrong's achievement on July 20, 1969, marked a major milestone in the United States' space program and the broader context of the Cold War.
5. The Apollo 11 mission on July 20, 1969, saw Neil Armstrong become the first person to walk on the moon, a historic event that garnered widespread international attention.

## Output B

ref `o-235aebe924cd`, raw sha256 `f5b41c50dc0f8f26b936fdb58082406d56f05e5ea44cb6d30cc1365815e0a8eb`

Format: strict (json_object), 5 options

1. On July 20, 1969, Neil Armstrong achieved the status of the first individual to set foot upon the lunar surface.
2. On July 20, 1969, Neil Armstrong was the inaugural person to walk on the moon.
3. On July 20, 1969, Neil Armstrong attained the distinction of being the first human to step onto the moon.
4. On July 20, 1969, Neil Armstrong made history as the first person to walk upon the moon.
5. On July 20, 1969, Neil Armstrong was the first human to walk on the moon.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-41cc3bc0e1c6`, raw sha256 `ddfabacfabcff55271f706557f4ecb49823263043f50ecf48eb7ca9c39fd5bef`

Format: strict (json_object), 5 options

1. On the 20th of July, 1969, astronaut Neil Armstrong achieved the historic milestone of being the first human to set foot on the lunar surface.
2. Neil Armstrong made history on July 20, 1969, by becoming the first individual to walk on the moon.
3. The landmark event of July 20, 1969, witnessed Neil Armstrong as the first person to traverse the moon's surface.
4. On July 20, 1969, astronaut Neil Armstrong made the monumental achievement of being the first person to walk on the moon.
5. The historic day of July 20, 1969, saw astronaut Neil Armstrong as the first to walk on the moon.
