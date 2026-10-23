# ws2-screen-p06-academic-1

Kind: `academic`, asks for 5 options.

Paragraph:

> Social media has a big effect on how teenagers see themselves. On apps like Instagram and TikTok, people usually only post the best parts of their lives, like vacations and nice clothes. When teens look at these posts all day, they start to compare themselves to others and feel bad about their own lives. A survey from 2023 found that almost half of teens said social media made them feel worse about their bodies. Social media is not all bad, though, because it also helps people stay in touch with friends and find others with the same interests. Still, I believe that teens should limit how much time they spend on these apps.

Selected: A survey from 2023 found that almost half of teens said social media made them feel worse about their bodies.

Instruction given to every model:

> Give 5 different rewrites of the selected text in a more academic register suitable for a school or college essay. Keep the same meaning and the same level of certainty. Do not add evidence, statistics, names, citations or new ideas. Put the best options first.

## Output A

ref `o-e39eac20fef3`, raw sha256 `23335a9d0f82cb9b51364356e9a00fd9ae15cc64b868e45d0f95ab462ba833a1`

Format: strict (json_object), 5 options

1. A study conducted in 2023 revealed that approximately 50% of adolescents reported negative self-perceptions due to social media usage.  — check: invented_number
2. Research from 2023 indicated that nearly half of the teenage population felt adversely about their physical appearance after engaging with social media.
3. A survey in 2023 demonstrated that about half of the teens surveyed experienced detrimental effects on their body image as a result of social media.
4. A 2023 survey found that nearly 50% of teenagers felt worse about their bodies after using social media.  — check: invented_number
5. In 2023, a survey showed that almost half of the teens felt negatively about their bodies following their social media interactions.

## Output B

ref `o-2d75f4865987`, raw sha256 `476d11a25302c56cb4b5fd060241d7902e20db7d4cc904c81a8276f2117aad2b`

Format: lenient (json_object_then_text), 5 options

1. A survey from 2023 indicates that nearly fifty percent of teenagers expressed negative feelings regarding their physical appearance.
2. According to a 2023 survey, approximately half of the teen population reported feeling dissatisfied with their bodies.
3. Research from 2023 suggests that almost half of adolescents perceive social media as negatively impacting their self-image.
4. A 2023 survey revealed that nearly fifty percent of teens felt worse about their bodies due to social media exposure.
5. The 2023 survey found that approximately half of the teen population believed social media made them feel bad about their bodies.

## Output C

ref `o-db88248480b8`, raw sha256 `22c84623f14a4998867981ff850b61b617cc5eb8a1ce7671220a08d9c047a8ae`

Format: lenient (json_object_then_text), 5 options

1. A 2023 survey revealed that nearly half of the surveyed teens indicated that social media negatively impacted their body image.
2. According to a 2023 study, over 45% of adolescents reported experiencing a decline in self-esteem due to social media usage.  — check: invented_number
3. The 2023 survey found that approximately 49% of teenagers claimed social media contributed to their dissatisfaction with their physical appearance.  — check: invented_number
4. As reported in a 2023 survey, nearly half of the respondents among teenagers expressed that social media had a detrimental effect on their body image.
5. A 2023 survey indicated that about 48% of teenagers stated that social media worsened their body image.  — check: invented_number

## Output D

ref `o-aee8256a5e86`, raw sha256 `e083368832760f4783f29b9a862e003d1fcc07d4d063cbef66114198559003d7`

Format: strict (json_object), 5 options

1. A 2023 survey indicated that nearly 50% of teenagers reported feeling negatively about their bodies due to social media.  — check: invented_number
2. Research conducted in 2023 revealed that approximately half of adolescents stated social media contributed to dissatisfaction with their physical appearance.
3. According to a 2023 survey, almost half of teens expressed that social media made them feel worse about their bodies.
4. Data from a 2023 survey showed that nearly half of teenagers claimed social media negatively impacted their body image.
5. A study from 2023 found that almost half of adolescents felt social media worsened their perception of their own bodies.

## Output E

ref `o-f409cbd6eb07`, raw sha256 `71789239e697acbcc61a3215236d700e4dd5786e8e93ee6b357e5b70f1fb0695`

Format: strict (json_object), 5 options

1. A 2023 survey indicated that nearly half of teenagers reported that social media negatively impacted their self-perception of their bodies.
2. A 2023 survey revealed that approximately half of teenagers reported that social media had a detrimental effect on their body image.
3. A 2023 survey showed that nearly half of teenagers felt that social media made them feel worse about their bodies.
4. A 2023 survey indicated that about half of teenagers reported that social media had a negative impact on their body image.
5. A 2023 survey suggested that nearly half of teenagers reported that social media made them feel worse about their bodies.  — not judged, counts as 0 (fail: duplicate)
