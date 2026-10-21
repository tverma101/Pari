# ws2-full-p26-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Every Saturday for the past two years, I have volunteered at a food bank in my neighborhood. At first, I only went because I needed community service hours for school. But after a few weeks, I started to really care about the people who came in. Many of them were working parents who just did not have enough money at the end of the month. One woman told me that the food we gave her was the only reason her kids had dinner that week. Hearing that made me realize how many people in my own town are struggling. Now I want to study social work so I can help families like hers.

Selected: Many of them were working parents who just did not have enough money at the end of the month.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-c23341b2e6dc`, raw sha256 `6760ad89526b943820a8b10433337012874396e1ad5c6243531ee218cf1b114b`

Format: strict (json_object), 5 options

1. Many were low-income working parents.  — check: negation_changed
2. Many were struggling working parents.  — check: negation_changed
3. Many were underpaid working parents.  — check: negation_changed
4. Many were working parents in need.  — check: negation_changed
5. Many were working parents with financial difficulties.  — check: negation_changed

## Output B

ref `o-561deb892fff`, raw sha256 `abdf410ffad2f2de7df9c5e24071266984e98a2a4f032539ae998fdac09a610d`

Format: strict (json_object), 5 options

1. Many were working parents struggling financially.  — check: negation_changed
2. Working parents often faced financial hardship.  — check: negation_changed
3. These people were working parents with limited funds.  — check: negation_changed
4. They were working parents who didn't have enough money.
5. Working parents in my town had financial struggles.  — check: negation_changed

## Output C

ref `o-007460d13a62`, raw sha256 `972c20a11eddc7de020325ce34ca7aa7ba7778aab5c54a4e0fc265bc96b09a50`

Format: strict (json_object), 5 options

1. Many were working parents with no money left at month's end.
2. Most were working parents short on funds by month's end.  — check: negation_changed
3. Many were working parents struggling to make it by month's end.  — check: negation_changed
4. Several were working parents who ran out of money by month's end.  — check: negation_changed
5. Many were working parents lacking funds at month's end.
