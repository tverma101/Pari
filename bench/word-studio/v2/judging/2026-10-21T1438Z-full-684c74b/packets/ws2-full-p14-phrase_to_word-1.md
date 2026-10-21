# ws2-full-p14-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Some school districts have switched to a four-day school week to save money and give students more time to rest. Supporters say that teachers are less tired and students come to school more ready to learn. The extra day off can also be used for doctor appointments, jobs, or family time. However, the longer school days can be hard for younger kids who have trouble focusing for that long. Working parents might also have to pay for childcare on the fifth day, which could be a problem for families without much money. Before more districts make this change, they should look closely at how it affects students' learning.

Selected: Before more districts make this change, they should [[look closely at]] how it affects students' learning.

Instruction given to every model:

> Give 10 single words that can replace "look closely at" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-3a8f8981ee44`, raw sha256 `826fe72dfade70a0925d4dc764849066a5ef8e07ba4440d0923347106c05a9ed`

Format: strict (json_object), 10 options

1. examine
2. study
3. investigate
4. analyze
5. scrutinize
6. review
7. expose
8. scrutinize  — not judged, counts as 0 (fail: duplicate)
9. check
10. evaluate

## Output B

ref `o-777fb0c5a2a1`, raw sha256 `3ec2511051ad49944fa713739bdfac741bf9dc4262ba3278cf62c3681ee2837b`

Format: lenient (json_object), 10 options

1. evaluate
2. assess
3. consider
4. analyze
5. review
6. study
7. examine
8. scrutinize
9. inspect
10. investigate

## Output C

ref `o-cea92b3aeca2`, raw sha256 `82a0d7c5d125657828d788fb6c625384c393c97da84b3e633834fcc28314d78e`

Format: strict (json_object), 10 options

1. examine
2. investigate
3. scrutinize
4. assess
5. review
6. study
7. evaluate
8. analyze
9. observe
10. inspect
