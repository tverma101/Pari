# ws2-full-p09-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Some people think school uniforms are a bad idea, but I think they help students in many ways. First, uniforms make it harder for kids to judge each other based on how much their clothes cost. When everyone wears the same thing, students from poor families do not stand out as much. Second, uniforms save time in the morning because students do not have to pick out an outfit every day. Critics say that uniforms take away students' freedom to express themselves. However, students can still show who they are through their hobbies, their writing, and the way they treat others.

Selected: When everyone wears the same thing, students from [[poor]] families do not stand out as much.

Instruction given to every model:

> Give 10 replacements for "poor" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "poor" without changing the rest of the sentence. Do not repeat "poor" itself. Put the best options first.

## Output A

ref `o-9900747b71f5`, raw sha256 `69c88069176fb7908f9fd641b1cb5f1c7fdfe0e161bcb6110e7b5b714c62e693`

Format: strict (json_object), 11 options

1. less affluent
2. low-income
3. underprivileged
4. economically disadvantaged
5. financially challenged
6. less fortunate
7. lower-income
8. hardship-stricken
9. economically struggling
10. struggling financially
11. less well-off  — not judged, counts as 0 (fail: beyond_requested)

## Output B

ref `o-7f107bf49eaa`, raw sha256 `0cb66ed97c9934a9f54ac6284775c06111aff1c545a993d7322dbbf52439841e`

Format: strict (json_object), 10 options

1. low-income families
2. less affluent families
3. working-class families
4. working families
5. middle-class families
6. working-class
7. working families  — not judged, counts as 0 (fail: duplicate)
8. middle-income families
9. less well-off families
10. working families  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-07f3485a8237`, raw sha256 `31ac10dba0aabd9b968388d664d7a487c9c0a0aa24e269593701c02bbeb4a8f5`

Format: strict (json_object), 10 options

1. low-income
2. financially disadvantaged
3. less wealthy
4. limited means
5. economically struggling
6. modest
7. working-class
8. financially challenged
9. less privileged
10. lower income
