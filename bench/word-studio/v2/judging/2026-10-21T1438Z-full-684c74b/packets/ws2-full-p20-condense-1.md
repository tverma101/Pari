# ws2-full-p20-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Romeo and Juliet is often called a love story, but it is also a story about how acting too fast can lead to disaster. Romeo and Juliet meet, fall in love, and get married in less than a week. Neither of them stops to think about what their families will do when they find out. Friar Laurence even warns Romeo that "they stumble that run fast," but Romeo does not listen. When Romeo hears that Juliet is dead, he kills himself right away instead of waiting to learn the truth. If the two young lovers had slowed down, the play might have had a happy ending.

Selected: Neither of them stops to think about what their families will do when they find out.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-cb552f2055fc`, raw sha256 `79849c932b200474cfb6b6c7beb170127567f2a7b9d4f02eb5fa9a505c52fc19`

Format: strict (json_object), 5 options

1. Neither thinks of their families' reaction.
2. Neither considers their families' response.
3. Neither ponders their families' reaction.
4. Neither thinks about their families' discovery.
5. Neither reflects on their families' reaction.

## Output B

ref `o-744e9b6e053e`, raw sha256 `4bbf0a94eacd4e8dd57b4fce5d34895d72658a967fe591860defc3012b808f56`

Format: strict (json_object), 5 options

1. They do not consider what their families will do upon learning.
2. They fail to think about their families' reaction to the news.
3. They do not ponder what their families will do when they discover.
4. They do not reflect on their families' response if they find out.
5. They do not consider what their families will do upon discovery.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-975d0b010cef`, raw sha256 `2a0e455126e072b4e23866916c3cbf4d231a93a5511e6f35703a6c094e49be46`

Format: lenient (json_object_then_text), 5 options

1. They fail to consider their families' reactions.
2. They overlook their families' potential response.  — check: negation_changed
3. They don't worry about their families finding out.
4. They ignore the possibility of their families' reaction.  — check: negation_changed
5. They neglect their families' reaction when they learn of it.  — check: negation_changed
