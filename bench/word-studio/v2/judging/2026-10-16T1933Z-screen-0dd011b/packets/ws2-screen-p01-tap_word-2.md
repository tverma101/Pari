# ws2-screen-p01-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Many schools are thinking about banning phones during class, and I think this is a good idea. When students have their phones out, they get distracted really easily and stop listening to the teacher. A lot of kids say they only use their phones to check the time, but most of the time they are actually on social media. In my opinion, I think that a ban would help students do better on tests because they would pay attention more. Some parents are worried that they will not be able to reach their kids in an emergency. However, the school office can always call a parent if something bad happens. Overall, a phone ban is a good way to make classrooms better places to learn.

Selected: However, the school office can always call a parent if something [[bad]] happens.

Instruction given to every model:

> Give 10 replacements for "bad" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "bad" without changing the rest of the sentence. Do not repeat "bad" itself. Put the best options first.

## Output A

ref `o-f8ec67a9380b`, raw sha256 `f62a741bf53fb961b10329215d5216e99b94d67a6805012a79a5cfa351eed607`

Format: strict (json_object), 10 options

1. worse
2. serious
3. detrimental
4. negative
5. unfortunate
6. critical
7. adverse
8. disastrous
9. grave
10. harmful

## Output B

ref `o-7350e41acc55`, raw sha256 `89bf7fbec7c7be5870bd3687d048b2a52819ca3f198f2e37ac391f5467c92932`

Format: strict (json_object), 10 options

1. serious
2. serious  — not judged, counts as 0 (fail: duplicate)
3. serious  — not judged, counts as 0 (fail: duplicate)
4. serious  — not judged, counts as 0 (fail: duplicate)
5. serious  — not judged, counts as 0 (fail: duplicate)
6. serious  — not judged, counts as 0 (fail: duplicate)
7. serious  — not judged, counts as 0 (fail: duplicate)
8. serious  — not judged, counts as 0 (fail: duplicate)
9. serious  — not judged, counts as 0 (fail: duplicate)
10. serious  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-d5b630587698`, raw sha256 `793dea75655688c8755d09e24c7977ed3ff34804dfa4612b8397949a8ba8d316`

Format: strict (json_object), 10 options

1. happens
2. occurs
3. happens  — not judged, counts as 0 (fail: duplicate)
4. happens  — not judged, counts as 0 (fail: duplicate)
5. happens  — not judged, counts as 0 (fail: duplicate)
6. happens  — not judged, counts as 0 (fail: duplicate)
7. happens  — not judged, counts as 0 (fail: duplicate)
8. happens  — not judged, counts as 0 (fail: duplicate)
9. happens  — not judged, counts as 0 (fail: duplicate)
10. happens  — not judged, counts as 0 (fail: duplicate)

## Output D

ref `o-6f4e10caa65b`, raw sha256 `7583e7f7725bd9e8bbae47daba2a7f34f5ea34063d614ca86c2ddf5bfc6ff2ae`

Format: strict (json_object), 10 options

1. serious
2. negative
3. urgent
4. troublesome
5. problematic
6. critical
7. severe
8. harmful
9. dangerous
10. adverse

## Output E

ref `o-c6c562f9644f`, raw sha256 `f05de95738785af5e385fc91c8748c1a6c5173a9deb058d37d8e5eec61bb1e93`

Format: lenient (json_object_then_text), 10 options

1. negative
2. problematic
3. troublesome
4. harmful
5. serious
6. serious  — not judged, counts as 0 (fail: duplicate)
7. bad  — not judged, counts as 0 (fail: echo)
8. difficult
9. critical
10. problematic  — not judged, counts as 0 (fail: duplicate)
