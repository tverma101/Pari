# ws2-full-p31-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Many students say they have too much homework, and I agree that it can sometimes do more harm than good. After a full day of classes, students still have to spend three or four hours on assignments every night. This leaves them with very little time for sports, family, or sleep. Some homework is helpful because it lets students practice what they learned in class. But when teachers give busywork just to fill time, students get tired and stop caring about learning. Schools should set limits on homework so that it is useful and not overwhelming.

Selected: But when teachers give busywork just to fill time, students get tired and stop caring about learning.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-1ea64d704ce7`, raw sha256 `82823bfcceb767231b94aaf66147b88548089235f6b9ee72d025bf3aab8966f6`

Format: strict (json_object), 5 options

1. However, when instructors assign tasks merely to consume time, students become exhausted and lose interest in learning.
2. Yet if teachers provide busywork simply to fill the gap, pupils grow weary and cease to care about education.
3. But when educators assign filler tasks just to occupy time, learners fatigue and stop valuing the learning process.
4. Still, if teachers give busywork only to fill the void, students tire out and no longer care about learning.  — check: negation_changed
5. However, when teachers hand out busywork solely to fill time, students become tired and stop caring about the subject.

## Output B

ref `o-b6fd30a9fe36`, raw sha256 `433ad094044460e60311637f403d2cafec49ecbac415ba5e94f47aa09610cdad`

Format: strict (json_object), 5 options

1. However, when teachers assign tedious tasks merely to occupy time, students become exhausted and lose interest in learning.
2. When teachers hand out monotonous work just to fill time, students grow weary and disengage from learning.
3. If teachers provide repetitive tasks just to occupy time, students become fatigued and lose their enthusiasm for learning.
4. When educators give students mundane work simply to pass time, the students become worn out and lose their passion for learning.
5. Students become demotivated and lose interest in learning when teachers assign dull tasks just to fill their time.

## Output C

ref `o-140de0d6c9ee`, raw sha256 `eabb7a88e277f0da89f25b8abaf9266b8ef207d85e1641d2e8c260f2f5702066`

Format: lenient (json_object), 5 options

1. But teachers often assign busywork to fill the time, which exhausts students and makes them lose interest in learning.
2. When teachers give unnecessary work, students get tired and lose their motivation to learn.
3. Teachers should avoid assigning busywork, as it leads to students feeling tired and disengaging from learning.
4. Busywork assigned by teachers can make students feel drained and decrease their enthusiasm for learning.
5. If teachers give too much work, students become exhausted and lose their interest in learning.
