# ws2-full-p28-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Lord of the Flies, a group of boys stranded on an island slowly lose their sense of right and wrong. At first, they choose Ralph as their leader and try to follow rules, like only speaking when they hold the conch shell. As time goes on, Jack becomes more interested in hunting than in keeping the signal fire going. More and more boys join Jack's tribe because it seems more fun than doing chores. By the end, the boys have turned violent, and two of them are dead. Golding uses the story to suggest that people can quickly become savage when there are no rules to control them.

Selected: More and more boys join Jack's tribe because it seems more [[fun]] than doing chores.

Instruction given to every model:

> Give 10 replacements for "fun" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "fun" without changing the rest of the sentence. Do not repeat "fun" itself. Put the best options first.

## Output A

ref `o-328f58f08818`, raw sha256 `ab315c35726b8a82df8cba229f91971fbc9830135df5988f8b4844e1ac754810`

Format: strict (json_object), 10 options

1. exciting
2. entertaining
3. enjoyable
4. pleasing
5. enthralling
6. captivating
7. stimulating
8. adventurous
9. thrilling
10. delightful

## Output B

ref `o-ced3abb6de53`, raw sha256 `aa285fe402477de679d1350e03b4b96d959cf4695eb7f7d0a57f8a7aef615870`

Format: strict (json_object), 10 options

1. exciting
2. appealing
3. enjoyable
4. entertaining
5. pleasurable
6. satisfying
7. amusing
8. stimulating
9. rewarding
10. appealing  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-51d248c1cef8`, raw sha256 `1da275c1d110dc7f06ffb1d5c0f81283ec20e512501445a64cbdf4aacf880003`

Format: strict (json_object), 11 options

1. enjoyable
2. pleasurable
3. entertaining
4. exciting
5. amusing
6. recreational
7. delightful
8. joyful
9. thrilling
10. satisfying
11. whimsical  — not judged, counts as 0 (fail: beyond_requested)
