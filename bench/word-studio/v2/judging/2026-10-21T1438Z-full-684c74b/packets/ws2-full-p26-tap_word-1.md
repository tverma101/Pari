# ws2-full-p26-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Every Saturday for the past two years, I have volunteered at a food bank in my neighborhood. At first, I only went because I needed community service hours for school. But after a few weeks, I started to really care about the people who came in. Many of them were working parents who just did not have enough money at the end of the month. One woman told me that the food we gave her was the only reason her kids had dinner that week. Hearing that made me realize how many people in my own town are struggling. Now I want to study social work so I can help families like hers.

Selected: Hearing that made me realize how many people in my own town are [[struggling]].

Instruction given to every model:

> Give 10 replacements for "struggling" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "struggling" without changing the rest of the sentence. Do not repeat "struggling" itself. Put the best options first.

## Output A

ref `o-b37556bb4607`, raw sha256 `8deeb4934d27c8d77fa8c6e26bfbc91c28aa8c0408ef3a8b8b86d3acba754a4e`

Format: lenient (json_object), 1 options

1. in need

## Output B

ref `o-04adaa30aa02`, raw sha256 `1724557943ee5cb55c242fe07bd9955f78eff7c37fa34e1c2ff716c32741d4d3`

Format: strict (json_object), 10 options

1. poor
2. in need
3. afflicted
4. needy
5. hard pressed
6. on the brink
7. burdened
8. facing difficulty
9. in distress
10. in need  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-e834e31407e8`, raw sha256 `cb59b075ca890663ec4f27627622905a0a5153cb07285f40a381b241ae21c769`

Format: lenient (json_object), 10 options

1. facing hardships
2. enduring difficulties
3. enduring financial challenges
4. facing economic challenges
5. facing tough times
6. enduring poverty
7. facing financial difficulties
8. enduring tough situations
9. facing economic hardship
10. enduring tough circumstances
