# ws2-full-p25-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> The Dust Bowl was a period in the 1930s when huge dust storms hit the Great Plains. Farmers had plowed up the grass that held the soil in place, and then a long drought dried everything out. When strong winds came, they picked up the loose dirt and created clouds of dust so thick that people could not see the sun. Crops died, animals got sick, and many families lost their farms. Thousands of people packed up their belongings and moved west to California looking for work. The disaster taught the government that it needed to help farmers protect the land.

Selected: Farmers had plowed up the grass that held the soil in place, and then a long drought dried everything out.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-ca41cbbde75d`, raw sha256 `04815d0767a6e65543ef9d00dae4d0361040ae90496f39904b03f035efc16511`

Format: strict (json_object), 5 options

1. Farmers removed the grass that kept the soil in place, and then a long drought dried everything out.
2. Farmers plowed away the grass that held the soil, and then a long drought dried everything out.
3. Farmers dug up the grass that held the soil in place, and then a long drought dried everything out.  — not judged, counts as 0 (fail: duplicate)
4. Farmers turned over the grass that held the soil, and then a long drought dried everything out.  — not judged, counts as 0 (fail: duplicate)
5. Farmers plowed up the grass that kept the soil, and then a long drought dried everything out.  — not judged, counts as 0 (fail: duplicate)
