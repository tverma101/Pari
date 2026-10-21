# ws2-full-p12-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Antibiotics are medicines that kill bacteria, and they have saved millions of lives since they were discovered. The problem is that bacteria can change over time so that the medicine does not work on them anymore. This happens faster when people take antibiotics they do not really need, like for a cold, which is caused by a virus. It also happens when people stop taking their pills early because they start to feel better. If this keeps going, simple infections could become deadly again. To stop this, doctors need to be careful about giving out antibiotics, and patients need to finish the whole treatment.

Selected: To stop this, doctors need to be careful about [[giving out]] antibiotics, and patients need to finish the whole treatment.

Instruction given to every model:

> Give 10 single words that can replace "giving out" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-a67375a9570a`, raw sha256 `e5e7d4da48c03839ee0ff91b4bf72cdd6fbbbf318938f62ffca8981577e0b96a`

Format: strict (json_object), 10 options

1. prescribing
2. distributing
3. administering
4. supplying
5. dispensing
6. issuing
7. providing
8. giving
9. allocating
10. furnishing

## Output B

ref `o-59e4cbd10d64`, raw sha256 `ffbe61ac6f17134cd4ec9477941e2c9954c5d1a60aa8154c0a7a61d9547777df`

Format: strict (json_object), 10 options

1. dispensing
2. prescribing
3. allocating
4. administering
5. issuing
6. providing
7. handing out  — not judged, counts as 0 (fail: too_many_words)
8. exchanging
9. delivering
10. giving

## Output C

ref `o-9d3a0d1daddd`, raw sha256 `c103cc81f63375ec02a4c76b44c000537b1300a7ec869545bb6fa94fbd928c1e`

Format: strict (json_object), 10 options

1. prescribing
2. distributing
3. issuing
4. administering
5. dispensing
6. providing
7. supplying
8. releasing
9. authorizing
10. handing out  — not judged, counts as 0 (fail: too_many_words)
