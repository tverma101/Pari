# ws2-full-p21-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> The Black Death was a plague that spread across Europe starting in 1347. It was carried by fleas that lived on rats, and it moved quickly along trade routes and through crowded cities. Within just a few years, it killed somewhere between a third and half of Europe's population. Because so many workers died, the people who survived could ask for higher pay, which made the old feudal system weaker. The plague also made a lot of people question the church, since prayers did not seem to stop the disease.

Selected: The plague also made a lot of people question the church, since prayers did not seem to stop the disease.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-f0bc44c41352`, raw sha256 `9109bb092ff4de49a084bf5b1bcecb008c33b67949533a9236b03083ec062476`

Format: strict (json_object), 5 options

1. The plague also caused people to question the church, as prayers failed to stop the disease.
2. The plague led many to doubt the church, since prayers did not halt the disease.
3. The plague made people question the church, because prayers seemed unable to stop the disease.
4. The plague caused people to question the church, as prayers did not prevent the disease.
5. The plague made people question the church, since prayers did not stop the disease.

## Output B

ref `o-1afc46aab42f`, raw sha256 `a35dc96bfaabfc0d0244cebeecaa47a8c6f6b8c0561c9c3f3190d682259edd07`

Format: strict (json_object), 5 options

1. The plague led many to doubt the church as prayers failed to halt the disease.
2. The plague caused people to question the church due to ineffective prayers.  — check: negation_changed
3. The plague made people doubt the church, as prayers didn't stop it.
4. Many questioned the church due to the plague, as prayers had no effect.
5. The plague undermined faith in the church as prayers couldn't prevent it.

## Output C

ref `o-8b430a3f8586`, raw sha256 `6c4dba641eb91a4ed8bbb4eaacf5b16036536bfc28ba192aabd99133fef8c4b1`

Format: strict (json_object), 5 options

1. The plague made prayers seem ineffective against the disease, leading many to question the church.  — check: negation_changed
2. Prayers failed to stop the plague, prompting many to doubt the church.
3. Because prayers were ineffective, the church's credibility was questioned by many.  — check: negation_changed
4. Many questioned the church after finding prayers ineffective against the plague.  — check: negation_changed
5. The plague's spread led to doubts about the church's ability to protect people through prayer.  — check: negation_changed
