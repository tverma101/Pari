# ws2-full-p41-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Every year, millions of tons of plastic end up in the ocean. Over time, sunlight and waves break this plastic into tiny pieces called microplastics. These pieces are so small that fish and other sea animals eat them by accident. Scientists have even found microplastics in drinking water, salt, and human blood. We still do not fully understand how they affect our health, but some studies suggest they could cause inflammation. Reducing how much plastic we use is the most important step we can take to fix this problem.

Selected: We still do not fully understand how they affect our health, but some studies suggest they could cause inflammation.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-d45585f9bad4`, raw sha256 `0200beac76b82435e74154efe349c05c2836a52a5d7c023dcc4a65d410a82e33`

Format: strict (json_object), 5 options

1. Scientists don't fully understand health effects, but studies suggest inflammation.
2. Health impacts remain unclear, though studies suggest possible inflammation.  — check: negation_changed
3. How they affect health is unknown, yet studies suggest inflammation.  — check: negation_changed
4. Health effects are unclear, but studies suggest they could cause inflammation.  — check: negation_changed
5. We don't fully understand health effects, but studies suggest inflammation.  — not judged, counts as 0 (fail: duplicate)
