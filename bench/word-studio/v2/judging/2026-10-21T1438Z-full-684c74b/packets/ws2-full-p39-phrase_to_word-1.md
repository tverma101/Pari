# ws2-full-p39-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Fast food companies spend billions of dollars every year on ads that are aimed at children. These commercials often use cartoon characters, bright colors, and free toys to make kids want to eat there. Young children cannot always tell the difference between an ad and a regular TV show, so they believe what the ads say. This is a problem because eating too much fast food can lead to health issues like obesity and diabetes. I believe the government should put stronger limits on food ads that target kids, the same way it does for cigarette ads.

Selected: Fast food companies spend billions of dollars every year on ads that [[are aimed at]] children.

Instruction given to every model:

> Give 10 single words that can replace "are aimed at" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-99e8070c67ad`, raw sha256 `074e3a7de51b557f27038657d9d25769a57d187247ee0e14955c979d0507208d`

Format: strict (json_object), 10 options

1. directed
2. focused
3. targeted
4. intended
5. designed
6. pointed
7. turned
8. aimed
9. specially
10. specifically

## Output B

ref `o-4c925f53a572`, raw sha256 `4ee79ae4c1be23ecd89975950e999ababa66a5306cdb2fa25eb7aa33f7eac34d`

Format: strict (json_object), 10 options

1. targeted at  — not judged, counts as 0 (fail: too_many_words)
2. designed for  — not judged, counts as 0 (fail: too_many_words)
3. intended for  — not judged, counts as 0 (fail: too_many_words)
4. geared towards  — not judged, counts as 0 (fail: too_many_words)
5. aimed at  — not judged, counts as 0 (fail: too_many_words)
6. directed at  — not judged, counts as 0 (fail: too_many_words)
7. sought after by  — not judged, counts as 0 (fail: too_many_words)
8. focus on  — not judged, counts as 0 (fail: too_many_words)
9. centered on  — not judged, counts as 0 (fail: too_many_words)
10. concentrated on  — not judged, counts as 0 (fail: too_many_words)

## Output C

ref `o-26ff3c84b372`, raw sha256 `b99d1da302411f90fa884ecdbaf9c877297ee48fa106f73a84cd339b37844da1`

Format: strict (json_object), 10 options

1. targeted at  — not judged, counts as 0 (fail: too_many_words)
2. focused on  — not judged, counts as 0 (fail: too_many_words)
3. directed towards  — not judged, counts as 0 (fail: too_many_words)
4. intended for  — not judged, counts as 0 (fail: too_many_words)
5. aimed at  — not judged, counts as 0 (fail: too_many_words)
6. targeting
7. targeted
8. directed at  — not judged, counts as 0 (fail: too_many_words)
9. intended for  — not judged, counts as 0 (fail: duplicate, too_many_words)
10. aimed at  — not judged, counts as 0 (fail: duplicate, too_many_words)
