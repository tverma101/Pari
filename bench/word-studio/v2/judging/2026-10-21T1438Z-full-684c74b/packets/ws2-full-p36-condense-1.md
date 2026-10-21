# ws2-full-p36-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Renewable energy comes from sources that do not run out, like the sun, wind, and water. Unlike coal and oil, these sources do not release a lot of greenhouse gases when they make electricity. In the last ten years, the cost of solar panels has dropped so much that solar power is now cheaper than coal in many places. One problem is that the sun does not always shine and the wind does not always blow, so we need better batteries to store the energy. Even with these challenges, switching to renewable energy is one of the best ways to slow down climate change.

Selected: One problem is that the sun does not always shine and the wind does not always blow, so we need better batteries to store the energy.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-f92110a70853`, raw sha256 `296a8de2c8d2d594ff01b97af57c107b5bf3115ca8ebfc0967bb85bacaeb2f02`

Format: strict (json_object), 5 options

1. Sun and wind are intermittent, necessitating improved energy storage.  — check: negation_changed
2. Intermittent sun and wind require better batteries for energy storage.  — check: negation_changed
3. The sun and wind don't always provide power, so we need better batteries.
4. Sun and wind intermittency needs better battery storage.  — check: negation_changed
5. Energy storage needs improvement due to inconsistent sun and wind.  — check: negation_changed

## Output B

ref `o-8dd855a1419b`, raw sha256 `01c4cfb8afb2f72590d9a460e1242a85b27ca7bf5311d290be20c0f455070b9a`

Format: strict (json_object), 5 options

1. A challenge is that the sun and wind are not constant, requiring better batteries for storage.
2. We need better batteries because the sun and wind are not always available.
3. The sun and wind are not always reliable, so we need better batteries to store energy.
4. Since the sun and wind are intermittent, we need improved batteries to store the energy.  — check: negation_changed
5. Intermittent sun and wind require better batteries to store the energy.  — check: negation_changed

## Output C

ref `o-8050b52298dd`, raw sha256 `2f9f8cb6fe33603d3d2f562265d48a9aedc1ac07cdb32a5844c3971a5e8247a8`

Format: lenient (json_object_then_text), 5 options

1. The sun doesn't always shine and the wind doesn't always blow, so better batteries are needed to store energy.
2. Without constant sun and wind, better batteries are required for energy storage.
3. Because the sun and wind aren't always available, we need improved batteries to store energy.
4. With unreliable sun and wind, better batteries are necessary for storing energy.  — check: negation_changed
5. The sun and wind aren't always available, so we must develop better batteries for energy storage.
