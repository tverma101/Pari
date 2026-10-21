# ws2-full-p48-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Some people think public libraries are not needed anymore because everything is online, but I strongly disagree. Libraries give free internet and computers to people who cannot afford them at home. They also offer programs like reading groups for kids, job help for adults, and English classes for immigrants. For many people, the library is one of the only safe and quiet places where they can study. If cities cut library funding, the people who would be hurt the most are the ones who already have the least. That is why we should keep supporting our libraries.

Selected: That is why we should [[keep supporting]] our libraries.

Instruction given to every model:

> Give 10 single words that can replace "keep supporting" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-c3ffedc5898b`, raw sha256 `ee9ee9ca83102516237d5f1fa45a5c64beee6c6c7d6d867d99f5665f0784b483`

Format: strict (json_object), 10 options

1. backing
2. funding
3. aiding
4. fostering
5. sustaining
6. upholding
7. maintaining
8. advocating
9. defending
10. promoting

## Output B

ref `o-beb5c32ffc10`, raw sha256 `491fd6d5627fc2153b493534228491936521a49fe8f3689ccb2f3fed653dbed2`

Format: strict (json_object), 10 options

1. support
2. continue to support  — not judged, counts as 0 (fail: too_many_words)
3. maintain support  — not judged, counts as 0 (fail: too_many_words)
4. uphold support  — not judged, counts as 0 (fail: too_many_words)
5. defend support  — not judged, counts as 0 (fail: too_many_words)
6. advocate for support  — not judged, counts as 0 (fail: too_many_words)
7. promote support  — not judged, counts as 0 (fail: too_many_words)
8. endorse support  — not judged, counts as 0 (fail: too_many_words)
9. back support  — not judged, counts as 0 (fail: too_many_words)
10. bolster support  — not judged, counts as 0 (fail: too_many_words)

## Output C

ref `o-21fdb004dbe1`, raw sha256 `5ec2a5034bf4c8e40ee69bfb179cb39b1b9d16a4bc3c0bb36806338a90f8dbe8`

Format: strict (json_object), 10 options

1. maintain
2. uphold
3. preserve
4. defend
5. sustain
6. fortify
7. uphold  — not judged, counts as 0 (fail: duplicate)
8. encourage
9. promote
10. bolster
