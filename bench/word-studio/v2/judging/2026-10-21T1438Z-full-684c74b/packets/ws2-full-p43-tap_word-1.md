# ws2-full-p43-tap_word-1

Kind: `tap_word`, asks for 10 options.

Paragraph:

> World War I had many causes, but the event that started it was the assassination of Archduke Franz Ferdinand in 1914. Before that, the major powers of Europe had already been building up their armies and making alliances with each other. These alliances meant that a fight between two countries could quickly pull in many others. When Austria-Hungary declared war on Serbia, Russia came to Serbia's defense, and then Germany, France, and Britain joined in. Nationalism also played a big role, because many people were proud of their countries and eager to prove their strength.

Selected: These alliances meant that a fight between two countries could quickly [[pull]] in many others.

Instruction given to every model:

> Give 10 replacements for "pull" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "pull" without changing the rest of the sentence. Do not repeat "pull" itself. Put the best options first.

## Output A

ref `o-fd80fe996957`, raw sha256 `e70b5c045ca2908915fabac5b310d0a9c8a22814554e6a13092912e1a6b272a4`

Format: strict (json_object), 10 options

1. draw in
2. bring in
3. draw others
4. draw in many
5. draw other countries
6. draw other nations
7. draw other allies
8. bring other countries
9. draw other powers
10. draw other countries in  — not judged, counts as 0 (fail: duplicate, too_many_words)

## Output B

ref `o-468b4b5cd8a0`, raw sha256 `463f0dfc21041aebcdf637fe6afb72099a2f95855d593b7cdd77f9e098ed4f5e`

Format: strict (json_object), 10 options

1. draw in
2. bring in
3. involve
4. drag in
5. include
6. involves  — not judged, counts as 0 (fail: duplicate)
7. entangle
8. draw in  — not judged, counts as 0 (fail: duplicate)
9. involve  — not judged, counts as 0 (fail: duplicate)
10. include  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-ac003287d75a`, raw sha256 `05cb0f434e1e263a2de167cff33dca8009c0bbc8a2a32b8f9479860c9e058db2`

Format: strict (json_object), 10 options

1. drag
2. involve
3. draw
4. engage
5. draw in
6. enlist
7. recruit
8. gather
9. bring in
10. entail
