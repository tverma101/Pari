# ws2-full-p25-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> The Dust Bowl was a period in the 1930s when huge dust storms hit the Great Plains. Farmers had plowed up the grass that held the soil in place, and then a long drought dried everything out. When strong winds came, they picked up the loose dirt and created clouds of dust so thick that people could not see the sun. Crops died, animals got sick, and many families lost their farms. Thousands of people packed up their belongings and moved west to California looking for work. The disaster taught the government that it needed to help farmers protect the land.

Selected: Thousands of people packed up their belongings and moved west to California [[looking for]] work.

Instruction given to every model:

> Give 10 single words that can replace "looking for" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-034e83758cca`, raw sha256 `65e52a551d6cbf3c78e61f8f7cdbd862de069f8c74e315ac4948510a1a94f7dc`

Format: strict (json_object), 5 options

1. seeking
2. seeking  — not judged, counts as 0 (fail: duplicate)
3. seeking  — not judged, counts as 0 (fail: duplicate)
4. seeking  — not judged, counts as 0 (fail: duplicate)
5. seeking  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-1edf9a1e106d`, raw sha256 `84abb54780f8f0ffcbc8e8ac6d32ea8db77455337a6b9bc5fd9eef178efe23bb`

Format: strict (json_object), 10 options

1. seeking
2. pursuing
3. in search of  — not judged, counts as 0 (fail: too_many_words)
4. hunting for  — not judged, counts as 0 (fail: too_many_words)
5. questing
6. scouring
7. gathering
8. searching for  — not judged, counts as 0 (fail: too_many_words)
9. pursuing  — not judged, counts as 0 (fail: duplicate)
10. hunting for  — not judged, counts as 0 (fail: duplicate, too_many_words)

## Output C

ref `o-d217dbf0118e`, raw sha256 `61182b5b9c1287e7bac29e2a2bd913cf5b38c17d040ef282e5fa9d1d46410dbd`

Format: strict (json_object), 10 options

1. seeking
2. searching for  — not judged, counts as 0 (fail: too_many_words)
3. in search of  — not judged, counts as 0 (fail: too_many_words)
4. in search of work  — not judged, counts as 0 (fail: too_many_words)
5. hoping to find  — not judged, counts as 0 (fail: too_many_words)
6. trying to obtain  — not judged, counts as 0 (fail: too_many_words)
7. aiming to get  — not judged, counts as 0 (fail: too_many_words)
8. looking for  — not judged, counts as 0 (fail: echo, too_many_words)
9. after
10. in pursuit of  — not judged, counts as 0 (fail: too_many_words)
