# ws2-full-p48-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Some people think public libraries are not needed anymore because everything is online, but I strongly disagree. Libraries give free internet and computers to people who cannot afford them at home. They also offer programs like reading groups for kids, job help for adults, and English classes for immigrants. For many people, the library is one of the only safe and quiet places where they can study. If cities cut library funding, the people who would be hurt the most are the ones who already have the least. That is why we should keep supporting our libraries.

Selected: Some people think public libraries are not needed anymore because everything is online, but I strongly disagree.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-f4f5bf9bc6a7`, raw sha256 `2661ff12712debc8750347b21654272ed1e3821ee0c89b8ba31cff81afa4e139`

Format: strict (json_object), 5 options

1. Some argue public libraries are obsolete due to online access, yet I strongly disagree.  — check: negation_changed
2. Critics claim public libraries are unnecessary because of the internet, but I strongly disagree.  — check: negation_changed
3. While some believe online resources replace libraries, I strongly disagree.  — check: negation_changed
4. Many think public libraries are no longer needed, but I strongly disagree.
5. Some say public libraries are redundant in the digital age, but I strongly disagree.  — check: negation_changed

## Output B

ref `o-8366370b0454`, raw sha256 `c24b54790d7a3c46bfbeeeb1cf9a9fe02f964ad45722caec5e33d8f2dd57e43c`

Format: strict (json_object), 5 options

1. I strongly disagree: public libraries are still essential despite online resources.  — check: negation_changed
2. I disagree: public libraries remain crucial, offering more than just internet access.  — check: negation_changed
3. Public libraries are indispensable, providing free internet, computers, and more.  — check: negation_changed
4. I strongly disagree: public libraries offer unique services like job help and reading groups.  — check: negation_changed
5. Public libraries are not obsolete: they offer essential services to those who can't afford them at home.  — not judged, counts as 0 (fail: not_shorter)

## Output C

ref `o-8629d7142366`, raw sha256 `5fe015e0546b7e4c248bff7407d0d7298bf46a3cd1bf6ef4878d1a349d5f90f5`

Format: strict (json_object), 5 options

1. Public libraries are essential despite online access because they provide free internet and computers, reading groups, job help, and English classes. They offer a safe and quiet place for study. Cutting library funding would disproportionately affect those with the least resources.  — not judged, counts as 0 (fail: not_shorter)
2. Public libraries are still needed as they offer free internet and computers, programs for kids and adults, and English classes for immigrants. They provide a quiet place for study and are vital for communities. Funding cuts would hurt the most vulnerable.  — not judged, counts as 0 (fail: not_shorter)
3. Libraries are crucial as they offer free internet and computers, reading groups, job help, and English classes. They provide a safe study environment for people who cannot afford it at home. Libraries must be maintained to support these services.  — not judged, counts as 0 (fail: not_shorter)
4. Libraries are necessary as they offer free internet and computers, reading groups, job help, and English classes. They are a safe and quiet place for study and support various communities. Funding cuts would negatively impact the most disadvantaged.  — not judged, counts as 0 (fail: not_shorter)
5. Despite online resources, public libraries are still needed for free internet and computers, reading groups, job help, and English classes. They provide a quiet study environment for people who cannot afford it at home. Funding cuts would disproportionately affect those with the least resources.  — not judged, counts as 0 (fail: not_shorter)
