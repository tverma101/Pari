# ws2-full-p15-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> In Of Mice and Men, George and Lennie share a dream of owning a small farm together. For George, the dream gives him a reason to keep working hard even though his life is lonely. For Lennie, it is mostly about getting to take care of rabbits. Most of the other workers on the ranch have no one, so they are surprised that the two men travel together. Steinbeck uses their friendship to show how important it is to have someone who cares about you. When the dream falls apart at the end, it shows how hard it was for poor workers to change their lives during the Great Depression.

Selected: Most of the other workers on the ranch have no one, so they are surprised that the two men travel together.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-b5a6ef2b12e6`, raw sha256 `c6e419ed16cfff3c04fd2fcc2a9c3b4e3c3ab1f60516b685135ee72a907a99c9`

Format: strict (json_object), 5 options

1. Since most other workers on the ranch have no one, they are surprised the two men travel together.
2. Most workers on the ranch have no one, so they are shocked that the two men travel together.
3. Because most other workers on the ranch have no one, they are surprised that the two men travel together.  — not judged, counts as 0 (fail: duplicate)
4. Most of the other workers on the ranch have no one, which is why they are surprised that the two men travel together.  — not judged, counts as 0 (fail: duplicate)
5. Since most workers on the ranch have no one, they are surprised that the two men travel together.  — not judged, counts as 0 (fail: duplicate)
