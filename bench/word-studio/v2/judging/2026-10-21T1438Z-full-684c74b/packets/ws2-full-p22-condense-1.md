# ws2-full-p22-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Coral reefs are some of the most beautiful places on Earth, but they are in serious trouble. When the ocean gets too warm, corals push out the tiny algae that live inside them and give them their color. This is called coral bleaching, and if the water stays hot for too long, the coral can die. Reefs are home to about a quarter of all ocean species, so losing them would hurt a lot of sea life. They also protect coastlines from big waves during storms. Cutting down on pollution and greenhouse gases is the best way to give reefs a chance to recover.

Selected: When the ocean gets too warm, corals push out the tiny algae that live inside them and give them their color.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-1f64c4aef3c7`, raw sha256 `c39ad3db3a00f9edca52a9a57d97f32483620ef13769c0da6946a75ef946f955`

Format: strict (json_object), 5 options

1. Coral bleaching occurs when corals expel algae due to high ocean temperatures.
2. The loss of algae by corals due to warm water causes bleaching.
3. When corals are exposed to excessive heat, they expel their algae, leading to bleaching.
4. Bleaching happens when corals are forced to expel algae from their bodies due to rising water temperatures.
5. Corals expel their algae when the ocean becomes too warm, resulting in bleaching.

## Output B

ref `o-3c8ab2407b57`, raw sha256 `9ae8d43622a79a7808c020db57f7f47e3fb61be8b53631319c3de514ca895de1`

Format: strict (json_object), 5 options

1. When the ocean warms, corals expel the algae that provide their color.
2. As ocean temperatures rise, corals eject the algae inside them responsible for their color.
3. Warm ocean water causes corals to expel the algae giving them color.
4. When ocean water gets too hot, corals expel the algae that give them color.
5. If the ocean warms, corals expel the algae that provide their color.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-7118bb5dfbb3`, raw sha256 `d5cee3ef8f6389ff204d3550d549a16d2d08a9349007e45b51bc21e0e7009baf`

Format: strict (json_object), 5 options

1. Corals expel the algae that color them when the ocean heats up.
2. Corals lose their color by releasing their algae when water is too warm.
3. Corals push out their coloring algae when the ocean becomes too warm.
4. Corals expel their color-giving algae in warmer waters.
5. Corals release their color-providing algae when the ocean temperature rises.
