# ws2-full-p09-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Some people think school uniforms are a bad idea, but I think they help students in many ways. First, uniforms make it harder for kids to judge each other based on how much their clothes cost. When everyone wears the same thing, students from poor families do not stand out as much. Second, uniforms save time in the morning because students do not have to pick out an outfit every day. Critics say that uniforms take away students' freedom to express themselves. However, students can still show who they are through their hobbies, their writing, and the way they treat others.

Selected: When everyone wears the same thing, students from poor families do not stand out as much.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-4be1c0c4bfe1`, raw sha256 `b345c31b42caaab60924b387730ebcdcc3c2476e3489213c0b8fae6d16bd69f9`

Format: strict (json_object), 5 options

1. In this scenario, children from low-income backgrounds are less likely to be singled out.  — check: negation_changed
2. When all students dress alike, those from poorer families do not become noticeable.
3. If everyone wears identical clothing, pupils from disadvantaged homes stand out less.  — check: negation_changed
4. With everyone in uniform, students from less wealthy families are less conspicuous.  — check: negation_changed
5. When the same attire is worn by all, children from poorer households are less likely to be distinguished.  — check: negation_changed

## Output B

ref `o-4a23a7722605`, raw sha256 `1c4180ed08e5649bdde59740e2f10450399c1b07f92347f7655c93562d3643c5`

Format: strict (json_object), 5 options

1. Uniforms help to minimize the visibility of students from less affluent backgrounds.  — check: negation_changed
2. Wearing the same uniform means that students from poorer families are less noticeable.  — check: negation_changed
3. The uniformity in clothing helps to lessen the distinction of students from low-income families.  — check: negation_changed
4. Students from economically disadvantaged families blend in more when everyone wears uniforms.  — check: negation_changed
5. By wearing uniforms, the socioeconomic status of students becomes less apparent.  — check: negation_changed

## Output C

ref `o-af91984bb341`, raw sha256 `454ec271014ff1b981063a8a9edf59c1c0bf5051623e17cb0e9c2c9b68f0bcf9`

Format: lenient (json_object_then_text), 5 options

1. When everyone wears the same attire, students from modest backgrounds blend in less noticeably.  — check: negation_changed
2. When all students wear identical clothing, the economic status of students is less apparent.  — check: negation_changed
3. When uniforms are worn by all, students from lower-income families are not easily distinguished.
4. When students wear the same uniform, the economic disparity among them is less noticeable.  — check: negation_changed
5. When everyone is dressed the same, students from poorer families are not easily recognized.
