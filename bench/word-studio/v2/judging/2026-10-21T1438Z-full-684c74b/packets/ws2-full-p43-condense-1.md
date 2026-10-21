# ws2-full-p43-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> World War I had many causes, but the event that started it was the assassination of Archduke Franz Ferdinand in 1914. Before that, the major powers of Europe had already been building up their armies and making alliances with each other. These alliances meant that a fight between two countries could quickly pull in many others. When Austria-Hungary declared war on Serbia, Russia came to Serbia's defense, and then Germany, France, and Britain joined in. Nationalism also played a big role, because many people were proud of their countries and eager to prove their strength.

Selected: Before that, the major powers of Europe had already been building up their armies and making alliances with each other.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-d00f56958c22`, raw sha256 `776ae32802a6cb67f459d0471db65317a2b4bb0c034729d822e6aca3727470a1`

Format: strict (json_object), 5 options

1. Prior to this, European powers were already amassing armies and forming alliances.
2. Earlier, major European nations had been expanding their armies and forging alliances.
3. Before this, the great powers of Europe were already building up armies and creating alliances.
4. Previously, Europe's major powers had already been strengthening their armies and establishing alliances.
5. Before this, major European powers were already amassing armies and making alliances.

## Output B

ref `o-9bd60514294f`, raw sha256 `b237f040d802936e1df06b345e4a1c4a63ef81c0c67c0f9f7b9b558f4f892aff`

Format: strict (json_object), 5 options

1. Prior to the assassination, European powers were amassing military forces and forming alliances.
2. Before the assassination, Europe’s major powers were building armies and creating alliances.
3. Before the assassination, the major European powers were preparing armies and forming alliances.
4. Before the assassination, the major European powers were increasing military strength and forming alliances.
5. Before the assassination, the major European powers were building armies and establishing alliances.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-1581e53af233`, raw sha256 `a22fa112d2996f563914d516708e2d922fda2f65585501a471e46abb7c38790d`

Format: lenient (json_object_then_text), 5 options

1. The major powers of Europe had already been arming themselves and forming alliances.
2. Europe's major powers had been amassing armies and forging alliances before the war.
3. Before the war, the major powers of Europe had been building up their military forces and making alliances.
4. Europe's major powers had already begun to prepare for war by building armies and forming alliances.
5. Before the assassination, the major powers of Europe had been preparing for war by building armies and making alliances.
