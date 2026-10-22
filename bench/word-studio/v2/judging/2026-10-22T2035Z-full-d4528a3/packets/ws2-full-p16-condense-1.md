# ws2-full-p16-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> The Montgomery Bus Boycott was a key event in the civil rights movement. It started in December 1955 when Rosa Parks was arrested for refusing to give up her seat to a white passenger. In response, Black residents of Montgomery stopped riding the city buses for more than a year. Many people walked miles to work every day or set up carpools so that they would not have to use the buses. The boycott hurt the bus company because it lost most of its riders. In 1956, the Supreme Court ruled that segregation on buses was unconstitutional, and the boycott ended in victory.

Selected: Many people walked miles to work every day or set up carpools so that they would not have to use the buses.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-abc470c8de63`, raw sha256 `07b0ffca2fa34c88718b3a7b22c37ec78feec7033bd44712109750560f7bfe3a`

Format: strict (json_object), 5 options

1. Many walked miles or carpooled to avoid buses.  — check: negation_changed
2. Many walked miles or carpooled rather than ride.  — check: negation_changed
3. Many walked miles or used carpools to skip buses.  — check: negation_changed
4. Many walked or carpooled to avoid the buses.  — not judged, counts as 0 (fail: duplicate)
5. Many walked miles or carpooled instead of riding.  — check: negation_changed
