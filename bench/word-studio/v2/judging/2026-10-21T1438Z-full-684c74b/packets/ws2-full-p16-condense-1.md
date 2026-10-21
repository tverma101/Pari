# ws2-full-p16-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> The Montgomery Bus Boycott was a key event in the civil rights movement. It started in December 1955 when Rosa Parks was arrested for refusing to give up her seat to a white passenger. In response, Black residents of Montgomery stopped riding the city buses for more than a year. Many people walked miles to work every day or set up carpools so that they would not have to use the buses. The boycott hurt the bus company because it lost most of its riders. In 1956, the Supreme Court ruled that segregation on buses was unconstitutional, and the boycott ended in victory.

Selected: Many people walked miles to work every day or set up carpools so that they would not have to use the buses.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-9e465fe98618`, raw sha256 `13b3f5cf98cc776a873f9744055c207d5da5de42a49f41f72f5079c79a703d89`

Format: strict (json_object), 5 options

1. Black residents walked miles or arranged carpools to avoid buses.  — check: negation_changed
2. Residents walked or organized carpools to bypass buses.  — check: negation_changed
3. People walked miles or formed carpools to avoid bus rides.  — check: negation_changed
4. Black residents walked or created carpools to circumvent buses.  — check: negation_changed
5. Residents walked or set up carpools to steer clear of buses.  — check: negation_changed

## Output B

ref `o-62e62f57f1dc`, raw sha256 `27dacb16657ff8b012d6d43de67a29ff96bccb7573df460b8f57a821aafcae6d`

Format: lenient (json_object_then_text), 5 options

1. Many walked miles to work or carpooled to avoid buses.  — check: negation_changed
2. They walked miles daily or carpooled to avoid using buses.  — check: negation_changed
3. People walked long distances to work or formed carpools to bypass buses.  — check: negation_changed
4. Many walked miles to work or carpooled daily to avoid the buses.  — not judged, counts as 0 (fail: duplicate)
5. Walkers and carpools avoided buses daily by walking long distances or carpooling.  — check: negation_changed

## Output C

ref `o-54e6f7e29b53`, raw sha256 `cab5006bf64f46cfba08115efd20499094e920b850b6d156fcdb4d9336472556`

Format: strict (json_object), 5 options

1. Many walked miles daily or carpooled to avoid buses.  — check: negation_changed
2. People walked miles daily or carpooled to skip buses.  — check: negation_changed
3. Many walked long distances or carpooled to avoid bus rides.  — check: negation_changed
4. Many walked miles daily or carpooled to bypass buses.  — not judged, counts as 0 (fail: duplicate)
5. Many walked long distances or carpooled to avoid using buses.  — check: negation_changed
