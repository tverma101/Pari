# ws2-full-p30-academic-1

Kind: `academic`, asks for 5 options.

Paragraph:

> Vaccines work by teaching the immune system how to fight a disease before a person ever gets sick. They contain a weak or harmless piece of a germ, which the body learns to recognize. If the real germ shows up later, the immune system can attack it quickly. Thanks to vaccines, diseases like smallpox have been wiped out, and polio is almost gone. When enough people in a community are vaccinated, it also protects those who cannot get the shot, like newborn babies. This is called herd immunity.

Selected: When enough people in a community are vaccinated, it also protects those who cannot get the shot, like newborn babies.

Instruction given to every model:

> Give 5 different rewrites of the selected text in a more academic register suitable for a school or college essay. Keep the same meaning and the same level of certainty. Do not add evidence, statistics, names, citations or new ideas. Put the best options first.

## Output A

ref `o-1bf515de2d83`, raw sha256 `63e9097802847396bc6db0abeaa446cd6a9e93f1d6ab9754a42250c445ef49b6`

Format: strict (json_object), 5 options

1. Consequently, widespread vaccination within a community safeguards individuals who are ineligible for immunization, such as infants.  — check: negation_changed
2. This collective protection extends to those who cannot receive the vaccine, including newborns.
3. As vaccination rates increase within a population, immunity is conferred upon those unable to be vaccinated, for example, newborns.
4. Such vaccination coverage also shields vulnerable individuals, such as newborns, who cannot receive the shot.
5. Widespread immunization in a community further protects those who cannot receive the vaccine, such as newborns.

## Output B

ref `o-d75368807631`, raw sha256 `8e672c99edfedb1ec44b415d4f4cb019052123f9120bbc36721d1006652f7e3e`

Format: strict (json_object), 5 options

1. Widespread vaccination within a community confers protection to individuals who are unable to receive the vaccine, such as newborns.
2. The phenomenon known as herd immunity is achieved when sufficient individuals in a population are vaccinated, thereby safeguarding those who cannot be vaccinated, including infants.
3. In a population where a majority are immunized, unvaccinated members, particularly infants, benefit from the collective immunity.  — check: negation_changed
4. The establishment of herd immunity occurs when a substantial proportion of the community is vaccinated, consequently shielding vulnerable individuals, including newborns, from vaccine-preventable diseases.  — check: negation_changed
5. Herd immunity is attained when the vaccination rate is high enough to protect unvaccinated individuals, including newborns, within a community.  — check: negation_changed

## Output C

ref `o-6ec03666d20d`, raw sha256 `fa990396f25be5cc96c94a9ac1543f99f1ffb79dcfb6ee738ddaa4a63dab8a4a`

Format: strict (json_object), 5 options

1. Vaccination of a significant proportion of the population provides indirect protection to individuals who cannot be immunized, such as newborns.
2. A high vaccination rate within a community offers protection to those who are unable to receive the vaccine, including infants.
3. When a substantial number of individuals in a community are vaccinated, it safeguards those who cannot be vaccinated, such as infants.
4. A high level of vaccination in a community can protect unvaccinated individuals, including newborns, by creating herd immunity.  — check: negation_changed
5. The presence of a high vaccination rate within a community can offer protection to those who are not eligible for vaccination, such as infants.
