# ws2-full-p19-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Standardized tests like the SAT are supposed to measure how ready students are for college, but they do not tell the whole story. A student's score can depend a lot on whether their family could pay for tutoring and practice books. Some students are also very nervous test-takers, so their scores do not show what they actually know. Because of this, more than 1,800 colleges have made the SAT optional. I think colleges should look at grades, essays, and activities instead of focusing on one test score.

Selected: A student's score can depend a lot on whether their family could [[pay for]] tutoring and practice books.

Instruction given to every model:

> Give 10 single words that can replace "pay for" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-147f960bc6b7`, raw sha256 `2258bedd8782428eccda11d6f2e487ae1c9b03ac3483b6660e78e7e7f46d6085`

Format: strict (json_object), 10 options

1. afford
2. cover
3. spend
4. sponsor
5. finance
6. purchase
7. support
8. invest
9. secure
10. allocate

## Output B

ref `o-2ae5d2f993d5`, raw sha256 `33403011337b481d7181fb3289ca4f6b8a91ff045e5e946b0fc7a7d83863a746`

Format: strict (json_object), 10 options

1. afford
2. spend
3. cover
4. buy
5. purchase
6. fund
7. finance
8. support
9. buy  — not judged, counts as 0 (fail: duplicate)
10. pay

## Output C

ref `o-c176472a75f8`, raw sha256 `5e35bf5158a4f6476335734104fc9cafe5b79fa0fc2b4044440ae878cb522206`

Format: strict (json_object), 10 options

1. afford
2. provide
3. cover
4. support
5. furnish
6. supply
7. allow
8. enable
9. give
10. grant
