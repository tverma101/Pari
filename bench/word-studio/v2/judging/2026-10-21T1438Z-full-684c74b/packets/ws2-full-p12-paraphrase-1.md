# ws2-full-p12-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Antibiotics are medicines that kill bacteria, and they have saved millions of lives since they were discovered. The problem is that bacteria can change over time so that the medicine does not work on them anymore. This happens faster when people take antibiotics they do not really need, like for a cold, which is caused by a virus. It also happens when people stop taking their pills early because they start to feel better. If this keeps going, simple infections could become deadly again. To stop this, doctors need to be careful about giving out antibiotics, and patients need to finish the whole treatment.

Selected: It also happens when people stop taking their pills early because they start to feel better.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-e1c65dd50198`, raw sha256 `81f21db3b6823afa7cb19674361df8db36a77c5d3d80a266729cd240d85b03d3`

Format: strict (json_object), 5 options

1. Stopping medication prematurely when feeling better is another issue.
2. People stopping their antibiotic course early due to feeling better is problematic.
3. Early cessation of antibiotics because of perceived improvement is also a concern.
4. When individuals stop their antibiotics early because they feel better, it creates problems.
5. A significant problem is people ending their antibiotics early once they start feeling better.

## Output B

ref `o-dd951796c96c`, raw sha256 `5b7e72ed25db2b7fc8b91b00de79d21995804cd4a7e33fa9fdf35bb27b200423`

Format: strict (json_object), 5 options

1. This also occurs when individuals discontinue their medication prematurely upon noticing improvement.
2. It also happens when patients cease their pill regimen early due to feeling better.
3. This situation arises when people stop their medication early because they begin to feel better.
4. It also occurs when individuals discontinue their treatment early as they start to feel better.
5. This happens when people stop taking their medication early because they start to feel better.

## Output C

ref `o-eacecfd32788`, raw sha256 `d6ad6dcf6fee8505db894da74d54933d3ddeb03128500eb2ecfdf6ba8408d7f7`

Format: lenient (json_object_then_text), 5 options

1. People often stop their antibiotics too soon when they start to feel better.
2. Stopping antibiotics early can happen when people feel better too quickly.
3. Individuals may prematurely end their antibiotic treatment due to feeling better.
4. Stopping the antibiotic course early is a common occurrence when people feel better.
5. People often cease taking antibiotics prematurely upon feeling better.
