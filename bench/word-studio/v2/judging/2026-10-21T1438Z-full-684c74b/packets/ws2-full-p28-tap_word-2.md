# ws2-full-p28-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Lord of the Flies, a group of boys stranded on an island slowly lose their sense of right and wrong. At first, they choose Ralph as their leader and try to follow rules, like only speaking when they hold the conch shell. As time goes on, Jack becomes more interested in hunting than in keeping the signal fire going. More and more boys join Jack's tribe because it seems more fun than doing chores. By the end, the boys have turned violent, and two of them are dead. Golding uses the story to suggest that people can quickly become savage when there are no rules to control them.

Selected: By the end, the boys have turned [[violent]], and two of them are dead.

Instruction given to every model:

> Give 10 replacements for "violent" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "violent" without changing the rest of the sentence. Do not repeat "violent" itself. Put the best options first.

## Output A

ref `o-9fc3284ebeed`, raw sha256 `7339b5a53ce8027503b66ce4e99aa5ccd2bab8e03396b54cd4e9c368f6cb6145`

Format: strict (json_object), 10 options

1. aggressive
2. ferocious
3. brutal
4. savage
5. hostile
6. dangerous
7. bloodthirsty
8. reckless
9. uncontrollable
10. fierce

## Output B

ref `o-0c888edbc107`, raw sha256 `96fd6cc1219bb70c39701fe23dd4e88adef6c68dbfd4570bf639ec7067e9560d`

Format: strict (json_object), 10 options

1. ferocious
2. hostile
3. belligerent
4. aggressive
5. belligerent  — not judged, counts as 0 (fail: duplicate)
6. belligerent  — not judged, counts as 0 (fail: duplicate)
7. belligerent  — not judged, counts as 0 (fail: duplicate)
8. belligerent  — not judged, counts as 0 (fail: duplicate)
9. belligerent  — not judged, counts as 0 (fail: duplicate)
10. hostile  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-29cd0be3285e`, raw sha256 `5a9055db24a8e8898c2cc29be1d2a546318a119e84291f980da7a8b277e6adb4`

Format: strict (json_object), 10 options

1. ruthless
2. ferocious
3. bloodthirsty
4. aggressive
5. destructive
6. savage
7. feral
8. suspicious
9. dangerous
10. hostile
