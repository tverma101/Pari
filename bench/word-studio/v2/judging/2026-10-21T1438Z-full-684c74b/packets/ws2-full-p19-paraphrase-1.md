# ws2-full-p19-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Standardized tests like the SAT are supposed to measure how ready students are for college, but they do not tell the whole story. A student's score can depend a lot on whether their family could pay for tutoring and practice books. Some students are also very nervous test-takers, so their scores do not show what they actually know. Because of this, more than 1,800 colleges have made the SAT optional. I think colleges should look at grades, essays, and activities instead of focusing on one test score.

Selected: Because of this, more than 1,800 colleges have made the SAT optional.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-05f2a12e2425`, raw sha256 `f4dadc156b15f84475c8d4c1930ef9513b7568a32715c51a215c67460e318155`

Format: strict (json_object), 5 options

1. Due to these reasons, over 1,800 institutions have opted to make the SAT optional.
2. Owing to these factors, more than 1,800 colleges have chosen to make the SAT optional.
3. As a result, more than 1,800 colleges have made the SAT optional.
4. Consequently, over 1,800 colleges have decided to make the SAT optional.
5. Following this, more than 1,800 colleges have made the SAT optional.

## Output B

ref `o-3daedbe495ea`, raw sha256 `a1743e5bf301ccb672bd4938b6d84222b71e02ae3e3ebb7c3099a711f7cce0d2`

Format: strict (json_object), 5 options

1. Consequently, over 1,800 institutions have rendered the SAT an optional requirement.
2. As a result, more than 1,800 colleges have made the SAT optional.
3. Due to this, over 1,800 universities have declared the SAT optional.
4. For this reason, more than 1,800 colleges have chosen to make the SAT optional.
5. Consequently, over 1,800 colleges have made the SAT optional.

## Output C

ref `o-f5fb09733cd3`, raw sha256 `39a2a0c77cb3f09beef477a485b04f819d72ed13102cc08dc7065d2a65bad896`

Format: lenient (json_object_then_text), 5 options

1. More than 1,800 colleges have decided to drop the SAT requirement.
2. Over 1,800 institutions have become SAT optional.
3. More than 1,800 colleges have chosen to not require the SAT.  — check: negation_changed
4. More than 1,800 colleges have removed the SAT from their admissions process.
5. More than 1,800 colleges have made the SAT optional as part of their admission process.
