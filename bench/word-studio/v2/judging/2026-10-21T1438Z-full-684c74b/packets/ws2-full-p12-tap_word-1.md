# ws2-full-p12-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Antibiotics are medicines that kill bacteria, and they have saved millions of lives since they were discovered. The problem is that bacteria can change over time so that the medicine does not work on them anymore. This happens faster when people take antibiotics they do not really need, like for a cold, which is caused by a virus. It also happens when people stop taking their pills early because they start to feel better. If this keeps going, simple infections could become deadly again. To stop this, doctors need to be careful about giving out antibiotics, and patients need to finish the whole treatment.

Selected: The problem is that bacteria can [[change]] over time so that the medicine does not work on them anymore.

Instruction given to every model:

> Give 10 replacements for "change" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "change" without changing the rest of the sentence. Do not repeat "change" itself. Put the best options first.

## Output A

ref `o-cdaa9fe9429f`, raw sha256 `83812e14b8caad6c833306d36c34cbe3ff5b4d51f31799b47ca9247cee35f0bb`

Format: strict (json_object), 10 options

1. evolve
2. adapt
3. develop resistance
4. mutate
5. alter
6. transform
7. shift
8. modify
9. develop
10. adjust

## Output B

ref `o-4dd7de04ed19`, raw sha256 `cf7e344db2ff55f735451f4b46d494a3c8c49aedf956d20329b923b7bdef98b9`

Format: strict (json_object), 10 options

1. alter
2. evolve
3. mutate
4. transform
5. adapt
6. shift
7. modify
8. progress
9. develop
10. reform

## Output C

ref `o-e8915cc1f073`, raw sha256 `a2983007c775e97d88dfdf00e230f97297b3bb494f2457f9061c2b6fb8518a53`

Format: strict (json_object), 10 options

1. adapt
2. evolve
3. mutate
4. adapt  — not judged, counts as 0 (fail: duplicate)
5. shift
6. transform
7. modify
8. alter
9. develop
10. adjust
