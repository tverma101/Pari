# ws2-full-p09-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Some people think school uniforms are a bad idea, but I think they help students in many ways. First, uniforms make it harder for kids to judge each other based on how much their clothes cost. When everyone wears the same thing, students from poor families do not stand out as much. Second, uniforms save time in the morning because students do not have to pick out an outfit every day. Critics say that uniforms take away students' freedom to express themselves. However, students can still show who they are through their hobbies, their writing, and the way they treat others.

Selected: When everyone wears the same thing, students from poor families do not stand out as much.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-a7c9cc68685b`, raw sha256 `e1b8a0aa1e50e721548628edbb18b1f836d3bb065cefadc1767669feda5c6c1b`

Format: strict (json_object), 5 options

1. When everyone wears the same clothes, students from poor families do not stand out as much.
2. When all students wear identical outfits, those from poor families do not stand out as much.
3. When everyone dresses the same, students from poor families do not stand out as much.  — not judged, counts as 0 (fail: duplicate)
4. When all students wear the same uniform, those from poor families do not stand out as much.
5. When everyone wears the same attire, students from poor families do not stand out as much.  — not judged, counts as 0 (fail: duplicate)
